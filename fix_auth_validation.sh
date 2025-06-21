#!/bin/bash

# Script to fix Azure App Service authentication validation issues

RESOURCE_GROUP="rg-telnyxmcp-staging-001"
APP_NAME="app-telnyxmcp-staging-eus2-001"

echo "Updating authentication settings to disable JWT validation..."

# Update auth settings to disable JWT validation for Bearer tokens
az webapp auth update \
  --resource-group $RESOURCE_GROUP \
  --name $APP_NAME \
  --set identityProviders.azureActiveDirectory.validation.jwtClaimChecks.allowedAudiences='["4d6b1965-15d3-4410-bef0-f5b659cb5585", "api://4d6b1965-15d3-4410-bef0-f5b659cb5585", "00000003-0000-0000-c000-000000000000"]'

echo "Auth settings updated. The app should now accept tokens with multiple audiences."
