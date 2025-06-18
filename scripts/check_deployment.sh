#!/bin/bash

# Check Azure App Service deployment and build logs

APP_NAME="app-telnyxmcp-dev-eus2-001"
RESOURCE_GROUP="rg-telnyxmcp-dev-001"

echo "=== Checking recent deployments ==="
az webapp deployment list -g $RESOURCE_GROUP -n $APP_NAME --output table

echo -e "\n=== Getting latest deployment logs ==="
az webapp log deployment show -g $RESOURCE_GROUP -n $APP_NAME --output json > deployment_log.json

echo -e "\n=== Checking for build errors ==="
cat deployment_log.json | grep -i "error\|fail\|pip\|requirements\|oryx" | head -20

echo -e "\n=== Checking app settings related to build ==="
az webapp config appsettings list -g $RESOURCE_GROUP -n $APP_NAME --output json | grep -E "SCM_|ORYX|WEBSITE_RUN|BUILD" -A 1 -B 1

echo -e "\n=== Live log tail (Ctrl+C to stop) ==="
az webapp log tail -g $RESOURCE_GROUP -n $APP_NAME
