#!/bin/bash

# Deployment diagnostics script for Azure App Service
# This script helps troubleshoot deployment issues

echo "======================================"
echo "Azure App Service Deployment Diagnostics"
echo "======================================"
echo "Run time: $(date -u)"

# Check basic environment
echo -e "\n[Environment Information]"
echo "Hostname: $(hostname)"
echo "OS: $(uname -a)"
echo "Python version: $(python --version 2>&1)"
echo "Pip version: $(pip --version 2>&1)"
echo "Current directory: $(pwd)"
echo "User: $(whoami)"

# Check for requirements.txt
echo -e "\n[Requirements File]"
if [ -f requirements.txt ]; then
    echo "✓ requirements.txt found"
    echo "  Size: $(wc -l < requirements.txt) lines"
    echo "  First package: $(head -1 requirements.txt)"
else
    echo "✗ requirements.txt NOT found"
fi

# Check for appsvc.yaml
echo -e "\n[App Service Config]"
if [ -f appsvc.yaml ]; then
    echo "✓ appsvc.yaml found"
else
    echo "✗ appsvc.yaml NOT found"
fi

# Check Python package
echo -e "\n[Python Package Structure]"
if [ -d telnyx_mcp_server ]; then
    echo "✓ telnyx_mcp_server package found"
    find telnyx_mcp_server -name "*.py" -type f | head -10
else
    echo "✗ telnyx_mcp_server package NOT found"
fi

# Check if app can be imported
echo -e "\n[Import Test]"
python -c "
try:
    from telnyx_mcp_server.remote.server import app
    print('✓ FastAPI app imported successfully')
except Exception as e:
    print(f'✗ Failed to import app: {e}')
"

# Check installed packages
echo -e "\n[Installed Packages]"
pip list | grep -E "fastapi|uvicorn|gunicorn|mcp|pydantic" || echo "Core packages not found"

# Check Oryx environment variables
echo -e "\n[Oryx Environment Variables]"
env | grep -E "ORYX|SCM|WEBSITE|PYTHON|BUILD" | sort

# Check Kudu logs location
echo -e "\n[Log Locations]"
echo "Deployment logs: /home/LogFiles/kudu/deployment"
echo "Application logs: /home/LogFiles"
echo "Oryx build logs: /home/site/deployments/[deployment-id]/log.log"

# Check disk space
echo -e "\n[Disk Space]"
df -h /home

# Check for common issues
echo -e "\n[Common Issues Check]"

# Check if running from package
if [ "$WEBSITE_RUN_FROM_PACKAGE" = "1" ]; then
    echo "⚠ WEBSITE_RUN_FROM_PACKAGE is enabled - files may be read-only"
fi

# Check if multi-instance
if [ -n "$WEBSITE_INSTANCE_ID" ]; then
    echo "Instance ID: $WEBSITE_INSTANCE_ID"
fi

echo -e "\n======================================"
echo "Diagnostics completed"
echo "======================================"
