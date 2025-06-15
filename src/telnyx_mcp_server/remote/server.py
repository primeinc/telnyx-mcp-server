"""Remote MCP server implementation for Telnyx using FastAPI."""

from fastapi import FastAPI, HTTPException, Request, Depends, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse
from sse_starlette.sse import EventSourceResponse
from typing import Any, Dict, Optional, List, Union
import logging
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import json
import asyncio
from datetime import datetime
import httpx

# Import authentication
from .auth import (
    AuthService, get_current_user, optional_auth,
    AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_REDIRECT_URI, AZURE_TENANT_ID,
    AZURE_TOKEN_URL
)

# Import existing Telnyx MCP components
from ..mcp import mcp
from ..config import settings
from ..utils.logger import get_logger

# Load environment variables
load_dotenv()

# Configure logging
logger = get_logger(__name__)

# Version information
__version__ = "0.3.0"
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
            from ..tools import (
                assistants,
                call_control,
                cloud_storage,
                connections,
                embeddings,
                messaging,
                messaging_profiles,
                phone_numbers,
                secrets,
                webhooks
            )
            
            # Get the list of tools from MCP
            tools_list = await mcp.list_tools()
            
            # Convert to dict format
            self.tools = {
                tool.name: {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema
                }
                for tool in tools_list
            }
            
            self._tools_initialized = True
            logger.info(f"Initialized {len(self.tools)} Telnyx tools")
            
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}", exc_info=True)
            self._tools_initialized = False
    
    def _extract_parameters_from_docstring(self, docstring: str) -> Dict[str, Any]:
        """Extract parameter definitions from tool docstring."""
        if not docstring:
            return {"type": "object", "properties": {}, "required": []}
        
        lines = docstring.split('\n')
        in_args = False
        properties = {}
        required = []
        
        for line in lines:
            line = line.strip()
            
            # Start of Args section
            if line.startswith("Args:"):
                in_args = True
                continue
            
            # End of Args section
            if in_args and (line.startswith("Returns:") or line == "" and not lines):
                break
            
            # Parse parameter lines
            if in_args and line:
                # Match parameter definition pattern
                if ":" in line:
                    parts = line.split(":", 1)
                    param_name = parts[0].strip()
                    description = parts[1].strip() if len(parts) > 1 else ""
                    
                    # Extract type and required status from description
                    is_required = "Required." in description or "required." in description
                    is_optional = "Optional" in description or "optional" in description
                    
                    # Determine type from description
                    param_type = "string"  # default
                    if "boolean" in description.lower() or "bool" in description.lower():
                        param_type = "boolean"
                    elif "integer" in description.lower() or "int" in description.lower():
                        param_type = "integer"
                    elif "number" in description.lower() or "float" in description.lower():
                        param_type = "number"
                    elif "array" in description.lower() or "list" in description.lower():
                        param_type = "array"
                    elif "object" in description.lower() or "dict" in description.lower():
                        param_type = "object"
                    
                    # Clean up parameter name (remove trailing underscore)
                    clean_name = param_name.rstrip('_')
                    
                    properties[clean_name] = {
                        "type": param_type,
                        "description": description
                    }
                    
                    if is_required and not is_optional:
                        required.append(clean_name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required
        }
    
    def _transform_tool_schema(self, tool: Dict[str, Any]) -> Dict[str, Any]:
        """Transform tool schema to flatten nested request objects."""
        # Create a copy of the tool
        transformed = tool.copy()
        
        # Check if this tool has the nested request pattern
        input_schema = tool.get("inputSchema", {})
        properties = input_schema.get("properties", {})
        
        if len(properties) == 1 and "request" in properties:
            # This is a nested schema - extract parameters from docstring
            docstring = tool.get("description", "")
            flattened_schema = self._extract_parameters_from_docstring(docstring)
            
            # Override with known schemas for common tools
            if tool["name"] == "send_message":
                flattened_schema = {
                    "type": "object",
                    "properties": {
                        "from": {
                            "type": "string",
                            "description": "Sending address (phone number, alphanumeric sender ID, or short code)"
                        },
                        "to": {
                            "type": "string",
                            "description": "Receiving address(es)"
                        },
                        "text": {
                            "type": "string",
                            "description": "Message text"
                        },
                        "messaging_profile_id": {
                            "type": "string",
                            "description": "Optional. Messaging profile ID"
                        },
                        "subject": {
                            "type": "string",
                            "description": "Optional. Message subject"
                        },
                        "media_urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional. List of media URLs"
                        },
                        "webhook_url": {
                            "type": "string",
                            "description": "Optional. Webhook URL"
                        },
                        "type": {
                            "type": "string",
                            "enum": ["SMS", "MMS"],
                            "description": "Optional. The protocol for sending the message"
                        }
                    },
                    "required": ["from", "to", "text"]
                }
            elif tool["name"] == "get_message":
                flattened_schema = {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "The ID of the message to retrieve"
                        }
                    },
                    "required": ["message_id"]
                }
            elif tool["name"] == "list_phone_numbers":
                flattened_schema = {
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Page number",
                            "default": 1
                        },
                        "page_size": {
                            "type": "integer",
                            "description": "Page size",
                            "default": 20
                        },
                        "filter_phone_number": {
                            "type": "string",
                            "description": "Filter by phone number"
                        },
                        "filter_status": {
                            "type": "string",
                            "description": "Filter by status"
                        },
                        "filter_voice_enabled": {
                            "type": "boolean",
                            "description": "Filter by voice enabled"
                        }
                    },
                    "required": []
                }
            elif tool["name"] == "get_assistant":
                flattened_schema = {
                    "type": "object",
                    "properties": {
                        "assistant_id": {
                            "type": "string",
                            "description": "Assistant ID"
                        }
                    },
                    "required": ["assistant_id"]
                }
            elif tool["name"] == "start_assistant_call":
                flattened_schema = {
                    "type": "object",
                    "properties": {
                        "assistant_id": {
                            "type": "string",
                            "description": "ID of the assistant to use for the call"
                        },
                        "to": {
                            "type": "string",
                            "description": "Destination phone number to call"
                        },
                        "from": {
                            "type": "string",
                            "description": "Source phone number to call from (must be a number on your Telnyx account)"
                        }
                    },
                    "required": ["assistant_id", "to", "from"]
                }
            
            transformed["inputSchema"] = flattened_schema
        
        return transformed
    
    async def handle_initialize(self, request_id: Any, params: Dict[str, Any], session_id: str = None) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        # Get client's requested protocol version
        client_version = params.get("protocolVersion", PROTOCOL_VERSION)
        
        # Version negotiation - we support 2025-03-26
        response_version = PROTOCOL_VERSION if client_version == PROTOCOL_VERSION else client_version
        
        # Mark session as initialized
        if session_id:
            self._initialized_sessions.add(session_id)
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": response_version,
                "capabilities": {
                    "tools": {
                        "listChanged": True
                    },
                    "resources": {
                        "subscribe": True,
                        "listChanged": True
                    },
                    "logging": {}
                },
                "serverInfo": {
                    "name": "Telnyx MCP Server",
                    "version": __version__
                }
            }
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
            "result": {
                "tools": transformed_tools
            }
        }
    
    async def handle_tools_call(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
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
                    "message": f"Tool '{tool_name}' not found"
                }
            }
        
        try:
            # Transform arguments if needed
            tool_schema = self.tools[tool_name].get("inputSchema", {})
            properties = tool_schema.get("properties", {})
            
            # If the tool expects a nested request object, wrap the arguments
            if len(properties) == 1 and "request" in properties:
                # This tool expects arguments wrapped in a request object
                transformed_args = {"request": arguments}
            else:
                # Tool has been flattened or uses direct parameters
                transformed_args = arguments
            
            # Call the tool through the existing MCP instance
            result = await mcp.call_tool(tool_name, transformed_args)
            
            # Format the result according to MCP protocol
            if hasattr(result, 'text'):
                content = [{"type": "text", "text": result.text}]
            elif hasattr(result, 'content'):
                content = result.content
            else:
                content = [{"type": "text", "text": str(result)}]
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": content
                }
            }
            
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": str(e)
                }
            }
    
    async def handle_resources_list(self, request_id: Any) -> Dict[str, Any]:
        """Handle resources/list request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "resources": list(self.resources.values())
            }
        }
    
    async def handle_resources_read(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri")
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32602,
                "message": f"Resource '{uri}' not found"
            }
        }
    
    async def process_message(self, message: Union[Dict, List], session_id: str = None) -> Union[Dict, List]:
        """Process a JSON-RPC message or batch."""
        if isinstance(message, list):
            # Batch request
            responses = []
            for msg in message:
                if msg.get("jsonrpc") == "2.0":
                    response = await self._process_single_message(msg, session_id)
                    if response:  # Only include responses for requests, not notifications
                        responses.append(response)
            return responses if responses else None
        else:
            # Single request
            return await self._process_single_message(message, session_id)
    
    async def _process_single_message(self, message: Dict[str, Any], session_id: str = None) -> Optional[Dict[str, Any]]:
        """Process a single JSON-RPC message."""
        if message.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32600,
                    "message": "Invalid Request - must be JSON-RPC 2.0"
                }
            }
        
        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id")
        
        # Notifications don't have id and don't get responses
        is_notification = msg_id is None
        
        try:
            # Route to appropriate handler
            if method == "initialize":
                response = await self.handle_initialize(msg_id, params, session_id)
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
                        "message": f"Method not found: {method}"
                    }
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
                        "data": str(e)
                    }
                }
            return None


# Initialize MCP server
telnyx_mcp_server = TelnyxMCPServer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Telnyx Remote MCP Server")
    await telnyx_mcp_server.initialize_tools()
    yield
    logger.info("Shutting down Telnyx Remote MCP Server")


# Create FastAPI app
app = FastAPI(
    title="Telnyx Remote MCP Server",
    description="Model Context Protocol server for Telnyx API integration",
    version=__version__,
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint with server information."""
    base_url = os.getenv("BASE_URL", "https://app-web-3ky2b33hy2dpm.azurewebsites.net")
    return {
        "name": "Telnyx Remote MCP Server",
        "version": __version__,
        "protocol_version": PROTOCOL_VERSION,
        "status": "healthy",
        "endpoints": {
            "mcp": "/mcp",
            "oauth_authorization_server": "/.well-known/oauth-authorization-server",
            "health": "/health"
        },
        "tools_available": len(telnyx_mcp_server.tools)
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "telnyx-mcp-server",
        "version": __version__,
        "protocol_version": PROTOCOL_VERSION
    }


@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata(request: Request):
    """OAuth 2.0 Protected Resource Metadata (RFC9728)."""
    # Get base URL from request, handling proxy headers
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    
    if forwarded_proto and forwarded_host:
        # Running behind a proxy (like Azure App Service)
        base_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        # Direct access
        base_url = str(request.base_url).rstrip('/')
    
    return {
        "resource": base_url,
        "authorization_servers": [base_url],
        "scopes_supported": ["openid", "profile", "email"],
        "bearer_methods_supported": ["header"],
        "resource_signing_alg_values_supported": ["RS256"],
        "resource_documentation": f"{base_url}/docs",
        "resource_policy_uri": f"{base_url}/privacy",
        "resource_tos_uri": f"{base_url}/terms"
    }


@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request):
    """OAuth 2.0 Authorization Server Metadata (RFC8414)."""
    # Get base URL from request, handling proxy headers
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    
    if forwarded_proto and forwarded_host:
        # Running behind a proxy (like Azure App Service)
        base_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        # Direct access
        base_url = str(request.base_url).rstrip('/')
    
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "registration_endpoint": f"{base_url}/register",
        "jwks_uri": f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "profile", "email", "User.Read"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256"],
        "claims_supported": ["sub", "email", "name", "exp", "iat"],
        "service_documentation": f"{base_url}/docs"
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
    code_challenge_method: Optional[str] = "S256"
):
    """OAuth 2.0 Authorization endpoint - redirects to Azure AD."""
    # Validate client_id matches our Azure app
    if client_id != AZURE_CLIENT_ID:
        return Response(
            content=f"Invalid client_id. Use {AZURE_CLIENT_ID}",
            status_code=400
        )
    
    # Get Azure AD authorization URL
    auth_url = AuthService.get_authorization_url(state)
    
    # Redirect to Azure AD
    return RedirectResponse(url=auth_url, status_code=302)


@app.post("/token")
async def token(request: Request):
    """OAuth 2.0 Token endpoint - exchanges code for JWT token."""
    form_data = await request.form()
    code = form_data.get("code")
    
    if not code:
        return Response(
            content=json.dumps({
                "error": "invalid_request",
                "error_description": "Missing authorization code"
            }),
            status_code=400,
            media_type="application/json"
        )
    
    try:
        # Exchange code for Azure AD token
        token_data = await AuthService.exchange_code_for_token(code)
        azure_access_token = token_data.get("access_token")
        
        # Get user info from Azure
        user_info = await AuthService.get_user_info(azure_access_token)
        
        # Create our JWT token
        jwt_token = AuthService.create_jwt_token(user_info)
        
        return {
            "access_token": jwt_token,
            "token_type": "Bearer",
            "expires_in": 86400,  # 24 hours
            "scope": "openid profile email"
        }
        
    except Exception as e:
        logger.error(f"Token exchange error: {e}")
        return Response(
            content=json.dumps({
                "error": "invalid_grant",
                "error_description": str(e)
            }),
            status_code=400,
            media_type="application/json"
        )


@app.get("/auth/callback")
async def oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None
):
    """OAuth 2.0 callback endpoint - matches Azure AD redirect URI."""
    # Check if this is coming from Claude.ai based on the state parameter
    # Claude.ai typically includes a redirect_uri in the state or expects a specific format
    
    if error:
        # For errors, we can return a simple HTML page
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
    
    # For successful authorization, return an HTML page that will handle the OAuth flow
    # This page will either redirect to Claude or display a success message
    html_content = f"""
    <html>
    <head>
        <title>Authorization Successful</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background-color: #f5f5f5;
            }}
            .container {{
                text-align: center;
                padding: 2rem;
                background-color: white;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                max-width: 400px;
            }}
            .success {{
                color: #22c55e;
                font-size: 3rem;
                margin-bottom: 1rem;
            }}
            h1 {{
                margin: 0 0 1rem 0;
                color: #333;
            }}
            p {{
                color: #666;
                margin: 0.5rem 0;
            }}
            .code {{
                background-color: #f3f4f6;
                padding: 0.5rem;
                border-radius: 4px;
                font-family: monospace;
                font-size: 0.9rem;
                word-break: break-all;
                margin: 1rem 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success">✓</div>
            <h1>Authorization Successful!</h1>
            <p>You have successfully authorized the Telnyx MCP Server.</p>
            <p>You can now close this window and return to Claude.</p>
            <p style="margin-top: 2rem; font-size: 0.9rem; color: #999;">
                If this window doesn't close automatically, you can close it manually.
            </p>
        </div>
        <script>
            // Try to close the window after a short delay
            setTimeout(() => {{
                window.close();
            }}, 3000);
            
            // If window.close() doesn't work, try to communicate with the opener
            if (window.opener) {{
                try {{
                    // Send the authorization code back to the opener if possible
                    window.opener.postMessage({{
                        type: 'authorization_complete',
                        code: '{code}',
                        state: '{state}'
                    }}, '*');
                }} catch (e) {{
                    console.error('Could not communicate with opener:', e);
                }}
            }}
        </script>
    </body>
    </html>
    """
    
    return Response(content=html_content, media_type="text/html")


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
        "token_endpoint_auth_signing_alg": "RS256"
    }


# MCP Protocol Endpoints
@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    current_user: Optional[Dict[str, Any]] = Depends(optional_auth)
):
    """MCP endpoint implementing Streamable HTTP transport.
    
    Note: Authentication is optional to allow for OAuth discovery flow.
    """
    # For methods that require auth, return 401 with proper WWW-Authenticate header
    if not current_user:
        try:
            body = await request.body()
            message = json.loads(body)
            
            # Allow initialize and metadata discovery without auth
            if isinstance(message, dict):
                method = message.get("method")
                if method not in ["initialize", "notifications/initialized"]:
                    # Other methods require authentication
                    # Get base URL from request, handling proxy headers
                    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
                    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
                    
                    if forwarded_proto and forwarded_host:
                        base_url = f"{forwarded_proto}://{forwarded_host}"
                    else:
                        base_url = str(request.base_url).rstrip('/')
                    
                    headers = {
                        "WWW-Authenticate": f'Bearer realm="{base_url}", resource_metadata="{base_url}/.well-known/oauth-protected-resource"'
                    }
                    return Response(
                        content=json.dumps({
                            "jsonrpc": "2.0",
                            "id": message.get("id"),
                            "error": {
                                "code": -32603,
                                "message": "Authentication required"
                            }
                        }),
                        status_code=401,
                        headers=headers,
                        media_type="application/json"
                    )
            
            # Reset body for processing
            request._body = body
            
        except json.JSONDecodeError:
            pass  # Will be handled below
    # Check Accept header
    accept_header = request.headers.get("accept", "application/json")
    prefers_sse = "text/event-stream" in accept_header
    
    # Get session ID if provided
    session_id = request.headers.get("mcp-session-id")
    
    try:
        body = await request.body()
        message = json.loads(body)
    except json.JSONDecodeError as e:
        error_response = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32700,
                "message": "Parse error",
                "data": str(e)
            }
        }
        
        if prefers_sse:
            async def error_generator():
                yield {"data": json.dumps(error_response)}
            return EventSourceResponse(error_generator())
        
        return error_response
    
    # Log request
    if isinstance(message, list):
        methods = [msg.get("method") for msg in message if isinstance(msg, dict)]
        logger.info(f"MCP batch request: {methods} (user: {current_user.get('email') if current_user else 'anonymous'})")
    else:
        logger.info(f"MCP request: {message.get('method')} (user: {current_user.get('email') if current_user else 'anonymous'})")
    
    # Process the message(s)
    response = await telnyx_mcp_server.process_message(message, session_id)
    
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
            
        return EventSourceResponse(event_generator(), headers=headers)
    else:
        # Return JSON response
        headers = {}
        if session_id:
            headers["mcp-session-id"] = session_id
            
        return Response(
            content=json.dumps(response),
            media_type="application/json",
            headers=headers
        )


@app.get("/mcp")
async def mcp_sse_stream(
    request: Request,
    current_user: Optional[Dict[str, Any]] = Depends(optional_auth)
):
    """GET endpoint for server-initiated SSE stream."""
    # Get session ID if provided
    session_id = request.headers.get("mcp-session-id")
    
    # Check Accept header
    accept_header = request.headers.get("accept", "")
    if "text/event-stream" not in accept_header:
        return Response(
            status_code=405,
            content="Method not allowed - this endpoint requires Accept: text/event-stream"
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")