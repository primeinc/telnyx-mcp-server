#!/bin/bash

# Azure App Service startup script
echo "Starting Telnyx MCP Server..."
echo "ENTRYPOINT: startup.sh"
echo "Current directory: $(pwd)"
echo "Directory contents:"
ls -la

# Set Python to unbuffered mode for immediate log output
export PYTHONUNBUFFERED=1

# Log environment info
echo "LOG_LEVEL: ${LOG_LEVEL:-INFO}"
echo "ENVIRONMENT: ${ENVIRONMENT:-development}"
echo "Python version: $(python --version)"

# Install dependencies if requirements.txt exists
if [ -f requirements.txt ]; then
    echo "Installing dependencies from requirements.txt..."
    pip install -r requirements.txt
    echo "Dependencies installed successfully"
else
    echo "ERROR: requirements.txt not found!"
    exit 1
fi

# Run the gunicorn server with our custom configuration
exec gunicorn -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --access-logfile - \
    --error-logfile - \
    --log-level ${LOG_LEVEL:-debug} \
    --capture-output \
    --enable-stdio-inheritance \
    telnyx_mcp_server.remote.server:app
