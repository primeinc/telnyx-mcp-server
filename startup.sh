#!/bin/bash
# Startup script for Telnyx Remote MCP Server on Azure App Service

echo "Starting Telnyx Remote MCP Server..."

# Export any additional environment variables if needed
export PYTHONUNBUFFERED=1

# Start the application with gunicorn
exec gunicorn -w 2 -k uvicorn.workers.UvicornWorker \
  -b 0.0.0.0:8000 \
  --timeout 600 \
  --access-logfile '-' \
  --error-logfile '-' \
  telnyx_mcp_server.remote.server:app