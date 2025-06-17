# Migration to Official MCP SDK (v0.4.0)

## Overview

Version 0.4.0 migrates from the `fastmcp` package to the official [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) for improved protocol compliance and lifecycle management.

## Changes Made

### Dependencies
- **Removed**: `fastmcp>=0.4.0,<0.5.0`
- **Using**: `mcp>=1.3.0` (official SDK)

### API Changes
- Imports changed from `fastmcp.FastMCP` to `mcp.server.FastMCP`
- Tool listing method changed from `get_tools()` to `list_tools()`
- All other APIs remain compatible

### Preserved Features
- ✅ All 46 Telnyx tools work unchanged
- ✅ Tool filtering functionality (`--tools`, `--exclude-tools`)
- ✅ Remote hosting capabilities (HTTP transport)
- ✅ MSAL authentication for remote mode
- ✅ CLI and plugin entrypoints
- ✅ Environment-driven configuration
- ✅ Webhook handling

## Compatibility

### Breaking Changes
- None for end users
- Internal API change: `mcp.get_tools()` → `mcp.list_tools()`

### Testing
- All existing functionality verified
- Tool registration, filtering, and execution tested
- Remote server compatibility confirmed

## Benefits

- **Official SDK**: Now using the canonical MCP implementation
- **Protocol Compliance**: Improved adherence to MCP specification
- **Future Support**: Better alignment with MCP ecosystem development
- **Reduced Dependencies**: One less external dependency to maintain

## Upgrade Notes

For most users, this is a transparent upgrade. The server will work exactly the same way with the same configuration and CLI arguments.

For developers extending the server:
- Update any imports from `fastmcp` to `mcp.server`
- Replace `get_tools()` calls with `list_tools()`
- Tool registration with `@mcp.tool()` remains unchanged