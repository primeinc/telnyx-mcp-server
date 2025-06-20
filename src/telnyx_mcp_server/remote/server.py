"""Remote MCP server implementation for Telnyx using FastAPI with Azure Easy Auth."""

from contextlib import asynccontextmanager
import json
import os
import secrets
import sys
import time
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Import existing Telnyx MCP components
from ..mcp import mcp

# Import Azure Easy Auth components
from .auth.azure import (
    AzureClientPrincipal,
    AzureEasyAuthMiddleware,
    get_current_user,
)
from .auth.azure.config import get_azure_auth_config
from .schema_fixer import fix_tool_schema, validate_tool_arguments

# Import structured logging
from .structured_logging import (
    TraceIdMiddleware,
    configure_structlog,
    get_logger,
    get_trace_id,
    set_trace_id,
)

# Load environment variables
load_dotenv()

# Get configuration
config = get_azure_auth_config()

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


def load_git_info() -> Dict[str, str]:
    """Load git information from embedded file or environment."""
    git_info = {
        "commit": "unknown",
        "branch": "unknown",
        "build_time": "unknown",
        "build_number": "unknown",
    }

    # Load from git_info.json file created by GitHub workflow
    try:
        # This file is located in src/git_info.json in the deployment
        src_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        git_info_path = os.path.join(src_dir, "git_info.json")
        with open(git_info_path, "r") as f:
            file_info = json.load(f)
            git_info.update(file_info)
            # Return first 7 characters of commit hash
            if git_info["commit"] != "unknown":
                git_info["commit"] = git_info["commit"][:7]
            return git_info
    except Exception as e:
        logger.warning(
            f"Could not load git_info.json from {git_info_path}: {e}"
        )
        # For local development, try git command
        try:
            import subprocess

            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            git_info["commit"] = result.stdout.strip()
        except Exception:
            pass

    return git_info


# Load git info at startup
GIT_INFO = load_git_info()
GIT_COMMIT = GIT_INFO["commit"]


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
        f"(commit={GIT_COMMIT}, env={config.environment}, "
        f"log_level={log_level}, pii_redaction={enable_pii_redaction})"
    )
    logger.info(f"Python version: {sys.version}")

    # Log configuration
    config.log_configuration(logger)

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

# Add structured logging middleware
app.add_middleware(TraceIdMiddleware)

# Add Azure Easy Auth middleware
app.add_middleware(AzureEasyAuthMiddleware)

# Add CORS middleware with configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allowed_origins,
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
    response.headers["Strict-Transport-Security"] = (
        config.strict_transport_security
    )
    response.headers["Referrer-Policy"] = config.referrer_policy
    response.headers["Content-Security-Policy"] = config.get_csp_header()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"

    return response


# Add COMPREHENSIVE request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log ALL incoming HTTP requests with FULL details."""
    start_time = time.time()

    # Generate or get trace ID
    trace_id = get_trace_id()
    if not trace_id:
        trace_id = str(secrets.token_hex(8))
        set_trace_id(trace_id)

    # Read request body
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8") if body_bytes else "<empty>"

    # Log EVERYTHING about the request
    logger.debug(
        f"\n{'=' * 80}\n"
        f"INCOMING REQUEST - {trace_id}\n"
        f"{'=' * 80}\n"
        f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Method: {request.method}\n"
        f"URL: {request.url}\n"
        f"Path: {request.url.path}\n"
        f"Query: {request.url.query}\n"
        f"Client: {request.client}\n"
        f"Headers:\n"
    )

    # Log all headers
    for header_name, header_value in request.headers.items():
        logger.debug(f"  {header_name}: {header_value}")

    logger.debug(f"\nBody ({len(body_bytes)} bytes):\n{body_str}\n{'=' * 80}")

    # Create new request with body for downstream handlers
    async def receive():
        return {"type": "http.request", "body": body_bytes}

    request._receive = receive

    # Process request
    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(f"ERROR processing request: {e}", exc_info=True)
        raise

    # Log response details
    process_time = time.time() - start_time
    logger.debug(
        f"\nRESPONSE - {trace_id}\n"
        f"Status: {response.status_code}\n"
        f"Time: {process_time:.3f}s\n"
        f"{'=' * 80}\n"
    )

    return response


@app.get("/")
async def root(request: Request):
    """Root endpoint - returns server info."""
    logger.info(
        "ROOT GET endpoint called",
        url=str(request.url),
        accept=request.headers.get("accept", "None"),
        client_ip=request.headers.get(
            "x-client-ip", request.client.host if request.client else "unknown"
        ),
    )

    # Get current user if authenticated
    user = get_current_user(request)

    return {
        "name": "Telnyx Remote MCP Server",
        "version": __version__,
        "protocol_version": PROTOCOL_VERSION,
        "status": "healthy",
        "endpoints": {
            "mcp": "/mcp",
            "health": "/health",
        },
        "tools_available": len(telnyx_mcp_server.tools),
        "authenticated": user is not None,
        "user": user.to_dict() if user else None,
    }


@app.post("/")
async def root_post(request: Request):
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
    return await mcp_endpoint(request)


# OAuth endpoints ONLY for local development / Claude Desktop
if not config.is_app_service:  # Only enable OAuth in local dev

    @app.get("/.well-known/openid-configuration")
    async def openid_configuration(request: Request):
        """OpenID Connect discovery endpoint - LOCAL DEV ONLY."""
        base_url = get_base_url_from_request(request)
        return {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            "userinfo_endpoint": f"{base_url}/userinfo",
            "jwks_uri": f"{base_url}/.well-known/jwks.json",
            "response_types_supported": ["code", "token", "id_token"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile", "email"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
            ],
            "claims_supported": ["sub", "name", "email", "preferred_username"],
            "code_challenge_methods_supported": ["S256"],
        }

    # TODO: Add /authorize, /token, /callback endpoints for local OAuth flow


# OAuth proxy endpoints for Azure AD - handle OAuth flow for Claude
@app.get("/authorize")
async def authorize_proxy(request: Request):
    """Proxy authorization endpoint that redirects to Azure AD with our client_id."""
    if not config.is_app_service:
        # Local OAuth flow - not implemented yet
        return JSONResponse(
            status_code=501,
            content={
                "error": "not_implemented",
                "error_description": "Local OAuth not implemented",
            },
        )

    # In Azure App Service, redirect to Azure AD with our client_id
    tenant_id = config.tenant_id or "common"
    client_id = config.client_id or os.getenv("AZURE_CLIENT_ID")

    if not client_id:
        return JSONResponse(
            status_code=500,
            content={
                "error": "server_error",
                "error_description": "OAuth client_id not configured",
            },
        )

    # Get query parameters from Claude
    params = dict(request.query_params)

    # Ensure our client_id is used
    params["client_id"] = client_id

    # Build Azure AD authorization URL
    azure_auth_url = (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
    )
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    redirect_url = f"{azure_auth_url}?{query_string}"

    logger.info(f"Redirecting to Azure AD: {redirect_url}")

    # Redirect to Azure AD
    return Response(status_code=302, headers={"Location": redirect_url})


@app.post("/token")
async def token_proxy(request: Request):
    """Proxy token endpoint that forwards to Azure AD."""
    if not config.is_app_service:
        # Local OAuth flow - not implemented yet
        return JSONResponse(
            status_code=501,
            content={
                "error": "not_implemented",
                "error_description": "Local OAuth not implemented",
            },
        )

    # In Azure App Service, forward to Azure AD token endpoint
    tenant_id = config.tenant_id or "common"
    client_id = config.client_id or os.getenv("AZURE_CLIENT_ID")

    if not client_id:
        return JSONResponse(
            status_code=500,
            content={
                "error": "server_error",
                "error_description": "OAuth client_id not configured",
            },
        )

    # Get form data from Claude
    form_data = await request.form()
    data = dict(form_data)

    # Ensure our client_id is used
    data["client_id"] = client_id

    # Log the token exchange attempt for debugging
    logger.info(
        f"Forwarding token request to Azure AD",
        client_id=client_id,
        tenant_id=tenant_id,
        has_code="code" in data,
        has_code_verifier="code_verifier" in data,
        grant_type=data.get("grant_type"),
    )

    # Forward to Azure AD token endpoint
    import httpx

    async with httpx.AsyncClient() as client:
        azure_token_url = (
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        )
        response = await client.post(azure_token_url, data=data)

        # Log the response for debugging
        if response.status_code != 200:
            logger.error(
                f"Azure AD token exchange failed",
                status_code=response.status_code,
                error_response=response.text,
            )

        # Return Azure AD response to Claude
        return Response(
            content=response.text,
            status_code=response.status_code,
            headers={"Content-Type": "application/json"},
        )


# MCP OAuth metadata endpoint - Claude looks for this
@app.get("/.well-known/mcp-oauth-metadata")
async def mcp_oauth_metadata(request: Request):
    """MCP OAuth metadata for Claude to discover our OAuth configuration."""
    base_url = get_base_url_from_request(request)

    # Debug logging
    logger.info(
        "MCP OAuth metadata requested",
        is_app_service=config.is_app_service,
        client_id=config.client_id,
        tenant_id=config.tenant_id,
    )

    if config.is_app_service:
        # Azure AD configuration - include all necessary fields for Claude
        tenant_id = config.tenant_id or "common"
        client_id = config.client_id or os.getenv("AZURE_CLIENT_ID")

        if not client_id:
            logger.error("No client_id available for Azure AD configuration")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "server_error",
                    "error_description": "OAuth client_id not configured",
                },
            )

        # Return metadata that points to our proxy endpoints
        # We'll handle the Azure AD client_id injection in our /authorize endpoint
        return {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            # Don't include client_id here - Claude should not send one
            "scopes_supported": [
                "openid",
                "profile",
                "email",
                "offline_access",
            ],
            "grant_types_supported": ["authorization_code"],
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        }
    else:
        # Local OAuth configuration
        return {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            "registration_endpoint": f"{base_url}/register",
            "scopes_supported": [
                "openid",
                "profile",
                "email",
                "mcp:read",
                "mcp:write",
                "mcp:execute",
            ],
            "grant_types_supported": ["authorization_code"],
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        }


# OAuth discovery endpoints for both local dev and Azure Easy Auth
@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata(request: Request):
    """OAuth 2.0 Protected Resource Metadata (RFC9728)."""
    logger.info("OAuth protected resource metadata endpoint called")
    base_url = get_base_url_from_request(request)

    # Always point to our own authorization server metadata
    # Claude will fetch this to discover the actual OAuth endpoints
    authorization_servers = [
        f"{base_url}/.well-known/oauth-authorization-server"
    ]

    return {
        "resource": base_url,
        "authorization_servers": authorization_servers,
        "bearer_methods_supported": ["header"],
        "resource_signing_alg_values_supported": ["RS256"],
        # Add client configuration for Azure AD
        "client_id": config.client_id if config.is_app_service else None,
    }


@app.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server_metadata(request: Request):
    """OAuth 2.0 Authorization Server Metadata (RFC8414)."""
    base_url = get_base_url_from_request(request)

    # Debug logging
    logger.info(
        "OAuth authorization server metadata requested",
        is_app_service=config.is_app_service,
        client_id=config.client_id,
        tenant_id=config.tenant_id,
        client_id_from_env=os.getenv("AZURE_CLIENT_ID"),
    )

    if config.is_app_service:
        # Azure Easy Auth - return Azure's OAuth endpoints WITH client_id
        tenant_id = config.tenant_id or "common"
        return {
            "issuer": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            # Add a registration endpoint that returns pre-configured client info
            "registration_endpoint": f"{base_url}/register",
            "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
            "jwks_uri": f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
            # CRITICAL: Include client_id so Claude knows what to use
            "client_id": config.client_id,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": [
                "openid",
                "profile",
                "email",
                "offline_access",
            ],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "none",
            ],
            "claims_supported": [
                "sub",
                "name",
                "email",
                "preferred_username",
                "aud",
                "iss",
                "iat",
                "exp",
            ],
        }
    else:
        # Local development - return our server's OAuth endpoints
        return {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            "registration_endpoint": f"{base_url}/register",
            "userinfo_endpoint": f"{base_url}/userinfo",
            "jwks_uri": f"{base_url}/.well-known/jwks.json",
            "response_types_supported": ["code", "token"],
            "grant_types_supported": ["authorization_code", "implicit"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["HS256"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": [
                "openid",
                "profile",
                "email",
                "mcp:read",
                "mcp:write",
                "mcp:execute",
            ],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
                "none",
            ],
            "claims_supported": ["sub", "name", "email", "preferred_username"],
        }


# OAuth endpoints ONLY for local development / Claude Desktop
if not config.is_app_service:  # Only enable OAuth in local dev

    @app.post("/register", status_code=201)
    async def register(request: Request):
        """OAuth 2.0 Dynamic Client Registration (RFC 7591) - LOCAL DEV ONLY."""
        try:
            client_data = await request.json()
        except:
            return Response(
                content=json.dumps(
                    {
                        "error": "invalid_request",
                        "error_description": "Invalid JSON in request body",
                    }
                ),
                status_code=400,
                media_type="application/json",
            )

        # Generate a client_id for the client
        import secrets

        client_id = f"mcp_{secrets.token_urlsafe(16)}"

        logger.info(
            f"Registered new OAuth client: {client_id}, name={client_data.get('client_name')}, redirect_uris={client_data.get('redirect_uris')}"
        )

        return {
            "client_id": client_id,
            "client_secret": "",  # Public client
            "redirect_uris": client_data.get("redirect_uris", []),
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "application_type": "web",
            "client_name": client_data.get("client_name"),
            "client_uri": client_data.get("client_uri"),
            "scope": client_data.get("scope", "openid profile email"),
        }


# OAuth proxy endpoints for Azure AD when running in App Service
if config.is_app_service:
    from urllib.parse import urlencode

    import httpx

    @app.get("/authorize")
    async def authorize_proxy(request: Request):
        """Proxy authorization endpoint that redirects to Azure AD with our client_id."""
        logger.info(
            "OAuth authorize proxy called",
            query_params=dict(request.query_params),
        )

        # Get all query parameters from the request
        params = dict(request.query_params)

        # Ensure our client_id is used
        params["client_id"] = config.client_id

        # Construct Azure AD authorization URL
        tenant_id = config.tenant_id or "common"
        azure_auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"

        # Redirect to Azure AD with all parameters
        redirect_url = f"{azure_auth_url}?{urlencode(params)}"
        logger.info("Redirecting to Azure AD", redirect_url=redirect_url)

        return Response(status_code=302, headers={"Location": redirect_url})

    @app.post("/token")
    async def token_proxy(request: Request):
        """Proxy token endpoint that forwards to Azure AD with managed identity authentication."""
        logger.info("OAuth token proxy called")

        # Get the request body
        body = await request.body()
        content_type = request.headers.get("content-type", "")

        # Parse the form data
        if "application/x-www-form-urlencoded" in content_type:
            from urllib.parse import parse_qs, urlencode

            form_data = parse_qs(body.decode("utf-8"))
            # Convert from parse_qs format (lists) to simple dict
            form_dict = {k: v[0] if v else "" for k, v in form_data.items()}

            # Ensure client_id is set
            if not form_dict.get("client_id"):
                form_dict["client_id"] = config.client_id

            logger.info(
                "Token request received",
                grant_type=form_dict.get("grant_type"),
                has_code=bool(form_dict.get("code")),
                has_code_verifier=bool(form_dict.get("code_verifier")),
                client_id=form_dict.get("client_id"),
                redirect_uri=form_dict.get("redirect_uri"),
            )
        else:
            logger.error(f"Unexpected content type: {content_type}")
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_request",
                    "error_description": "Content-Type must be application/x-www-form-urlencoded",
                },
            )

        # Check if we should use managed identity with FIC for authentication
        override_client_id = os.getenv(
            "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID"
        )
        use_jwt_assertion = (
            os.getenv("USE_JWT_ASSERTION", "true").lower() == "true"
        )

        if override_client_id:
            if use_jwt_assertion:
                # Approach 1: Use managed identity to create a JWT assertion for private_key_jwt authentication
                from .auth.azure.managed_identity import create_jwt_assertion

                try:
                    logger.info(
                        "Using managed identity for private_key_jwt authentication",
                        managed_identity_client_id=override_client_id,
                        app_client_id=config.client_id,
                    )

                    # Create JWT assertion
                    jwt_assertion = await create_jwt_assertion(
                        managed_identity_client_id=override_client_id,
                        client_id=config.client_id,
                        audience=f"https://login.microsoftonline.com/{config.tenant_id}/oauth2/v2.0/token",
                    )

                    # Add JWT assertion to the form data
                    form_dict["client_assertion_type"] = (
                        "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
                    )
                    form_dict["client_assertion"] = jwt_assertion

                    # Remove code_verifier if present when using client assertion
                    if "code_verifier" in form_dict:
                        del form_dict["code_verifier"]

                    logger.info("Added JWT assertion to token request")

                except Exception as e:
                    logger.error(
                        f"Failed to create JWT assertion: {e}", exc_info=True
                    )
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": "server_error",
                            "error_description": f"Failed to create client assertion: {str(e)}",
                        },
                    )
            else:
                # Approach 2: Use managed identity client ID as client secret
                logger.info(
                    "Using managed identity client ID as client secret",
                    managed_identity_client_id=override_client_id,
                    app_client_id=config.client_id,
                )

                # Set the managed identity client ID as the client secret
                form_dict["client_secret"] = override_client_id

                # Remove code_verifier if present when using client secret
                if "code_verifier" in form_dict:
                    del form_dict["code_verifier"]

                logger.info(
                    "Added managed identity client ID as client secret to token request"
                )

        # Reconstruct body with all parameters
        body = urlencode(form_dict).encode("utf-8")

        # Construct Azure AD token URL
        tenant_id = config.tenant_id or "common"
        azure_token_url = (
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        )

        # Forward the request to Azure AD
        async with httpx.AsyncClient() as client:
            try:
                # Make the request to Azure AD
                response = await client.post(
                    azure_token_url,
                    data=body,
                    headers={
                        "Content-Type": content_type,
                        # Azure AD might need these headers
                        "Origin": request.headers.get("origin", ""),
                        "User-Agent": request.headers.get("user-agent", ""),
                    },
                )

                logger.info(
                    "Azure AD token response",
                    status_code=response.status_code,
                    headers=dict(response.headers),
                )

                # Log error details if the request failed
                if response.status_code != 200:
                    error_text = response.text
                    logger.error(
                        "Azure AD token error",
                        status_code=response.status_code,
                        error_response=error_text,
                    )

                # Return Azure AD's response
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers={
                        "Content-Type": response.headers.get(
                            "content-type", "application/json"
                        ),
                        "Cache-Control": "no-store",
                        "Pragma": "no-cache",
                    },
                )

            except Exception as e:
                logger.error(
                    f"Error forwarding token request: {e}", exc_info=True
                )
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": "server_error",
                        "error_description": "Failed to forward token request",
                    },
                )

    @app.post("/register", status_code=201)
    async def register_proxy(request: Request):
        """Registration endpoint for Azure AD - returns pre-configured client information."""
        logger.info("OAuth registration endpoint called (Azure AD mode)")

        # Azure AD doesn't support dynamic client registration
        # Instead, we return our pre-configured client information
        # This allows Claude to discover our client_id without having to pre-configure it

        try:
            client_data = await request.json()
        except:
            client_data = {}

        logger.info(
            "Registration request received",
            client_name=client_data.get("client_name"),
            redirect_uris=client_data.get("redirect_uris"),
        )

        # Get the managed identity client ID that we use for authentication
        override_client_id = os.getenv(
            "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID", ""
        )
        use_jwt_assertion = (
            os.getenv("USE_JWT_ASSERTION", "true").lower() == "true"
        )

        # Return our pre-configured Azure AD app registration details
        response_data = {
            "client_id": config.client_id,
            "redirect_uris": client_data.get("redirect_uris", []),
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "application_type": "web",
            "client_name": client_data.get("client_name", "Telnyx MCP Server"),
            "client_uri": client_data.get("client_uri"),
            "scope": "openid profile email offline_access",
            "code_challenge_methods_supported": ["S256"],
        }

        if use_jwt_assertion:
            # Using JWT assertion (private_key_jwt)
            response_data["client_secret"] = (
                ""  # No secret needed for JWT assertion
            )
            response_data["token_endpoint_auth_method"] = "private_key_jwt"
            response_data["token_endpoint_auth_methods_supported"] = [
                "private_key_jwt",
                "none",
            ]
        else:
            # Using managed identity client ID as secret
            response_data["client_secret"] = (
                override_client_id  # MI client ID as secret
            )
            response_data["token_endpoint_auth_method"] = "client_secret_post"
            response_data["token_endpoint_auth_methods_supported"] = [
                "client_secret_post",
                "none",
            ]

        return response_data


@app.get("/oauth/callback/debug")
async def oauth_callback_debug(request: Request):
    """Debug endpoint to test OAuth callbacks and exchange authorization codes for tokens."""
    logger.info("OAuth callback debug endpoint called")

    # Get query parameters
    code = request.query_params.get("code")
    state = request.query_params.get("state", "")
    session_state = request.query_params.get("session_state", "")
    error = request.query_params.get("error")
    error_description = request.query_params.get("error_description", "")

    if error:
        return JSONResponse(
            content={
                "error": error,
                "error_description": error_description,
                "message": "OAuth authorization failed",
            },
            status_code=400,
        )

    if not code:
        return JSONResponse(
            content={
                "error": "missing_code",
                "message": "No authorization code provided",
            },
            status_code=400,
        )

    # Log the callback details
    logger.info(
        "OAuth callback received",
        code_length=len(code),
        has_state=bool(state),
        session_state=session_state,
    )

    # Prepare token exchange request
    token_request = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": str(request.url).split("?")[
            0
        ],  # Current URL without query params
        "client_id": config.client_id,
    }

    # Add code_verifier if we're using PKCE (you would need to store this from the authorization request)
    # For now, we'll just note it's missing
    code_verifier = request.query_params.get("code_verifier", "")
    if code_verifier:
        token_request["code_verifier"] = code_verifier

    # Make request to token endpoint
    token_url = f"{get_base_url_from_request(request)}/token"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                token_url,
                data=token_request,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            logger.info(
                "Token exchange response",
                status_code=response.status_code,
                has_access_token="access_token" in response.json()
                if response.status_code == 200
                else False,
            )

            if response.status_code == 200:
                tokens = response.json()
                return JSONResponse(
                    content={
                        "message": "Token exchange successful!",
                        "tokens": {
                            "access_token": tokens.get("access_token", "")[:50]
                            + "..."
                            if tokens.get("access_token")
                            else None,
                            "token_type": tokens.get("token_type"),
                            "expires_in": tokens.get("expires_in"),
                            "scope": tokens.get("scope"),
                            "id_token": tokens.get("id_token", "")[:50] + "..."
                            if tokens.get("id_token")
                            else None,
                            "refresh_token": tokens.get("refresh_token", "")[
                                :50
                            ]
                            + "..."
                            if tokens.get("refresh_token")
                            else None,
                        },
                        "debug_info": {
                            "redirect_uri_used": token_request["redirect_uri"],
                            "client_id": config.client_id,
                            "use_jwt_assertion": os.getenv(
                                "USE_JWT_ASSERTION", "true"
                            ),
                            "has_override_client_id": bool(
                                os.getenv(
                                    "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID"
                                )
                            ),
                        },
                    }
                )
            else:
                error_response = response.json()
                return JSONResponse(
                    content={
                        "message": "Token exchange failed",
                        "error": error_response,
                        "debug_info": {
                            "status_code": response.status_code,
                            "token_request": {
                                k: v
                                for k, v in token_request.items()
                                if k != "code"
                            },
                            "use_jwt_assertion": os.getenv(
                                "USE_JWT_ASSERTION", "true"
                            ),
                        },
                    },
                    status_code=response.status_code,
                )

        except Exception as e:
            logger.error(f"Error during token exchange: {e}", exc_info=True)
            return JSONResponse(
                content={
                    "error": "token_exchange_error",
                    "message": f"Failed to exchange authorization code: {str(e)}",
                    "debug_info": {
                        "redirect_uri_used": token_request["redirect_uri"],
                        "client_id": config.client_id,
                    },
                },
                status_code=500,
            )


@app.get("/health")
async def health_check():
    """Health check endpoint with readiness probe functionality."""
    logger.debug("Health check requested")
    health_data = {
        "status": "healthy",
        "service": "telnyx-mcp-server",
        "version": __version__,
        "git_commit": GIT_INFO["commit"],
        "git_branch": GIT_INFO["branch"],
        "build_time": GIT_INFO["build_time"],
        "build_number": GIT_INFO["build_number"],
        "protocol_version": PROTOCOL_VERSION,
        "timestamp": time.time(),
    }

    # Check Easy Auth configuration
    import os

    health_data["auth"] = {
        "easy_auth_available": config.is_easy_auth_available,
        "environment": config.environment,
        "auth_enforced": config.auth_enforce,
        "client_id": config.client_id,
        "tenant_id": config.tenant_id,
        "debug": {
            "auth_enabled_field": config.auth_enabled,
            "is_app_service_field": config.is_app_service,
            "website_auth_enabled_env": os.getenv(
                "WEBSITE_AUTH_ENABLED", "NOT_SET"
            ),
            "website_instance_id_env": os.getenv(
                "WEBSITE_INSTANCE_ID", "NOT_SET"
            ),
            "website_instance_id_bool": bool(os.getenv("WEBSITE_INSTANCE_ID")),
            "logic_check": f"is_app_service={config.is_app_service} AND auth_enabled={config.auth_enabled} = {config.is_app_service and config.auth_enabled}",
            "azure_client_id_env": os.getenv("AZURE_CLIENT_ID", "NOT_SET"),
            "azure_tenant_id_env": os.getenv("AZURE_TENANT_ID", "NOT_SET"),
        },
    }

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
        for component in [health_data.get("mcp_tools", {})]
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


# MCP Protocol Endpoints


@app.get("/mcp")
async def mcp_metadata():
    """MCP metadata discovery endpoint."""
    return {
        "mcp_version": "1.0",
        "protocol_version": PROTOCOL_VERSION,
        "server_name": "Telnyx MCP Server",
        "server_version": __version__,
        "capabilities": {"tools": True, "resources": True, "logging": True},
        "auth_required": True,
        "auth_type": "oauth2"
        if not config.is_app_service
        else "azure_easy_auth",
    }


@app.options("/mcp")
async def mcp_options():
    """Handle CORS preflight for /mcp endpoint."""
    return Response(status_code=200)


@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    user: Optional[AzureClientPrincipal] = Depends(get_current_user),
):
    """MCP endpoint implementing Streamable HTTP transport.

    Authentication is handled by Azure Easy Auth middleware.
    """
    # Get base URL first
    base_url = get_base_url_from_request(request)

    # LOG EVERYTHING - FULL REQUEST DETAILS
    logger.debug(
        "MCP POST /mcp REQUEST RECEIVED",
        url=str(request.url),
        method=request.method,
        client=str(request.client),
        headers=dict(request.headers),
    )

    # Parse the request body
    message = None
    try:
        body = await request.body()
        body_str = body.decode("utf-8") if body else "None"
        logger.debug("REQUEST BODY", body=body_str)
        message = json.loads(body)

        # Check if authentication is required
        requires_auth = True
        method = ""
        if isinstance(message, dict):
            method = message.get("method", "")

        # If auth is required but no user, return 401
        if requires_auth and not user:
            headers = {
                "WWW-Authenticate": 'Bearer realm="telnyx-mcp"',
                "Cache-Control": "no-store",
            }

            logger.debug(
                "SENDING 401 UNAUTHORIZED RESPONSE",
                method=method,
                response_headers=headers,
                response_body="(empty)",
                status_code=401,
            )

            return Response(
                content="",  # Empty body - critical for MCP clients
                status_code=401,
                headers=headers,
            )

        # Comprehensive logging
        logger.info(
            "MCP POST endpoint called",
            url=str(request.url),
            method=request.method,
            user_email=user.email if user else None,
            user_id=user.user_id if user else None,
            accept=request.headers.get("accept", "None"),
            content_type=request.headers.get("content-type", "None"),
            client_ip=request.headers.get(
                "x-client-ip",
                request.client.host if request.client else "unknown",
            ),
            session_id=request.headers.get("mcp-session-id", "None"),
            mcp_method=method,
        )

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
                user_email=user.email if user else "anonymous",
            )
        else:
            logger.info(
                "MCP request",
                method=message.get("method"),
                user_email=user.email if user else "anonymous",
            )

    # Process the message(s)
    response = await telnyx_mcp_server.process_message(
        message, session_id, base_url
    )

    # Handle response format based on message type and Accept header
    if response is None:
        # Notification - return 202 Accepted with no body
        return Response(status_code=202)

    # LOG THE RESPONSE WE'RE ABOUT TO SEND
    logger.debug(
        "MCP RESPONSE TO BE SENT",
        response_data=response if response else "None (202 already sent)",
    )

    # Return JSON response
    headers = {}
    if session_id:
        headers["mcp-session-id"] = session_id

    # Log the response being sent
    logger.debug(
        "MCP response sent",
        session_id=session_id,
        response_size=len(json.dumps(response)) if response else 0,
        has_result="result" in (response or {}),
        has_error="error" in (response or {}),
        is_batch=isinstance(response, list),
        batch_size=len(response) if isinstance(response, list) else 1,
        user_email=user.email if user else "anonymous",
    )

    return Response(
        content=json.dumps(response),
        media_type="application/json",
        headers=headers,
    )


# MUST BE LAST - Catch all unhandled routes
@app.api_route(
    "/{path:path}",
    methods=[
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "OPTIONS",
        "HEAD",
        "PATCH",
        "TRACE",
    ],
)
async def catch_all(request: Request, path: str):
    """Catch all route to log any unhandled requests."""
    logger.info(
        f"\nCATCH ALL ROUTE HIT:\n"
        f"Path: /{path}\n"
        f"Method: {request.method}\n"
        f"Headers: {dict(request.headers)}\n"
    )
    return JSONResponse(
        status_code=404, content={"detail": f"Path '/{path}' not found"}
    )


def main():
    """Main entry point for the remote server."""
    import h11
    import uvicorn
    from uvicorn.protocols.http.h11_impl import H11Protocol

    # Monkey patch H11Protocol to log invalid requests
    original_handle_events = H11Protocol.handle_events

    def patched_handle_events(self):
        try:
            return original_handle_events(self)
        except h11.RemoteProtocolError as e:
            logger.error(
                f"\n{'=' * 80}\n"
                f"INVALID HTTP REQUEST DETAILS\n"
                f"{'=' * 80}\n"
                f"Client: {self.client}\n"
                f"Error: {e}\n"
                f"Raw data received: {self.conn.trailing_data[:1000]}\n"
                f"{'=' * 80}\n"
            )
            raise

    H11Protocol.handle_events = patched_handle_events

    uvicorn.run(
        "telnyx_mcp_server.remote.server:app",
        host="0.0.0.0",
        port=8000,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
