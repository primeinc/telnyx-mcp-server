#!/bin/bash

# Azure App Service startup script
echo "Starting Telnyx MCP Server..."
echo "Current directory: $(pwd)"
echo "Directory contents:"
ls -la

# Run the gunicorn server with our custom configuration
exec gunicorn -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 600 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    telnyx_mcp_server.remote.server:app
