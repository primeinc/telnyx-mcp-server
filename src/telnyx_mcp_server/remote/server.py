"""Remote MCP server implementation for Telnyx using FastAPI."""

from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import Any, Dict, Optional, List
import logging
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import json
import asyncio

# Import authentication
from .auth import AuthService, get_current_user, optional_auth

# Import existing Telnyx MCP components
from ..mcp import mcp
from ..config import settings
from ..utils.logger import get_logger
from mcp.types import Tool as MCPTool

# Load environment variables
load_dotenv()

# Configure logging
logger = get_logger(__name__)

# Pydantic Models for MCP protocol
class Tool(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any]

class Resource(BaseModel):
    uri: str
    name: str
    description: Optional[str] = None
    mimeType: Optional[str] = None


class TelnyxMCPServer:
    """Telnyx MCP Server implementation."""
    
    def __init__(self):
        """Initialize the MCP server with Telnyx tools."""
        self.tools: Dict[str, Tool] = {}
        self.resources: Dict[str, Resource] = {}
        self._tools_initialized = False
    
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
            
            # Convert to our Tool format
            for tool_def in tools_list:
                # MCPTool has attributes: name, description, inputSchema
                self.tools[tool_def.name] = Tool(
                    name=tool_def.name,
                    description=tool_def.description or "",
                    inputSchema=tool_def.inputSchema
                )
            
            self._tools_initialized = True
            logger.info(f"Initialized {len(self.tools)} Telnyx tools")
            
            # Log the available tools for debugging
            if self.tools:
                logger.info(f"Available tools: {', '.join(self.tools.keys())}")
            
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}", exc_info=True)
            # Don't mark as initialized on failure
            self._tools_initialized = False
    
    async def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {
                    "listChanged": True
                },
                "resources": {
                    "subscribe": True,
                    "listChanged": True
                }
            },
            "serverInfo": {
                "name": "Telnyx MCP Server",
                "version": "1.0.0"
            }
        }
    
    async def handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request."""
        # Ensure tools are initialized
        await self.initialize_tools()
        tools_list = [tool.dict() for tool in self.tools.values()]
        return {"tools": tools_list}
    
    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request by delegating to the existing MCP implementation."""
        # Ensure tools are initialized
        await self.initialize_tools()
        
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        if tool_name not in self.tools:
            raise HTTPException(status_code=400, detail=f"Tool '{tool_name}' not found")
        
        try:
            # Call the tool through the existing MCP instance
            result = await mcp.call_tool(tool_name, arguments)
            
            # Format the result according to MCP protocol
            if hasattr(result, 'text'):
                content = [{"type": "text", "text": result.text}]
            elif hasattr(result, 'content'):
                content = result.content
            else:
                content = [{"type": "text", "text": str(result)}]
            
            return {"content": content}
            
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error executing tool: {str(e)}"
                    }
                ]
            }
    
    async def handle_resources_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle resources/list request."""
        resources_list = [resource.dict() for resource in self.resources.values()]
        return {"resources": resources_list}
    
    async def handle_resources_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri")
        
        # For now, return empty resources
        raise HTTPException(status_code=404, detail=f"Resource '{uri}' not found")


# Initialize MCP server
telnyx_mcp_server = TelnyxMCPServer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Telnyx Remote MCP Server")
    # Initialize tools asynchronously
    await telnyx_mcp_server.initialize_tools()
    yield
    logger.info("Shutting down Telnyx Remote MCP Server")


# Create FastAPI app
app = FastAPI(
    title="Telnyx Remote MCP Server",
    description="Remote Model Context Protocol server for Telnyx API integration with OAuth authentication",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint with server information."""
    return {
        "name": "Telnyx Remote MCP Server",
        "status": "healthy",
        "authentication": {
            "type": "Azure OAuth 2.0",
            "login_endpoint": "/auth/login",
            "test_page": "/test-auth",
            "required_for": ["/mcp/stream", "/tools", "/resources"]
        },
        "endpoints": {
            "health": "/health",
            "login": "/auth/login",
            "callback": "/auth/callback",
            "me": "/auth/me",
            "test": "/test-auth",
            "mcp": "/mcp",
            "mcp_legacy": "/mcp/stream",
            "docs": "/docs"
        },
        "tools_available": len(telnyx_mcp_server.tools)
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "telnyx-mcp-server",
        "mode": "remote"
    }


# Authentication routes
@app.get("/auth/login")
async def login():
    """Initiate Azure OAuth login."""
    auth_url = AuthService.get_authorization_url()
    return RedirectResponse(url=auth_url, status_code=302)


@app.get("/auth/url")
async def get_auth_url():
    """Get the OAuth authorization URL as JSON."""
    auth_url = AuthService.get_authorization_url()
    return {"auth_url": auth_url}


@app.get("/auth/callback")
async def auth_callback(code: str = None, error: str = None, state: str = None):
    """Handle OAuth callback from Azure."""
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error: {error}"
        )
    
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code not provided"
        )
    
    try:
        # Exchange code for token
        token_data = await AuthService.exchange_code_for_token(code)
        access_token = token_data.get("access_token")
        
        # Get user info
        user_info = await AuthService.get_user_info(access_token)
        
        # Create JWT token
        jwt_token = AuthService.create_jwt_token(user_info)
        
        # Return success page with token
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authentication Successful - Telnyx MCP</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
                .success {{ color: green; }}
                .token {{ background: #f5f5f5; padding: 10px; margin: 10px 0; border-radius: 5px; word-break: break-all; font-family: monospace; font-size: 12px; }}
                .user-info {{ background: #e8f4fd; padding: 15px; margin: 10px 0; border-radius: 5px; }}
                code {{ background: #f5f5f5; padding: 2px 4px; border-radius: 3px; }}
            </style>
        </head>
        <body>
            <h1 class="success">✅ Authentication Successful!</h1>
            <div class="user-info">
                <h3>Welcome, {user_info.get('displayName', 'User')}!</h3>
                <p><strong>Email:</strong> {user_info.get('mail') or user_info.get('userPrincipalName', 'N/A')}</p>
                <p><strong>ID:</strong> {user_info.get('id', 'N/A')}</p>
            </div>
            <h3>Your JWT Token:</h3>
            <div class="token">{jwt_token}</div>
            <p><strong>Instructions:</strong></p>
            <ol>
                <li>Copy the token above</li>
                <li>Use it in the Authorization header as: <code>Bearer &lt;token&gt;</code></li>
                <li>The token expires in {os.getenv('JWT_EXPIRATION_HOURS', '24')} hours</li>
            </ol>
            <p><a href="/test-auth">Test your authentication</a> | <a href="/docs">API Documentation</a></p>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {str(e)}"
        )


@app.get("/auth/me")
async def get_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Get current user information."""
    return {"user": current_user}


@app.get("/test-auth")
async def test_auth_page():
    """Serve a page to test authentication."""
    tools_list = list(telnyx_mcp_server.tools.keys())
    tools_json = str(tools_list).replace("'", '"')
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Telnyx MCP Server - Test Authentication</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 50px auto; padding: 20px; }}
            .container {{ margin: 20px 0; }}
            input, button, select {{ padding: 10px; margin: 5px; }}
            input[type="text"] {{ width: 400px; }}
            select {{ width: 200px; }}
            .response {{ background: #f5f5f5; padding: 15px; margin: 10px 0; border-radius: 5px; min-height: 100px; max-height: 400px; overflow-y: auto; }}
            .error {{ color: red; }}
            .success {{ color: green; }}
            pre {{ white-space: pre-wrap; word-wrap: break-word; }}
            .tool-test {{ background: #f9f9f9; padding: 15px; margin: 10px 0; border-radius: 5px; }}
        </style>
    </head>
    <body>
        <h1>Telnyx MCP Server - Authentication Test</h1>
        
        <div class="container">
            <h3>1. Login to get token:</h3>
            <button onclick="login()">Start Azure OAuth Login</button>
        </div>
        
        <div class="container">
            <h3>2. Test authenticated endpoint:</h3>
            <input type="text" id="token" placeholder="Paste your JWT token here" />
            <button onclick="testAuth()">Test /auth/me</button>
        </div>
        
        <div class="container">
            <h3>3. Test MCP Tools:</h3>
            <button onclick="listTools()">List Available Tools</button>
            
            <div class="tool-test">
                <h4>Test a Tool:</h4>
                <select id="toolSelect">
                    <option value="">Select a tool...</option>
                </select>
                <button onclick="showToolDetails()">Show Tool Details</button>
                <button onclick="testTool()">Execute Tool</button>
                <div id="toolParams" style="margin-top: 10px;"></div>
            </div>
        </div>
        
        <div class="container">
            <h3>Response:</h3>
            <div id="response" class="response">Ready to test...</div>
        </div>
        
        <script>
            const availableTools = {tools_json};
            
            // Populate tool selector
            const toolSelect = document.getElementById('toolSelect');
            availableTools.forEach(tool => {{
                const option = document.createElement('option');
                option.value = tool;
                option.textContent = tool;
                toolSelect.appendChild(option);
            }});
            
            function login() {{
                fetch('/auth/url')
                    .then(response => response.json())
                    .then(data => {{
                        if (data.auth_url) {{
                            window.open(data.auth_url, '_blank');
                            document.getElementById('response').innerHTML = '<span class="success">✅ Login window opened. Complete the login and copy your token.</span>';
                        }}
                    }})
                    .catch(error => {{
                        document.getElementById('response').innerHTML = '<span class="error">❌ Error: ' + error + '</span>';
                    }});
            }}
            
            function testAuth() {{
                const token = document.getElementById('token').value;
                if (!token) {{
                    document.getElementById('response').innerHTML = '<span class="error">❌ Please enter a token first</span>';
                    return;
                }}
                
                fetch('/auth/me', {{
                    headers: {{
                        'Authorization': 'Bearer ' + token
                    }}
                }})
                .then(response => response.json())
                .then(data => {{
                    document.getElementById('response').innerHTML = '<span class="success">✅ Authentication Success!</span><br><pre>' + JSON.stringify(data, null, 2) + '</pre>';
                }})
                .catch(error => {{
                    document.getElementById('response').innerHTML = '<span class="error">❌ Error: ' + error + '</span>';
                }});
            }}
            
            function listTools() {{
                const token = document.getElementById('token').value;
                if (!token) {{
                    document.getElementById('response').innerHTML = '<span class="error">❌ Please enter a token first</span>';
                    return;
                }}
                
                fetch('/mcp/stream', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + token
                    }},
                    body: JSON.stringify({{
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {{}}
                    }})
                }})
                .then(response => response.json())
                .then(data => {{
                    document.getElementById('response').innerHTML = '<span class="success">✅ Available Telnyx Tools:</span><br><pre>' + JSON.stringify(data, null, 2) + '</pre>';
                }})
                .catch(error => {{
                    document.getElementById('response').innerHTML = '<span class="error">❌ Error: ' + error + '</span>';
                }});
            }}
            
            function showToolDetails() {{
                const selectedTool = document.getElementById('toolSelect').value;
                if (!selectedTool) {{
                    alert('Please select a tool first');
                    return;
                }}
                
                // For now, just show the tool name
                document.getElementById('toolParams').innerHTML = `<p>Selected tool: <strong>${{selectedTool}}</strong></p>`;
                document.getElementById('response').innerHTML = `Ready to execute tool: ${{selectedTool}}`;
            }}
            
            function testTool() {{
                const token = document.getElementById('token').value;
                const selectedTool = document.getElementById('toolSelect').value;
                
                if (!token) {{
                    document.getElementById('response').innerHTML = '<span class="error">❌ Please enter a token first</span>';
                    return;
                }}
                
                if (!selectedTool) {{
                    document.getElementById('response').innerHTML = '<span class="error">❌ Please select a tool first</span>';
                    return;
                }}
                
                // Example parameters for common tools
                let args = {{}};
                if (selectedTool === 'send_sms') {{
                    args = {{ to: '+1234567890', from: '+0987654321', text: 'Test message from Telnyx MCP' }};
                }}
                
                fetch('/mcp/stream', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + token
                    }},
                    body: JSON.stringify({{
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {{
                            "name": selectedTool,
                            "arguments": args
                        }}
                    }})
                }})
                .then(response => response.json())
                .then(data => {{
                    document.getElementById('response').innerHTML = '<span class="success">✅ Tool Execution Result:</span><br><pre>' + JSON.stringify(data, null, 2) + '</pre>';
                }})
                .catch(error => {{
                    document.getElementById('response').innerHTML = '<span class="error">❌ Error: ' + error + '</span>';
                }});
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# REST endpoints for tools and resources (authenticated)
@app.get("/tools")
async def list_tools(current_user: Dict[str, Any] = Depends(get_current_user)):
    """REST endpoint to list available tools."""
    logger.info(f"User {current_user.get('email')} requested tools list")
    return {"tools": [tool.dict() for tool in telnyx_mcp_server.tools.values()]}


@app.get("/resources")
async def list_resources(current_user: Dict[str, Any] = Depends(get_current_user)):
    """REST endpoint to list available resources."""
    logger.info(f"User {current_user.get('email')} requested resources list")
    return {"resources": [resource.dict() for resource in telnyx_mcp_server.resources.values()]}


# MCP Protocol Endpoints
@app.get("/mcp/stream")
async def mcp_stream_info():
    """Information about the MCP stream endpoint."""
    return {
        "info": "Telnyx MCP Streamable HTTP Transport Endpoint",
        "description": "This endpoint accepts POST requests with JSON-RPC 2.0 messages for MCP communication",
        "protocol_version": "2024-11-05",
        "authentication": "Required - use Bearer token from /auth/login",
        "methods": ["POST"],
        "available_methods": [
            "initialize",
            "tools/list",
            "tools/call",
            "resources/list",
            "resources/read"
        ],
        "example_request": {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        }
    }


@app.post("/mcp/stream")
async def mcp_stream_endpoint(request: Request, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Main MCP endpoint with streamable HTTP support."""
    try:
        message = await request.json()
        logger.info(f"User {current_user.get('email')} sent MCP message: {message.get('method')}")
        
        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id")
        
        if method == "initialize":
            result = await telnyx_mcp_server.handle_initialize(params)
            # Add user info to initialization response
            result["userInfo"] = {
                "email": current_user.get("email"),
                "name": current_user.get("name"),
                "authenticated": True
            }
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result
            }
        elif method == "tools/list":
            result = await telnyx_mcp_server.handle_tools_list(params)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result
            }
        elif method == "tools/call":
            result = await telnyx_mcp_server.handle_tools_call(params)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result
            }
        elif method == "resources/list":
            result = await telnyx_mcp_server.handle_resources_list(params)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result
            }
        elif method == "resources/read":
            result = await telnyx_mcp_server.handle_resources_read(params)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found"
                }
            }
        
    except Exception as e:
        logger.error(f"MCP stream error: {e}")
        return {
            "jsonrpc": "2.0",
            "id": message.get("id") if 'message' in locals() else None,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }


@app.get("/mcp/capabilities")
async def mcp_capabilities():
    """Return MCP server capabilities."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {"listChanged": True},
            "resources": {"subscribe": True, "listChanged": True}
        },
        "serverInfo": {
            "name": "Telnyx MCP Server",
            "version": "1.0.0"
        }
    }


@app.options("/mcp/stream")
async def mcp_stream_options():
    """Handle CORS preflight for MCP stream endpoint."""
    return {
        "status": "ok",
        "methods": ["POST", "OPTIONS"],
        "headers": ["Content-Type", "Accept", "Authorization"]
    }


@app.post("/sse")
async def mcp_sse_endpoint(request: Request, current_user: Dict[str, Any] = Depends(get_current_user)):
    """SSE endpoint for MCP communication - compatible with Claude MCP connector."""
    async def event_generator():
        try:
            # Read the entire request body
            body = await request.body()
            message = json.loads(body)
            
            logger.info(f"SSE: User {current_user.get('email')} sent MCP message: {message.get('method')}")
            
            method = message.get("method")
            params = message.get("params", {})
            msg_id = message.get("id")
            
            # Process the message
            result = None
            error = None
            
            try:
                if method == "initialize":
                    result = await telnyx_mcp_server.handle_initialize(params)
                    # Add user info to initialization response
                    result["userInfo"] = {
                        "email": current_user.get("email"),
                        "name": current_user.get("name"),
                        "authenticated": True
                    }
                elif method == "tools/list":
                    result = await telnyx_mcp_server.handle_tools_list(params)
                elif method == "tools/call":
                    result = await telnyx_mcp_server.handle_tools_call(params)
                elif method == "resources/list":
                    result = await telnyx_mcp_server.handle_resources_list(params)
                elif method == "resources/read":
                    result = await telnyx_mcp_server.handle_resources_read(params)
                else:
                    error = {
                        "code": -32601,
                        "message": f"Method '{method}' not found"
                    }
            except Exception as e:
                logger.error(f"SSE processing error: {e}", exc_info=True)
                error = {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                }
            
            # Create response
            response = {
                "jsonrpc": "2.0",
                "id": msg_id
            }
            
            if error:
                response["error"] = error
            else:
                response["result"] = result
            
            # Send the response as SSE
            yield {
                "event": "message",
                "data": json.dumps(response)
            }
            
        except Exception as e:
            logger.error(f"SSE stream error: {e}", exc_info=True)
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32603,
                    "message": f"Stream error: {str(e)}"
                }
            }
            yield {
                "event": "error",
                "data": json.dumps(error_response)
            }
    
    return EventSourceResponse(event_generator())


@app.get("/sse")
async def mcp_sse_info():
    """Information about the SSE endpoint."""
    return {
        "info": "Telnyx MCP Server-Sent Events Endpoint",
        "description": "This endpoint accepts POST requests with JSON-RPC 2.0 messages for MCP communication via SSE",
        "protocol_version": "2024-11-05",
        "authentication": "Required - use Bearer token from /auth/login",
        "compatibility": "Claude MCP Connector (anthropic-beta: mcp-client-2025-04-04)",
        "usage": {
            "endpoint": "/sse",
            "method": "POST",
            "headers": {
                "Authorization": "Bearer <token>",
                "Content-Type": "application/json"
            }
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")