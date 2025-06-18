#!/bin/bash

# Script to get specific Oryx build log from Azure App Service

if [ $# -lt 3 ]; then
    echo "Usage: $0 <app-name> <resource-group> <deployment-id>"
    echo "Example: $0 app-telnyxmcp-dev-eus2-001 rg-development 6d23002e-b20c-472f-8c7c-14db16cafcbb"
    exit 1
fi

APP_NAME=$1
RESOURCE_GROUP=$2
DEPLOYMENT_ID=$3

echo "Fetching Oryx build log for deployment: $DEPLOYMENT_ID"

# Get the deployment log details
echo "1. Getting deployment details..."
az webapp deployment show \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-id "$DEPLOYMENT_ID" \
    --output json > deployment-details.json

# Try to get the specific log URL from the deployment
echo "2. Fetching deployment logs..."
az webapp log deployment show \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-id "$DEPLOYMENT_ID" \
    --output json > deployment-log.json

# Use Kudu API to get the detailed log
echo "3. Fetching detailed Oryx build log via Kudu API..."
KUDU_URL="https://${APP_NAME}.scm.azurewebsites.net"

# Get the deployment log file
echo "4. Attempting to download the log file..."
# The log ID from your logs: 5176ab36-d4c6-4193-9887-d0bae95e4733
LOG_PATH="/api/deployments/${DEPLOYMENT_ID}/log/5176ab36-d4c6-4193-9887-d0bae95e4733"

# Get auth token
ACCESS_TOKEN=$(az account get-access-token --resource https://management.core.windows.net/ --query accessToken -o tsv)

# Download the log
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
     "${KUDU_URL}${LOG_PATH}" \
     -o oryx-build-log.txt

echo "5. Contents of Oryx build log:"
cat oryx-build-log.txt

# Also try the standard deployment log path
echo "6. Trying standard deployment log path..."
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
     "${KUDU_URL}/api/deployments/${DEPLOYMENT_ID}/log" \
     -o deployment-full-log.json

echo "Logs saved to current directory"
