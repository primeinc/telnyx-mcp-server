"""Unified MCP server using official MCP SDK with STDIO transport."""

import os
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
)

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import Tool as MCPTool, EmbeddedResource, ImageContent, TextContent

from .telnyx.client import TelnyxClient
from .utils.logger import get_logger

logger = get_logger(__name__)

# Load environment variables
load_dotenv()

# Get API key from environment
api_key = os.getenv("TELNYX_API_KEY", "")
if not api_key:
    logger.error("TELNYX_API_KEY environment variable must be set")
    raise ValueError("TELNYX_API_KEY environment variable must be set")


class FilterableOfficialMCP(FastMCP):
    """Extended official FastMCP class that supports tool filtering."""

    def __init__(self, *args, **kwargs):
        # Call super().__init__() first to initialize the official FastMCP
        super().__init__(*args, **kwargs)

        self._enabled_tools: Optional[List[str]] = None
        self._excluded_tools: List[str] = []

    def set_enabled_tools(self, tool_names: List[str]) -> None:
        """
        Set specific tools to enable. All other tools will be disabled.

        Args:
            tool_names: List of tool names to enable
        """
        self._enabled_tools = tool_names
        logger.info(
            f"Tool filtering enabled. Available tools: {', '.join(tool_names)}"
        )

    def set_excluded_tools(self, tool_names: List[str]) -> None:
        """
        Set specific tools to exclude. All other tools will remain enabled.

        Args:
            tool_names: List of tool names to exclude
        """
        self._excluded_tools = tool_names
        logger.info(
            f"Tool exclusion enabled. Excluded tools: {', '.join(tool_names)}"
        )

    async def list_tools(
        self,
    ) -> list[MCPTool]:
        """Filter the list of tools based on enabled/excluded settings."""
        all_mcp_tools = await super().list_tools()

        # If no filtering is configured, return all tools
        if self._enabled_tools is None and not self._excluded_tools:
            return all_mcp_tools

        filtered_mcp_tools = []
        for tool_spec in all_mcp_tools:
            tool_name = tool_spec.name

            # Check if tool should be included
            if (
                self._enabled_tools is not None
                and tool_name not in self._enabled_tools
            ):
                logger.debug(
                    f"Filtering out tool: {tool_name} (not in enabled list)"
                )
                continue

            # Check if tool should be excluded
            if tool_name in self._excluded_tools:
                logger.debug(
                    f"Filtering out tool: {tool_name} (in excluded list)"
                )
                continue

            filtered_mcp_tools.append(tool_spec)

        return filtered_mcp_tools

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
    ) -> Sequence[
        TextContent | ImageContent | EmbeddedResource
    ]:
        """Filter tool calls based on enabled/excluded settings."""
        # Check if tool is allowed
        if self._enabled_tools is not None and name not in self._enabled_tools:
            logger.warning(f"Attempted to call disabled tool: '{name}'")
            raise ValueError(f"Tool '{name}' is not enabled")

        if name in self._excluded_tools:
            logger.warning(f"Attempted to call excluded tool: '{name}'")
            raise ValueError(f"Tool '{name}' is excluded")

        try:
            # Call the original FastMCP behavior to execute the tool
            return await super().call_tool(name, arguments)
        except Exception as e:
            logger.error(f"Error calling tool '{name}': {str(e)}")
            raise


# Create a single shared MCP instance with filtering support using official SDK
mcp = FilterableOfficialMCP("Telnyx MCP")

# Initialize Telnyx client with API key from environment
telnyx_client = TelnyxClient(api_key=api_key)
