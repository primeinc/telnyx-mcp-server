# Deployment Secrets Configuration

## Overview
This document tracks the Azure App registrations and GitHub secrets configuration for the Telnyx MCP Server deployment.

## Azure App Registrations

### OAuth Apps (for user authentication)
We discovered THREE OAuth apps in the tenant:

1. **telnyx-mcp-server-oauth-20250618044941**
   - App ID: `ff80b7c9-c497-41de-b253-08af89d9df96`
   - Created: June 18, 2025 04:49:41
   - Status: Not currently used

2. **telnyx-mcp-server-oauth-20250618050345**
   - App ID: `3f403795-679c-4932-b2ae-521dc82cb652`
   - Created: June 18, 2025 05:03:45
   - Status: Was initially in GitHub secrets, but not the correct one

3. **Telnyx MCP Server** (The correct one from Bicep deployment)
   - App ID: `4d6b1965-15d3-4410-bef0-f5b659cb5585`
   - Display Name: Telnyx MCP Server
   - Status: **ACTIVE** - This is what the deployment created and should be used

### GitHub Actions App (for deployment)
- **github-actions-deploy**
  - App ID: `46496289-758c-4ccc-ad43-c781467d102e`
  - Uses Federated Identity Credentials (no client secret)
  - Trusts: `repo:primeinc/telnyx-mcp-server:environment:staging`

## GitHub Secrets Architecture

### Repository-level Secrets
- `AZURE_TENANT_ID`: `cffbf047-c1e9-4778-a916-93e4e5274641` (same across all environments)
- `TELNYX_API_KEY`: Your Telnyx API key (shared across environments)

### Environment-specific Secrets (staging)
- `AZURE_DEPLOY_CLIENT_ID`: `46496289-758c-4ccc-ad43-c781467d102e` (GitHub Actions app for deployment)
- `AZURE_OAUTH_CLIENT_ID`: `4d6b1965-15d3-4410-bef0-f5b659cb5585` (OAuth app for user auth)
- `AZURE_SUBSCRIPTION_ID`: `98a49ff3-2204-48c2-9908-6d6c121ee372` (staging/sandbox subscription)
- `AZURE_WEBAPP_NAME`: `app-telnyxmcp-staging-eus2-001`
- `JWT_SECRET_KEY`: Your JWT signing key

## Key Learnings

1. **Clear Naming**: We renamed `AZURE_CLIENT_ID` to `AZURE_DEPLOY_CLIENT_ID` in the workflow to avoid confusion between the deployment service principal and the OAuth app.

2. **Multiple OAuth Apps**: Multiple OAuth apps were created during testing. Always verify which one is actually deployed by checking the azd environment values.

3. **No Client Secrets**: With Built-in Auth and Federated Identity Credentials, we don't need client secrets for either:
   - GitHub Actions (uses OIDC)
   - OAuth app (uses managed identity with FIC)

## Verification Commands

```bash
# Check deployed app settings
az webapp config appsettings list --name app-telnyxmcp-staging-eus2-001 --resource-group rg-telnyxmcp-staging-001 -o table

# List OAuth apps
az ad app list --filter "startswith(displayName,'telnyx-mcp-server')" --query "[].{appId:appId,displayName:displayName}" -o table

# Check GitHub secrets
gh secret list --env staging

# Check azd environment values
azd env get-values | grep -E "(CLIENT_ID|OAUTH)" | sort
```
