"""Remote MCP server implementation for Telnyx using FastAPI."""

import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import json
import os
import secrets
import sys
import time
from typing import Any, Dict, List, Optional, Union
import urllib.parse

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from sse_starlette.sse import EventSourceResponse

# Import existing Telnyx MCP components
from ..mcp import mcp

# Import authentication
from .auth import (
    AuthService,
    get_current_user,
)
from .auth_store import auth_store
from .schema_fixer import fix_tool_schema, validate_tool_arguments

# Import new components
from .structured_logging import (
    TraceIdMiddleware,
    configure_structlog,
    get_logger,
    get_trace_id,
    set_trace_id,
)

# Load environment variables
load_dotenv()

# Azure OAuth configuration
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_REDIRECT_URI = os.getenv(
    "AZURE_REDIRECT_URI", "http://localhost:8000/auth/callback"
)
AZURE_TOKEN_URL = (
    f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/token"
    if AZURE_TENANT_ID
    else None
)

# Configure structured logging
log_level = os.getenv("LOG_LEVEL", "INFO")
enable_pii_redaction = os.getenv("ENABLE_PII_REDACTION", "true").lower() in (
    "true",
    "1",
    "yes",
)
application_insights_key = os.getenv("APPLICATION_INSIGHTS_KEY")

configure_structlog(
    log_level=log_level,
    enable_pii_redaction=enable_pii_redaction,
    application_insights_key=application_insights_key,
)

# Use structured logger
logger = get_logger(__name__)

# Version information
__version__ = "0.5.0"
PROTOCOL_VERSION = "2025-03-26"


class TelnyxMCPServer:
    """Telnyx MCP Server implementation."""

    def __init__(self):
        """Initialize the MCP server with Telnyx tools."""
        self.tools = {}
        self.resources = {}
        self._tools_initialized = False
        self._initialized_sessions = set()  # Track initialized sessions

    async def initialize_tools(self):
        """Initialize tools from MCP instance if not already done."""
        if self._tools_initialized:
            return

        try:
            # Import all Telnyx tools to ensure they're registered with MCP
            # Import tools module to trigger tool registration
            from .. import tools  # noqa: F401

            # Get the list of tools from MCP
            tools_list = await mcp.list_tools()

            # Convert to dict format
            self.tools = {
                tool.name: {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema,
                }
                for tool in tools_list
            }

            self._tools_initialized = True
            logger.info(f"Initialized {len(self.tools)} Telnyx tools")

        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}", exc_info=True)
            self._tools_initialized = False

    def _transform_tool_schema(self, tool: Dict[str, Any]) -> Dict[str, Any]:
        """Transform tool schema using Pydantic models when available."""
        return fix_tool_schema(tool)

    async def handle_initialize(
        self,
        request_id: Any,
        params: Dict[str, Any],
        session_id: str = None,
        base_url: str = None,
    ) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        # Get client's requested protocol version
        client_version = params.get("protocolVersion", PROTOCOL_VERSION)

        # Version negotiation - we support 2025-03-26
        response_version = (
            PROTOCOL_VERSION
            if client_version == PROTOCOL_VERSION
            else client_version
        )

        # Mark session as initialized
        if session_id:
            self._initialized_sessions.add(session_id)

        # Use provided base_url or fallback to environment variable
        if not base_url:
            base_url = os.getenv("BASE_URL", "http://localhost:8000")

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": response_version,
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"subscribe": True, "listChanged": True},
                    "logging": {},
                    "auth": {
                        "oauth2": True,
                        "authorizationServers": [
                            f"{base_url}/.well-known/oauth-authorization-server"
                        ],
                    },
                },
                "serverInfo": {
                    "name": "Telnyx MCP Server",
                    "version": __version__,
                },
            },
        }

    async def handle_initialized(self, params: Dict[str, Any]) -> None:
        """Handle initialized notification from client."""
        # Client has confirmed initialization
        logger.info("Client confirmed initialization")

    async def handle_tools_list(self, request_id: Any) -> Dict[str, Any]:
        """Handle tools/list request."""
        await self.initialize_tools()

        # Transform tool schemas to flatten nested request objects
        transformed_tools = []
        for tool in self.tools.values():
            transformed_tool = self._transform_tool_schema(tool)
            transformed_tools.append(transformed_tool)

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": transformed_tools},
        }

    async def handle_tools_call(
        self, request_id: Any, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle tools/call request."""
        await self.initialize_tools()

        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in self.tools:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": f"Tool '{tool_name}' not found",
                },
            }

        try:
            # Validate arguments if we have a schema
            try:
                validated_args = validate_tool_arguments(tool_name, arguments)
                logger.info(
                    f"Validated arguments for tool {tool_name}",
                    extra={"tool": tool_name, "args_count": len(arguments)},
                )
            except Exception as validation_error:
                logger.warning(
                    f"Argument validation failed for {tool_name}: {validation_error}",
                    extra={"tool": tool_name, "error": str(validation_error)},
                )
                validated_args = (
                    arguments  # Use original arguments if validation fails
                )

            # Transform arguments if needed
            tool_schema = self.tools[tool_name].get("inputSchema", {})
            properties = tool_schema.get("properties", {})

            # If the tool expects a nested request object, wrap the arguments
            if len(properties) == 1 and "request" in properties:
                # This tool expects arguments wrapped in a request object
                transformed_args = {"request": validated_args}
            else:
                # Tool has been flattened or uses direct parameters
                transformed_args = validated_args

            # Call the tool through the existing MCP instance
            result = await mcp.call_tool(tool_name, transformed_args)

            # Format the result according to MCP protocol
            if hasattr(result, "text"):
                content = [{"type": "text", "text": result.text}]
            elif hasattr(result, "content"):
                content = result.content
            else:
                content = [{"type": "text", "text": str(result)}]

            logger.info(
                f"Tool {tool_name} executed successfully",
                extra={"tool": tool_name, "success": True},
            )

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": content},
            }

        except Exception as e:
            logger.error(
                f"Tool execution error for {tool_name}: {e}",
                extra={"tool": tool_name, "error": str(e)},
                exc_info=True,
            )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": str(e),
                },
            }

    async def handle_resources_list(self, request_id: Any) -> Dict[str, Any]:
        """Handle resources/list request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"resources": list(self.resources.values())},
        }

    async def handle_resources_read(
        self, request_id: Any, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri")

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32602,
                "message": f"Resource '{uri}' not found",
            },
        }

    async def process_message(
        self,
        message: Union[Dict, List],
        session_id: str = None,
        base_url: str = None,
    ) -> Union[Dict, List]:
        """Process a JSON-RPC message or batch."""
        if isinstance(message, list):
            # Batch request
            responses = []
            for msg in message:
                if msg.get("jsonrpc") == "2.0":
                    response = await self._process_single_message(
                        msg, session_id, base_url
                    )
                    if response:  # Only include responses for requests, not notifications
                        responses.append(response)
            return responses if responses else None
        else:
            # Single request
            return await self._process_single_message(
                message, session_id, base_url
            )

    async def _process_single_message(
        self,
        message: Dict[str, Any],
        session_id: str = None,
        base_url: str = None,
    ) -> Optional[Dict[str, Any]]:
        """Process a single JSON-RPC message."""
        if message.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32600,
                    "message": "Invalid Request - must be JSON-RPC 2.0",
                },
            }

        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id")

        # Notifications don't have id and don't get responses
        is_notification = msg_id is None

        try:
            # Route to appropriate handler
            if method == "initialize":
                response = await self.handle_initialize(
                    msg_id, params, session_id, base_url
                )
            elif method == "notifications/initialized":
                await self.handle_initialized(params)
                return None  # No response for notifications
            elif method == "tools/list":
                response = await self.handle_tools_list(msg_id)
            elif method == "tools/call":
                response = await self.handle_tools_call(msg_id, params)
            elif method == "resources/list":
                response = await self.handle_resources_list(msg_id)
            elif method == "resources/read":
                response = await self.handle_resources_read(msg_id, params)
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }

            return response if not is_notification else None

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            if not is_notification:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": str(e),
                    },
                }
            return None


# Initialize MCP server
telnyx_mcp_server = TelnyxMCPServer()


def get_base_url_from_request(request: Request) -> str:
    """Extract base URL from request, handling proxy headers."""
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    forwarded_host = request.headers.get(
        "x-forwarded-host"
    ) or request.headers.get("host")

    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}"
    else:
        return str(request.base_url).rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info(
        f"Starting Telnyx Remote MCP Server v{__version__} "
        f"(env={os.getenv('ENVIRONMENT', 'development')}, "
        f"log_level={log_level}, pii_redaction={enable_pii_redaction})"
    )
    logger.info(f"Python version: {sys.version}")

    # Log configuration details
    logger.info(
        f"Server configuration: allowed_origins={allowed_origins}, "
        f"auth_enabled={AZURE_CLIENT_ID is not None}, "
        f"redis_enabled={os.getenv('USE_REDIS', 'false').lower() == 'true'}, "
        f"app_insights={application_insights_key is not None}"
    )

    await telnyx_mcp_server.initialize_tools()
    logger.info(f"Initialized {len(telnyx_mcp_server.tools)} tools")

    yield

    logger.info("Shutting down Telnyx Remote MCP Server")


# Create FastAPI app
app = FastAPI(
    title="Telnyx Remote MCP Server",
    description="Model Context Protocol server for Telnyx API integration",
    version=__version__,
    lifespan=lifespan,
)

# Configure CORS with security considerations
allowed_origins = os.getenv("MCP_ALLOWED_ORIGINS", "*").split(",")
if allowed_origins == ["*"]:
    logger.warning(
        "CORS configured to allow all origins - this should not be used in production"
    )

# Add structured logging middleware
app.add_middleware(TraceIdMiddleware)

# Add CORS middleware with proper security
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["x-trace-id", "mcp-session-id"],
)


# Add security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to responses."""
    response = await call_next(request)

    # Add security headers
    response.headers["Strict-Transport-Security"] = os.getenv(
        "STRICT_TRANSPORT_SECURITY", "max-age=31536000; includeSubDomains"
    )
    response.headers["Referrer-Policy"] = os.getenv(
        "REFERRER_POLICY", "strict-origin-when-cross-origin"
    )

    # Configure CSP based on environment
    environment = os.getenv("ENVIRONMENT", "development")
    if environment == "production":
        # Stricter CSP for production - no unsafe-inline
        default_csp = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'"
    else:
        # More permissive CSP for development
        default_csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"

    response.headers["Content-Security-Policy"] = os.getenv(
        "CONTENT_SECURITY_POLICY", default_csp
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"

    return response


# Add CORS violation logging middleware
@app.middleware("http")
async def log_cors_violations(request: Request, call_next):
    """Log potential CORS violations."""
    origin = request.headers.get("origin")

    if origin and origin not in allowed_origins and "*" not in allowed_origins:
        logger.warning(
            f"CORS violation detected: origin={origin}, "
            f"url={request.url}, method={request.method}"
        )

    response = await call_next(request)
    return response


# Add request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming HTTP requests with structured logging."""
    start_time = time.time()

    # Generate or get trace ID
    trace_id = get_trace_id()
    if not trace_id:
        trace_id = str(secrets.token_hex(8))
        set_trace_id(trace_id)

    # Log request details (PII will be redacted by processor)
    logger.debug(
        f"HTTP {request.method} {request.url.path} from "
        f"{request.client.host if request.client else 'unknown'}"
    )

    # Process request
    response = await call_next(request)

    # Log response details
    process_time = time.time() - start_time
    logger.debug(
        f"HTTP {request.method} {request.url.path} completed with "
        f"status {response.status_code} in {process_time:.3f}s"
    )

    return response


@app.get("/")
async def root(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Root endpoint - handles both server info and SSE streams based on Accept header."""
    logger.info(
        "ROOT GET endpoint called",
        url=str(request.url),
        current_user=current_user,
        accept=request.headers.get("accept", "None"),
        client_ip=request.headers.get(
            "x-client-ip", request.client.host if request.client else "unknown"
        ),
    )
    logger.debug(f"Request headers: {dict(request.headers)}")

    # Check if this is an SSE request
    accept_header = request.headers.get("accept", "")
    if "text/event-stream" in accept_header:
        # This is Claude Desktop trying to establish an SSE connection
        # Redirect to the MCP SSE endpoint
        return await mcp_sse_stream(request, current_user)

    # Regular GET request - return server info
    base_url = os.getenv(
        "BASE_URL", "https://app-web-3ky2b33hy2dpm.azurewebsites.net"
    )
    return {
        "name": "Telnyx Remote MCP Server",
        "version": __version__,
        "protocol_version": PROTOCOL_VERSION,
        "status": "healthy",
        "endpoints": {
            "mcp": "/mcp",
            "oauth_authorization_server": "/.well-known/oauth-authorization-server",
            "health": "/health",
        },
        "tools_available": len(telnyx_mcp_server.tools),
    }


@app.post("/")
async def root_post(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
):
    """POST endpoint at root - handles MCP protocol requests."""
    logger.info(
        "ROOT POST endpoint called - redirecting to MCP handler",
        url=str(request.url),
        auth_header=request.headers.get("authorization", "None"),
        client_ip=request.headers.get(
            "x-client-ip", request.client.host if request.client else "unknown"
        ),
    )

    # Claude Desktop is trying to POST to root - handle it as MCP protocol
    return await mcp_endpoint(request, credentials)


@app.get("/health")
async def health_check():
    """Health check endpoint with readiness probe functionality."""
    logger.debug("Health check requested")
    health_data = {
        "status": "healthy",
        "service": "telnyx-mcp-server",
        "version": __version__,
        "git_commit": os.getenv("GIT_COMMIT_HASH", "unknown"),
        "protocol_version": PROTOCOL_VERSION,
        "timestamp": time.time(),
    }

    # Check auth store health
    try:
        if hasattr(auth_store, "health_check"):
            auth_health = await auth_store.health_check()
            health_data["auth_store"] = auth_health
        else:
            health_data["auth_store"] = {
                "type": "in_memory",
                "status": "healthy",
            }
    except Exception as e:
        logger.error(f"Auth store health check failed: {e}")
        health_data["auth_store"] = {"status": "unhealthy", "error": str(e)}

    # Check MCP tools initialization
    try:
        await telnyx_mcp_server.initialize_tools()
        health_data["mcp_tools"] = {
            "status": "healthy",
            "tools_count": len(telnyx_mcp_server.tools),
        }
    except Exception as e:
        logger.error(f"MCP tools health check failed: {e}")
        health_data["mcp_tools"] = {"status": "unhealthy", "error": str(e)}

    # Determine overall health
    is_healthy = all(
        component.get("status") == "healthy"
        for component in [
            health_data.get("auth_store", {}),
            health_data.get("mcp_tools", {}),
        ]
        if isinstance(component, dict)
    )

    if not is_healthy:
        health_data["status"] = "unhealthy"
        return Response(
            content=json.dumps(health_data),
            status_code=503,
            media_type="application/json",
        )

    return health_data


@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata(request: Request):
    """OAuth 2.0 Protected Resource Metadata (RFC9728)."""
    logger.info("=" * 50)
    logger.info("OAUTH PROTECTED RESOURCE METADATA called")
    logger.info(f"Request URL: {request.url}")
    logger.info(f"All headers: {dict(request.headers)}")
    logger.info("=" * 50)

    # Get base URL from request, handling proxy headers
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    forwarded_host = request.headers.get(
        "x-forwarded-host"
    ) or request.headers.get("host")

    if forwarded_proto and forwarded_host:
        # Running behind a proxy (like Azure App Service)
        base_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        # Direct access
        base_url = str(request.base_url).rstrip("/")

    response = {
        "resource": f"{base_url}/mcp",  # Point to the MCP endpoint specifically
        "authorization_servers": [base_url],  # We are the authorization server
        "scopes_supported": [
            "openid",
            "profile",
            "email",
            "mcp:read",
            "mcp:write",
            "mcp:execute",
        ],
        "bearer_methods_supported": ["header"],
        "resource_signing_alg_values_supported": [
            "HS256"
        ],  # Changed to match our JWT signing
        "resource_documentation": f"{base_url}/docs",
        "resource_policy_uri": f"{base_url}/privacy",
        "resource_tos_uri": f"{base_url}/terms",
    }

    logger.info(f"Returning metadata: {json.dumps(response, indent=2)}")
    return response


@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request):
    """OAuth 2.0 Authorization Server Metadata (RFC8414)."""
    # Get base URL from request, handling proxy headers
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    forwarded_host = request.headers.get(
        "x-forwarded-host"
    ) or request.headers.get("host")

    if forwarded_proto and forwarded_host:
        # Running behind a proxy (like Azure App Service)
        base_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        # Direct access
        base_url = str(request.base_url).rstrip("/")

    # Check if running with Built-in Auth enabled
    builtin_auth_enabled = (
        os.getenv("WEBSITE_AUTH_ENABLED", "false").lower() == "true"
    )

    metadata = {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "userinfo_endpoint": f"{base_url}/userinfo",
        "registration_endpoint": f"{base_url}/register",
        # Note: We use HS256 for JWT signing, not RS256 from Azure
        # Remove jwks_uri to avoid confusion since we don't publish our symmetric key
        # "jwks_uri": f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys" if AZURE_TENANT_ID else None,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["HS256"],
        "scopes_supported": [
            "openid",
            "profile",
            "email",
            "User.Read",
            "mcp:read",
            "mcp:write",
            "mcp:execute",
        ],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "claims_supported": ["sub", "email", "name", "exp", "iat"],
        "service_documentation": f"{base_url}/docs",
    }

    # Add Built-in Auth information when enabled
    if builtin_auth_enabled:
        metadata["authorization_endpoint_alternatives"] = {
            "builtin_auth": {
                "endpoint": f"{base_url}/.auth/login/aad",
                "description": "Azure App Service Built-in Authentication (Easy Auth)",
                "type": "browser_based",
            }
        }
        metadata["authentication_methods_supported"] = [
            "oauth2_authorization_code",
            "azure_builtin_auth",
        ]

    return metadata


@app.get("/.well-known/mcp-oauth-metadata")
async def mcp_oauth_metadata(request: Request):
    """MCP OAuth 2.0 Metadata endpoint for Claude."""
    # Get base URL from request, handling proxy headers
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    forwarded_host = request.headers.get(
        "x-forwarded-host"
    ) or request.headers.get("host")

    if forwarded_proto and forwarded_host:
        # Running behind a proxy (like Azure App Service)
        base_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        # Direct access
        base_url = str(request.base_url).rstrip("/")

    # Check if running with Built-in Auth enabled
    builtin_auth_enabled = (
        os.getenv("WEBSITE_AUTH_ENABLED", "false").lower() == "true"
    )

    metadata = {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "scopes_supported": [
            "openid",
            "profile",
            "email",
            "mcp:read",
            "mcp:write",
            "mcp:execute",
        ],
        "code_challenge_methods_supported": ["S256"],
    }

    # Add Built-in Auth information when enabled
    if builtin_auth_enabled:
        metadata["azure_builtin_auth"] = {
            "enabled": True,
            "login_endpoint": f"{base_url}/.auth/login/aad",
            "logout_endpoint": f"{base_url}/.auth/logout",
            "description": "Azure App Service Built-in Authentication is enabled. Browser-based clients can use the login endpoint directly.",
        }

    return metadata


@app.get("/.well-known/openid-configuration")
async def openid_configuration(request: Request):
    """OpenID Connect Discovery endpoint."""
    # Get base URL from request, handling proxy headers
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    forwarded_host = request.headers.get(
        "x-forwarded-host"
    ) or request.headers.get("host")

    if forwarded_proto and forwarded_host:
        # Running behind a proxy (like Azure App Service)
        base_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        # Direct access
        base_url = str(request.base_url).rstrip("/")

    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "userinfo_endpoint": f"{base_url}/userinfo",
        # Note: We use HS256 for JWT signing, not RS256 from Azure
        # Remove jwks_uri to avoid confusion since we don't publish our symmetric key
        # "jwks_uri": f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys" if AZURE_TENANT_ID else None,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["HS256"],
        "scopes_supported": [
            "openid",
            "profile",
            "email",
            "mcp:read",
            "mcp:write",
            "mcp:execute",
        ],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "claims_supported": ["sub", "email", "name", "exp", "iat"],
    }


@app.get("/.well-known/mcp-metadata")
async def mcp_metadata(request: Request):
    """MCP Metadata endpoint for Claude Desktop discovery."""
    # Get base URL from request, handling proxy headers
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    forwarded_host = request.headers.get(
        "x-forwarded-host"
    ) or request.headers.get("host")

    if forwarded_proto and forwarded_host:
        # Running behind a proxy (like Azure App Service)
        base_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        # Direct access
        base_url = str(request.base_url).rstrip("/")

    return {
        "mcpVersion": "2025-03-26",
        "serverInfo": {"name": "Telnyx MCP Server", "version": __version__},
        "auth": {
            "type": "oauth2",
            "oauth2": {
                "authorizationEndpoint": f"{base_url}/authorize",
                "tokenEndpoint": f"{base_url}/token",
                "scopes": [
                    "openid",
                    "profile",
                    "email",
                    "mcp:read",
                    "mcp:write",
                    "mcp:execute",
                ],
                "pkce": True,
            },
        },
        "capabilities": {
            "tools": True,
            "resources": True,
            "prompts": False,
            "logging": True,
        },
    }


@app.get("/.well-known/mcp-oauth-metadata")
async def mcp_oauth_metadata(request: Request):
    """MCP OAuth Metadata endpoint - alias for mcp-metadata."""
    # Just redirect to the mcp-metadata endpoint
    return await mcp_metadata(request)


@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource(request: Request):
    """OAuth 2.0 Protected Resource Metadata (RFC 8897).

    This tells clients about the authorization server for this protected resource.
    """
    # Get base URL from request
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    forwarded_host = request.headers.get(
        "x-forwarded-host"
    ) or request.headers.get("host")

    if forwarded_proto and forwarded_host:
        base_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        base_url = str(request.base_url).rstrip("/")

    return {
        "resource": base_url,
        "authorization_servers": [
            f"{base_url}/.well-known/oauth-authorization-server"
        ],
        "bearer_methods_supported": ["header"],
        "resource_signing_alg_values_supported": ["HS256"],
        "resource_documentation": f"{base_url}/docs",
        "resource_policy_uri": f"{base_url}/privacy",
        "resource_tos_uri": f"{base_url}/terms",
    }


# OAuth 2.0 endpoints (simplified for MCP)
@app.get("/authorize")
async def authorize(
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    scope: str = "openid profile email",
    state: Optional[str] = None,
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = "S256",
):
    """OAuth 2.0 Authorization endpoint - initiates the two-layer OAuth flow."""
    # For public clients like Claude Desktop, accept any client_id
    # In production, you'd validate against registered clients
    logger.info(f"Authorization request from client_id: {client_id}")

    # Validate response_type
    if response_type != "code":
        return Response(
            content="Only response_type=code is supported", status_code=400
        )

    # PKCE is MANDATORY for public clients (RFC 7636)
    if not code_challenge:
        logger.error(f"Missing code_challenge from client_id: {client_id}")
        return Response(
            content="code_challenge is required for public clients",
            status_code=400,
        )

    # Validate code_challenge_method - only S256 allowed for security
    if code_challenge_method != "S256":
        logger.error(f"Invalid code_challenge_method: {code_challenge_method}")
        return Response(
            content="Only S256 code_challenge_method is supported",
            status_code=400,
        )

    # Generate a unique state for Azure AD if not provided
    azure_state = state or secrets.token_urlsafe(32)

    # Create a session to track this OAuth flow
    session_id = auth_store.create_session(
        state=azure_state,
        redirect_uri=redirect_uri,
        pkce_challenge=code_challenge,
        pkce_method=code_challenge_method,
    )

    logger.info(
        f"Created OAuth session {session_id[:8]}... for redirect_uri: {redirect_uri}"
    )

    # Get Azure AD authorization URL with our generated state
    auth_url = AuthService.get_authorization_url(azure_state)

    # Redirect to Azure AD
    return RedirectResponse(url=auth_url, status_code=302)


@app.post("/token")
async def token(request: Request):
    """OAuth 2.0 Token endpoint - exchanges MCP auth code for JWT token."""
    logger.info("=" * 50)
    logger.info("TOKEN endpoint called")
    logger.info(f"Request URL: {request.url}")
    logger.info(f"All headers: {dict(request.headers)}")

    form_data = await request.form()
    logger.info(f"Form data keys: {list(form_data.keys())}")

    code = form_data.get("code")
    grant_type = form_data.get("grant_type")
    client_id = form_data.get("client_id")
    code_verifier = form_data.get("code_verifier")  # PKCE

    logger.info(f"grant_type: {grant_type}")
    logger.info(f"client_id: {client_id}")
    logger.info(
        f"code (first 20 chars): {code[:20] if code and len(code) >= 20 else code}"
    )
    logger.info(f"code_verifier present: {code_verifier is not None}")
    logger.info("=" * 50)

    # Validate grant type
    if grant_type != "authorization_code":
        return Response(
            content=json.dumps(
                {
                    "error": "unsupported_grant_type",
                    "error_description": "Only authorization_code grant type is supported",
                }
            ),
            status_code=400,
            media_type="application/json",
        )

    if not code:
        return Response(
            content=json.dumps(
                {
                    "error": "invalid_request",
                    "error_description": "Missing authorization code",
                }
            ),
            status_code=400,
            media_type="application/json",
        )

    try:
        # Retrieve the MCP auth code from our store
        auth_code_data = auth_store.get_auth_code(code)

        if not auth_code_data:
            logger.warning(f"Invalid or expired MCP auth code: {code[:8]}...")
            return Response(
                content=json.dumps(
                    {
                        "error": "invalid_grant",
                        "error_description": "Authorization code is invalid or expired",
                    }
                ),
                status_code=400,
                media_type="application/json",
            )

        # Mark the code as used to prevent replay attacks
        auth_store.mark_code_used(code)

        # PKCE validation is MANDATORY for public clients (RFC 7636)
        if auth_code_data.pkce_challenge:
            if not code_verifier:
                logger.error(
                    "PKCE code_verifier missing for code with challenge"
                )
                return Response(
                    content=json.dumps(
                        {
                            "error": "invalid_request",
                            "error_description": "code_verifier is required for PKCE",
                        }
                    ),
                    status_code=400,
                    media_type="application/json",
                )

            # Validate PKCE - compute challenge from verifier and compare
            if auth_code_data.pkce_method == "S256":
                # SHA256 hash the verifier and base64url encode
                verifier_bytes = code_verifier.encode("ascii")
                challenge_bytes = hashlib.sha256(verifier_bytes).digest()
                computed_challenge = (
                    base64.urlsafe_b64encode(challenge_bytes)
                    .decode("ascii")
                    .rstrip("=")
                )
            else:
                # Plain method not allowed for security
                logger.error(
                    f"Unsupported PKCE method: {auth_code_data.pkce_method}"
                )
                return Response(
                    content=json.dumps(
                        {
                            "error": "invalid_request",
                            "error_description": "Only S256 code_challenge_method is supported",
                        }
                    ),
                    status_code=400,
                    media_type="application/json",
                )

            # Compare with stored challenge
            if computed_challenge != auth_code_data.pkce_challenge:
                logger.error("PKCE verification failed - challenge mismatch")
                return Response(
                    content=json.dumps(
                        {
                            "error": "invalid_grant",
                            "error_description": "PKCE verification failed",
                        }
                    ),
                    status_code=400,
                    media_type="application/json",
                )

        # Create JWT token using the stored user info and Azure token
        user_info = auth_code_data.user_info
        logger.info(f"Creating JWT for user: {user_info}")

        jwt_token = AuthService.create_jwt_token(user_info)

        logger.info(f"JWT token created successfully")
        logger.info(f"Token (first 50 chars): {jwt_token[:50]}...")
        logger.info(
            f"Issued JWT token for user: {user_info.get('mail', user_info.get('userPrincipalName'))}"
        )

        # Get base URL for MCP endpoint discovery
        base_url = get_base_url_from_request(request)

        # Standard OAuth token response
        return {
            "access_token": jwt_token,
            "token_type": "Bearer",
            "expires_in": 86400,  # 24 hours in seconds
            "scope": "openid profile email mcp:read mcp:write mcp:execute",
        }

    except Exception as e:
        logger.error(f"Token exchange error: {e}", exc_info=True)
        return Response(
            content=json.dumps(
                {
                    "error": "server_error",
                    "error_description": "An internal error occurred",
                }
            ),
            status_code=500,
            media_type="application/json",
        )


@app.get("/userinfo")
async def userinfo(user: Dict[str, Any] = Depends(get_current_user)):
    """OpenID Connect UserInfo endpoint."""
    return {
        "sub": user.get("sub"),
        "email": user.get("email"),
        "name": user.get("name"),
        "email_verified": True,
        "updated_at": int(time.time()),
    }


@app.get("/auth/callback")
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """OAuth 2.0 callback endpoint - handles the two-layer OAuth flow.

    This endpoint:
    1. Receives the authorization code from Azure AD
    2. Exchanges it for Azure AD tokens
    3. Generates an MCP-specific authorization code
    4. Redirects back to Claude.ai with the MCP code
    """
    if error:
        # Azure AD returned an error
        logger.error(f"OAuth callback error: {error} - {error_description}")
        html_content = f"""
        <html>
        <head><title>Authorization Failed</title></head>
        <body>
            <h1>Authorization Failed</h1>
            <p>Error: {error}</p>
            <p>Description: {error_description or "Authorization failed"}</p>
            <p>You can close this window and try again.</p>
        </body>
        </html>
        """
        return Response(content=html_content, media_type="text/html")

    if not code:
        logger.error("OAuth callback missing authorization code")
        html_content = """
        <html>
        <head><title>Authorization Failed</title></head>
        <body>
            <h1>Authorization Failed</h1>
            <p>Missing authorization code</p>
            <p>You can close this window and try again.</p>
        </body>
        </html>
        """
        return Response(content=html_content, media_type="text/html")

    try:
        # Find the session by state parameter
        session = None
        if state:
            session = auth_store.get_session_by_state(state)
            if not session:
                logger.warning(f"Session not found for state: {state}")

        # Exchange the Azure AD code for tokens
        logger.info("Exchanging Azure AD code for tokens")
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                AZURE_TOKEN_URL,
                data={
                    "client_id": AZURE_CLIENT_ID,
                    "client_secret": AZURE_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": AZURE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )

            if token_response.status_code != 200:
                logger.error(
                    f"Azure token exchange failed: {token_response.text}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to exchange authorization code",
                )

            azure_token_data = token_response.json()
            azure_access_token = azure_token_data.get("access_token")

            if not azure_access_token:
                logger.error("No access token in Azure response")
                raise HTTPException(
                    status_code=500,
                    detail="No access token received from Azure",
                )

        # Get user info from Azure
        logger.info("Fetching user info from Azure AD")
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {azure_access_token}"},
            )

            if user_response.status_code != 200:
                logger.error(f"Failed to get user info: {user_response.text}")
                raise HTTPException(
                    status_code=500, detail="Failed to get user information"
                )

            user_info = user_response.json()
            logger.info(
                f"Retrieved user info for: {user_info.get('mail', user_info.get('userPrincipalName'))}"
            )

        # Generate MCP-specific authorization code
        mcp_auth_code = auth_store.create_auth_code(
            azure_token=azure_access_token,
            azure_token_data=azure_token_data,
            user_info=user_info,
            state=state,
            redirect_uri=session.redirect_uri if session else None,
            pkce_challenge=session.pkce_challenge if session else None,
            pkce_method=session.pkce_method if session else None,
        )

        logger.info(f"Generated MCP auth code: {mcp_auth_code[:8]}...")

        # Check if this is a browser flow or Claude.ai flow
        # For now, we'll detect Claude by looking for the session
        if session and session.redirect_uri:
            # This is part of a proper OAuth flow with a redirect URI
            # Build the redirect URL back to Claude.ai
            redirect_params = {"code": mcp_auth_code, "state": state}

            # Parse the redirect URI and add parameters
            if "?" in session.redirect_uri:
                redirect_url = f"{session.redirect_uri}&{urllib.parse.urlencode(redirect_params)}"
            else:
                redirect_url = f"{session.redirect_uri}?{urllib.parse.urlencode(redirect_params)}"

            logger.info(f"Redirecting to Claude.ai: {redirect_url}")
            return RedirectResponse(url=redirect_url, status_code=302)

        # For browser-based flows or testing, show success page with the MCP code
        html_content = f"""
        <html>
        <head>
            <title>Authorization Complete</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    background-color: #f5f5f5;
                    padding: 1rem;
                }}
                .container {{
                    text-align: center;
                    padding: 2rem;
                    background-color: white;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    max-width: 500px;
                    width: 100%;
                }}
                .success {{
                    color: #22c55e;
                    font-size: 3rem;
                    margin-bottom: 1rem;
                }}
                h1 {{
                    margin: 0 0 1rem 0;
                    color: #1a1a1a;
                    font-size: 1.5rem;
                    font-weight: 600;
                }}
                p {{
                    color: #666;
                    margin: 0.5rem 0;
                    line-height: 1.5;
                }}
                .code-box {{
                    background-color: #f3f4f6;
                    border: 1px solid #e5e7eb;
                    border-radius: 4px;
                    padding: 1rem;
                    margin: 1.5rem 0;
                    font-family: monospace;
                    font-size: 0.875rem;
                    word-break: break-all;
                    user-select: all;
                }}
                .instructions {{
                    text-align: left;
                    margin: 1.5rem 0;
                    padding: 1rem;
                    background-color: #f9fafb;
                    border-radius: 4px;
                }}
                .instructions li {{
                    margin: 0.5rem 0;
                    color: #374151;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="success">✓</div>
                <h1>Authorization Complete</h1>
                <p>You have successfully authenticated with Azure AD.</p>
                <p>Your MCP authorization code is:</p>
                <div class="code-box">{mcp_auth_code}</div>
                <div class="instructions">
                    <p><strong>Next steps:</strong></p>
                    <ol>
                        <li>Copy the authorization code above</li>
                        <li>Return to Claude.ai</li>
                        <li>Complete the connection process</li>
                    </ol>
                </div>
                <p style="margin-top: 2rem; font-size: 0.875rem; color: #999;">
                    This code expires in 10 minutes and can only be used once.
                </p>
            </div>
        </body>
        </html>
        """

        return Response(content=html_content, media_type="text/html")

    except Exception as e:
        logger.error(f"OAuth callback error: {str(e)}", exc_info=True)
        html_content = f"""
        <html>
        <head><title>Authorization Failed</title></head>
        <body>
            <h1>Authorization Failed</h1>
            <p>An error occurred during authentication.</p>
            <p>Error: {str(e)}</p>
            <p>Please close this window and try again.</p>
        </body>
        </html>
        """
        return Response(
            content=html_content, media_type="text/html", status_code=500
        )


@app.post("/register")
async def register(request: Request):
    """OAuth 2.0 Dynamic Client Registration (RFC7591).

    Since we're using Azure AD, we return our pre-registered app details.
    """
    try:
        client_data = await request.json()
    except:
        client_data = {}

    # Return our Azure AD app registration
    # For public clients, we return an empty string for client_secret
    return {
        "client_id": AZURE_CLIENT_ID,
        "client_secret": "",  # Empty string for public client
        "registration_access_token": "",
        "registration_client_uri": "",
        "client_id_issued_at": int(datetime.utcnow().timestamp()),
        "client_secret_expires_at": 0,
        "redirect_uris": [AZURE_REDIRECT_URI],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",  # Public client
        "application_type": "web",
        "token_endpoint_auth_signing_alg": "RS256",
    }


# MCP Protocol Endpoints
# OPTIONS handling removed - CORS middleware handles preflight requests


@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
):
    """MCP endpoint implementing Streamable HTTP transport.

    Authentication is required for all methods except initialize.
    """
    # Get base URL first
    base_url = get_base_url_from_request(request)

    # Parse the request body first to check method
    message = None
    current_user = None
    try:
        body = await request.body()
        logger.debug(
            f"Request body: {body.decode('utf-8') if body else 'None'}"
        )
        message = json.loads(body)

        # Determine if this request requires authentication
        requires_auth = True
        method = ""
        if isinstance(message, dict):
            method = message.get("method", "")
            # Only initialize and its notification are allowed without auth
            if method in ["initialize", "notifications/initialized"]:
                requires_auth = False

        # If auth is required, check authentication
        if requires_auth:
            try:
                # First try Built-in Auth header
                current_user = AuthService.extract_user_from_header(request)
                if not current_user and credentials:
                    # Fall back to JWT token from MSAL
                    token = credentials.credentials
                    current_user = AuthService.decode_jwt_token(token)

                if not current_user:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authentication required",
                    )
            except HTTPException:
                headers = {
                    "WWW-Authenticate": f'Bearer realm="MCP Server", resource_metadata_uri="{base_url}/.well-known/oauth-protected-resource"',
                    "Link": f'<{base_url}/.well-known/oauth-authorization-server>; rel="oauth-authorization-server"',
                }

                # Determine response ID for error
                response_id = None
                if isinstance(message, dict):
                    response_id = message.get("id")

                return Response(
                    content=json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": response_id,
                            "error": {
                                "code": -32000,
                                "message": "Authentication required",
                                "data": {
                                    "type": "oauth2",
                                    "authorization_url": f"{base_url}/authorize",
                                    "metadata_url": f"{base_url}/.well-known/oauth-authorization-server",
                                },
                            },
                        }
                    ),
                    status_code=401,
                    headers=headers,
                    media_type="application/json",
                )

        # Comprehensive logging
        logger.info(
            "MCP POST endpoint called",
            url=str(request.url),
            method=request.method,
            auth_header=request.headers.get("authorization", "None"),
            current_user=current_user,
            accept=request.headers.get("accept", "None"),
            content_type=request.headers.get("content-type", "None"),
            client_ip=request.headers.get(
                "x-client-ip",
                request.client.host if request.client else "unknown",
            ),
            session_id=request.headers.get("mcp-session-id", "None"),
            mcp_method=method,
        )
        # Log all headers separately for debugging
        logger.debug(f"Request headers: {dict(request.headers)}")

    except json.JSONDecodeError as e:
        # Return parse error
        error_response = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32700,
                "message": "Parse error",
                "data": str(e),
            },
        }
        return JSONResponse(error_response)
    # Check Accept header
    accept_header = request.headers.get("accept", "application/json")
    prefers_sse = "text/event-stream" in accept_header

    # Get session ID if provided
    session_id = request.headers.get("mcp-session-id")

    # Log request
    if message:
        if isinstance(message, list):
            methods = [
                msg.get("method") for msg in message if isinstance(msg, dict)
            ]
            logger.info(
                "MCP batch request",
                methods=methods,
                user_email=current_user.get("email")
                if current_user
                else "anonymous",
            )
        else:
            logger.info(
                "MCP request",
                method=message.get("method"),
                user_email=current_user.get("email")
                if current_user
                else "anonymous",
            )

    # Get base URL for OAuth discovery
    base_url = get_base_url_from_request(request)

    # Process the message(s)
    response = await telnyx_mcp_server.process_message(
        message, session_id, base_url
    )

    # Handle response format based on message type and Accept header
    if response is None:
        # Notification - return 202 Accepted with no body
        return Response(status_code=202)

    # Check if this contains only responses (no requests)
    is_batch = isinstance(response, list)
    contains_requests = False

    if is_batch:
        for resp in response:
            if "result" in resp or "error" in resp:
                # This is a response to a request
                contains_requests = True
                break
    else:
        if "result" in response or "error" in response:
            contains_requests = True

    # Return appropriate format
    if prefers_sse and contains_requests:

        async def event_generator():
            if is_batch:
                # Send each response as a separate SSE event
                for resp in response:
                    yield {"data": json.dumps(resp)}
            else:
                yield {"data": json.dumps(response)}

        headers = {}
        if session_id:
            headers["mcp-session-id"] = session_id

        # CORS headers handled by middleware
        return EventSourceResponse(event_generator(), headers=headers)
    else:
        # Return JSON response
        headers = {}
        if session_id:
            headers["mcp-session-id"] = session_id

        # CORS headers handled by middleware

        return Response(
            content=json.dumps(response),
            media_type="application/json",
            headers=headers,
        )


@app.get("/mcp")
async def mcp_sse_stream(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """GET endpoint for server-initiated SSE stream."""
    # Comprehensive logging
    logger.info(
        "MCP GET endpoint called",
        url=str(request.url),
        method=request.method,
        auth_header=request.headers.get("authorization", "None"),
        current_user=current_user,
        accept=request.headers.get("accept", "None"),
        client_ip=request.headers.get(
            "x-client-ip", request.client.host if request.client else "unknown"
        ),
        session_id=request.headers.get("mcp-session-id", "None"),
    )
    # Log all headers separately for debugging
    logger.debug(f"Request headers: {dict(request.headers)}")

    # SSE streams also require authentication
    if not current_user:
        base_url = get_base_url_from_request(request)
        headers = {
            "WWW-Authenticate": f'Bearer realm="MCP Server", resource_metadata_uri="{base_url}/.well-known/oauth-protected-resource"',
            "Link": f'<{base_url}/.well-known/oauth-authorization-server>; rel="oauth-authorization-server"',
        }

        # Return the same response as POST /mcp for consistency
        return Response(
            content=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32000,
                        "message": "Authentication required",
                        "data": {
                            "type": "oauth2",
                            "authorization_url": f"{base_url}/authorize",
                            "metadata_url": f"{base_url}/.well-known/oauth-authorization-server",
                        },
                    },
                }
            ),
            status_code=401,
            headers=headers,
            media_type="application/json",
        )

    # Get session ID if provided
    session_id = request.headers.get("mcp-session-id")

    # Check Accept header
    accept_header = request.headers.get("accept", "")
    if "text/event-stream" not in accept_header:
        return Response(
            status_code=405,
            content="Method not allowed - this endpoint requires Accept: text/event-stream",
        )

    async def event_generator():
        # For now, just keep the connection open
        # In a real implementation, this would send server-initiated messages
        try:
            while True:
                await asyncio.sleep(30)  # Send keepalive every 30 seconds
                yield {"event": "ping", "data": ""}
        except asyncio.CancelledError:
            logger.info("SSE stream closed")

    headers = {}
    if session_id:
        headers["mcp-session-id"] = session_id

    return EventSourceResponse(event_generator(), headers=headers)


def main():
    """Main entry point for the remote server."""
    import uvicorn

    uvicorn.run(
        "telnyx_mcp_server.remote.server:app",
        host="0.0.0.0",
        port=8000,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
