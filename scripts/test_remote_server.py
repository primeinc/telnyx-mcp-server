#!/usr/bin/env python3
"""Test script for Telnyx Remote MCP Server."""

import asyncio
import os
from pathlib import Path
import sys

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def test_server():
    """Test that the remote server can start."""
    try:
        # Import the FastAPI app to ensure all modules load correctly
        from telnyx_mcp_server.remote.server import app

        print("✅ Remote server module imported successfully")
        print(f"✅ FastAPI app created: {app.title}")

        # Check that required endpoints exist
        routes = [route.path for route in app.routes]
        # List of endpoints that are required for the API to function correctly.
        # These endpoints are validated to ensure the server is configured as expected:
        # - "/" : Root endpoint for API documentation
        # - "/health" : Health check endpoint for monitoring and deployment readiness
        # - "/authorize" : OAuth 2.0 authorization endpoint for initiating auth flow
        # - "/token" : OAuth 2.0 token endpoint for exchanging codes for tokens
        # - "/mcp" : Main MCP protocol endpoint for handling tool calls
        # Update this list if new critical routes are added or existing ones are modified.
        required_endpoints = ["/", "/health", "/authorize", "/token", "/mcp"]

        missing_endpoints = [ep for ep in required_endpoints if ep not in routes]
        if missing_endpoints:
            print(f"❌ Error: Missing required endpoints: {missing_endpoints}")
            return False

        print(f"✅ All required endpoints configured ({len(routes)} total routes)")

        # Import the MCP instance to verify it exists
        from telnyx_mcp_server.mcp import mcp  # noqa: F401

        print("✅ MCP instance available")

        # Import tool modules to ensure they load without errors
        try:
            import importlib.util

            spec = importlib.util.find_spec("telnyx_mcp_server.tools")
            if spec is not None:
                print("✅ Tool modules can be imported")

            # Test that we can access the MCP server instance and initialize tools
            from telnyx_mcp_server.remote.server import telnyx_mcp_server

            await telnyx_mcp_server.initialize_tools()
            num_tools = len(telnyx_mcp_server.tools)
            if num_tools > 0:
                print(f"✅ Successfully loaded {num_tools} tools")
            else:
                print("⚠️  Warning: No tools loaded, but server can still start")

        except ImportError as e:
            print(f"⚠️  Warning: Could not import tools: {e}")
            # This is not fatal for the server test
        except Exception as e:
            print(f"⚠️  Warning: Could not initialize tools: {e}")
            # This is not fatal for the server test

        print("\n✅ Remote server is ready to run!")
        print("\nTo start the server, run:")
        print(
            "  uv run uvicorn telnyx_mcp_server.remote.server:app --reload --port 8000"
        )
        print("\nThen visit: http://localhost:8000/test-auth")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    # Check for required environment variables
    if not os.getenv("TELNYX_API_KEY"):
        print(
            "⚠️  Warning: TELNYX_API_KEY not set. Server will start but tools won't work."
        )
        print("   Set it in .env or export TELNYX_API_KEY=your-key")

    success = asyncio.run(test_server())
    sys.exit(0 if success else 1)
