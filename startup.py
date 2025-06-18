#!/usr/bin/env python
"""
Startup script for Azure App Service deployment.
This helps Oryx detect the application entry point.
"""

import os
import sys

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the FastAPI app
from telnyx_mcp_server.remote.server import app

# This allows Oryx to detect the WSGI/ASGI application
application = app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "telnyx_mcp_server.remote.server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
