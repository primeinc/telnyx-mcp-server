#!/bin/bash

# Azure App Service startup script
echo "Starting Telnyx MCP Server..."
echo "Current directory: $(pwd)"
echo "Directory contents:"
ls -la

# Set Python to unbuffered mode for immediate log output
export PYTHONUNBUFFERED=1

# Log environment info
echo "LOG_LEVEL: ${LOG_LEVEL:-INFO}"
echo "ENVIRONMENT: ${ENVIRONMENT:-development}"
echo "Python version: $(python --version)"

# Run the gunicorn server with our custom configuration
exec gunicorn -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --access-logfile - \
    --error-logfile - \
    --log-level ${LOG_LEVEL:-info} \
    --capture-output \
    --enable-stdio-inheritance \
    telnyx_mcp_server.remote.server:app
