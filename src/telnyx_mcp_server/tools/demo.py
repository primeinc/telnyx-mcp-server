"""Demonstration tools for the unified MCP server using official SDK."""

from typing import Any, Dict
from ..mcp import mcp
from ..utils.logger import get_logger

logger = get_logger(__name__)


@mcp.tool()
async def echo_message(message: str) -> Dict[str, Any]:
    """Simple echo tool that demonstrates the unified MCP server using official SDK.
    
    This tool simply echoes back the message provided, demonstrating that the 
    official MCP SDK integration is working correctly.

    Args:
        message: The message to echo back.
    """
    logger.info("Echo tool called with official MCP SDK")
    
    if not message:
        return {
            "error": "Message is required",
            "status": "error"
        }
    
    return {
        "echoed_message": message,
        "status": "success",
        "server_info": "Telnyx MCP Server using official MCP SDK",
        "timestamp": str(__import__("datetime").datetime.now())
    }


@mcp.tool()
async def server_info() -> Dict[str, Any]:
    """Get information about the unified MCP server implementation.
    
    This tool provides information about the current server implementation,
    confirming that it's using the official MCP SDK and unified architecture.
    
    No arguments required.
    """
    logger.info("Server info tool called")
    
    return {
        "server_name": "Telnyx MCP Server",
        "implementation": "Official MCP SDK (unified architecture)",
        "sdk_package": "mcp.server.fastmcp.FastMCP",
        "features": [
            "Tool filtering",
            "Webhook support", 
            "Telnyx API integration",
            "Unified local/remote architecture"
        ],
        "status": "active"
    }