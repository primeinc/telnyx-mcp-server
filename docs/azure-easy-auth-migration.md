# Azure Easy Auth Migration Guide

This guide documents the migration from manual OAuth 2.0 implementation to Azure App Service Built-in Authentication (Easy Auth) with Federated Identity Credential (FIC).

## Overview

The migration eliminates all client secrets and custom authentication logic by leveraging Azure's platform-managed authentication. This significantly enhances security and reduces maintenance overhead.

### Architecture Changes

**Before (Manual OAuth):**
- Custom OAuth endpoints (`/authorize`, `/token`, `/callback`, `/register`)
- JWT_SECRET_KEY for token generation
- Redis/in-memory session storage
- Complex authorization server bridge pattern
- ~2000 lines of authentication code

**After (Easy Auth):**
- Platform-managed authentication
- No secrets in application code
- Modular authentication architecture
- Clean separation of concerns
- Focus on business logic

## New File Structure

```
src/telnyx_mcp_server/
└── remote/
    ├── auth/
    │   └── azure/
    │       ├── __init__.py           # Azure auth module exports
    │       ├── config.py             # Configuration management
    │       ├── models.py             # Pydantic models for Azure principals
    │       ├── middleware.py         # Easy Auth middleware
    │       ├── dependencies.py       # FastAPI dependencies
    │       ├── token_store.py        # Access to Easy Auth token store
    │       ├── managed_identity.py   # Managed Identity handling
    │       └── validators.py         # ID token validation
    ├── services/
    │   └── azure/
    │       ├── __init__.py
    │       ├── key_vault.py          # Key Vault access with MI
    │       └── graph_api.py          # MS Graph API client
    └── server.py                     # Main FastAPI application
```

## Phase 1: Infrastructure Verification

### 1.1 Verify authsettingsV2 Configuration

```bash
az webapp auth show -g <resource-group> -n <app-name>
```

Key values to verify:
- `"requireAuthentication": true`
- `"unauthenticatedClientAction": "RedirectToLoginPage"`
- `"clientSecretSettingName": "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID"`

### 1.2 Validate Federated Identity Credential

1. Navigate to Microsoft Entra admin center
2. Go to App Registration → Certificates & secrets → Federated credentials
3. Verify Subject identifier matches Managed Identity Principal ID
4. Verify issuer is `https://login.microsoftonline.com/<tenant-id>/v2.0`

### 1.3 Validate Redirect URIs

In App Registration → Authentication:
- Ensure redirect URI: `https://<app-name>.azurewebsites.net/.auth/login/aad/callback`

## Phase 2: Code Implementation

### 2.1 Using the New Authentication

#### Protected Endpoint Example

```python
from fastapi import Depends
from telnyx_mcp_server.remote.auth.azure import require_user, AzureClientPrincipal

@app.get("/profile")
async def get_profile(user: AzureClientPrincipal = Depends(require_user)):
    return {
        "id": user.user_id,
        "email": user.email,
        "name": user.name,
        "roles": user.roles
    }
```

#### Role-Based Access Control

```python
from telnyx_mcp_server.remote.auth.azure import require_role

@app.get("/admin", dependencies=[Depends(require_role("admin"))])
async def admin_endpoint():
    return {"message": "Admin access granted"}
```

#### Accessing Azure Services

```python
# Using Managed Identity for Key Vault
from telnyx_mcp_server.remote.services.azure import AzureKeyVaultService

vault = AzureKeyVaultService()
api_key = await vault.get_secret("telnyx-api-key")

# Using user token for MS Graph
from telnyx_mcp_server.remote.services.azure import MicrosoftGraphService

graph = MicrosoftGraphService()
user_profile = await graph.get_user_profile(request)
```

### 2.2 Application Startup

```python
from fastapi import FastAPI
from telnyx_mcp_server.remote.auth.azure import AzureEasyAuthMiddleware
from telnyx_mcp_server.remote.auth.azure.config import get_azure_auth_config

app = FastAPI()

# Add Azure Easy Auth middleware
app.add_middleware(AzureEasyAuthMiddleware)

# Configure based on environment
config = get_azure_auth_config()
config.log_configuration(logger)
```

## Phase 3: Environment Variables

### Required Variables

```env
# Azure AD Configuration
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id

# Environment
ENVIRONMENT=production
WEBSITE_AUTH_ENFORCE=true

# Optional
KEY_VAULT_URI=https://your-vault.vault.azure.net/
VALIDATE_AZURE_TOKENS=true
MCP_ALLOWED_ORIGINS=https://claude.ai
```

### Removed Variables

- `JWT_SECRET_KEY` - No longer needed
- `AZURE_CLIENT_SECRET` - Replaced by FIC
- `AZURE_REDIRECT_URI` - Managed by platform

## Phase 4: Testing

### 4.1 Unit Tests

```python
# tests/auth/azure/test_middleware.py
import pytest
from telnyx_mcp_server.remote.auth.azure import AzureEasyAuthMiddleware

def test_middleware_parses_principal_header():
    # Test implementation
    pass
```

### 4.2 Integration Tests

Test authentication flow:
1. Access protected endpoint without auth → 401
2. Access with valid Easy Auth headers → 200
3. Role-based access control
4. Token validation for critical operations

### 4.3 Manual Testing Checklist

- [ ] Browser access redirects to Azure AD login
- [ ] Successful login returns to application
- [ ] Protected endpoints require authentication
- [ ] Role-based access works correctly
- [ ] Managed Identity can access Key Vault
- [ ] User tokens can access MS Graph

## Phase 5: Security Hardening

### 5.1 App Service Configuration

Set in Azure Portal or CLI:
```bash
az webapp config appsettings set -g <rg> -n <app> --settings "WEBSITE_AUTH_ENFORCE=true"
```

### 5.2 CORS Configuration

In `config.py`:
```python
allowed_origins = ["https://claude.ai", "https://your-domain.com"]
```

### 5.3 RBAC for Managed Identity

Grant minimal required roles:
- Key Vault Secrets User (not Contributor)
- Graph API Application permissions only as needed

## Phase 6: Rollback Plan

If critical issues occur:

### 6.1 Generate New Client Secret

```bash
# In App Registration
az ad app credential reset --id <app-id>
```

### 6.2 Update App Settings

```bash
az webapp config appsettings set -g <rg> -n <app> \
  --settings "AZURE_CLIENT_SECRET=<new-secret>"
```

### 6.3 Reconfigure Auth

```bash
az webapp auth set -g <rg> -n <app> \
  --aad-client-id <client-id> \
  --aad-client-secret-setting-name AZURE_CLIENT_SECRET
```

### 6.4 Deploy Previous Version

```bash
git checkout <previous-version>
git push azure main
```

## Troubleshooting

### Common Issues

1. **401 Unauthorized**
   - Check WEBSITE_AUTH_ENFORCE setting
   - Verify FIC configuration
   - Check redirect URIs

2. **Token validation fails**
   - Verify AZURE_TENANT_ID
   - Check token audience matches client ID
   - Ensure JWKS endpoint is accessible

3. **Managed Identity errors**
   - Verify MI is assigned to App Service
   - Check RBAC permissions
   - Ensure FIC subject matches MI principal ID

### Debug Headers

Easy Auth injects these headers:
- `X-MS-CLIENT-PRINCIPAL` - Base64 encoded user claims
- `X-MS-CLIENT-PRINCIPAL-ID` - User ID
- `X-MS-CLIENT-PRINCIPAL-NAME` - Display name
- `X-MS-TOKEN-AAD-ACCESS-TOKEN` - Access token (if configured)
- `X-MS-TOKEN-AAD-ID-TOKEN` - ID token (if configured)

## Benefits Summary

1. **Zero Secrets**: No JWT_SECRET_KEY or client secrets
2. **Platform Security**: Authentication handled by Azure
3. **Simplified Code**: From ~2000 lines to focused modules
4. **Better Maintenance**: Clear separation of concerns
5. **Enhanced Security**: No long-lived credentials in code

## Next Steps

1. Complete infrastructure verification
2. Deploy new authentication modules
3. Remove legacy OAuth code
4. Test thoroughly in staging
5. Monitor post-deployment
6. Document any customizations
