# OAuth Implementation Guide for Telnyx MCP Server

## Overview

The Telnyx MCP Server implements OAuth 2.0 authentication as a bridge service that delegates user authentication to Microsoft Azure AD while maintaining its own authorization server identity. This document describes the complete OAuth implementation and flow.

## Architecture

### Authorization Server Bridge Model

The Telnyx MCP Server acts as its own authorization server that bridges to Microsoft Azure AD for actual user authentication. From the MCP client's perspective, the Telnyx server is the sole authorization server, while Microsoft's involvement remains transparent.

Key principles:
- The server maintains its own issuer identity
- All tokens are signed by the Telnyx server
- Microsoft Azure AD handles user authentication behind the scenes
- Clients only interact with Telnyx OAuth endpoints

## OAuth Discovery Chain

The OAuth discovery process follows a specific sequence that allows MCP clients to discover and use the authorization endpoints:

### 1. Initialize Response

When an MCP client sends an `initialize` request, the server responds with capabilities including OAuth configuration:

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {
      "auth": {
        "oauth2": true,
        "authorizationServers": [
          "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net"
        ]
      }
    }
  }
}
```

The `authorizationServers` array contains the issuer URI only, not the full metadata URL. Clients append `/.well-known/oauth-authorization-server` to discover metadata.

### 2. Unauthenticated Request Handling

When the server receives an unauthenticated request to a protected endpoint:

**Request:**
```
POST /mcp
{
  "method": "tools/list",
  "jsonrpc": "2.0",
  "id": 1
}
```

**Response:**
```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer resource_metadata="https://app-telnyxmcp-staging-eus2-001.azurewebsites.net/.well-known/oauth-protected-resource"
Link: <https://app-telnyxmcp-staging-eus2-001.azurewebsites.net/.well-known/oauth-authorization-server>; rel="oauth2-authorization-server"
Cache-Control: no-store
Access-Control-Expose-Headers: WWW-Authenticate
Content-Length: 0

```

Critical requirements:
- Response body MUST be empty (no JSON-RPC error)
- WWW-Authenticate header MUST use exact format shown
- Applies to all HTTP methods (GET, POST, etc.)

### 3. Protected Resource Metadata

**Endpoint:** `GET /.well-known/oauth-protected-resource`

**Response:**
```json
{
  "resource": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net",
  "authorization_servers": [
    "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net"
  ],
  "bearer_methods_supported": ["header"],
  "resource_signing_alg_values_supported": ["HS256"],
  "resource_documentation": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net/docs",
  "resource_policy_uri": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net/privacy",
  "resource_tos_uri": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net/terms"
}
```

The `authorization_servers` array points to the Telnyx server itself, not Microsoft.

### 4. Authorization Server Metadata

**Endpoint:** `GET /.well-known/oauth-authorization-server`

**Response:**
```json
{
  "issuer": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net",
  "authorization_endpoint": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net/authorize",
  "token_endpoint": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net/token",
  "userinfo_endpoint": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net/userinfo",
  "registration_endpoint": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net/register",
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["HS256"],
  "scopes_supported": [
    "openid",
    "profile",
    "email",
    "User.Read",
    "mcp:read",
    "mcp:write",
    "mcp:execute"
  ],
  "token_endpoint_auth_methods_supported": ["none"],
  "code_challenge_methods_supported": ["S256"],
  "claims_supported": ["sub", "email", "name", "exp", "iat"],
  "service_documentation": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net/docs"
}
```

Note: No `jwks_uri` is provided because the server uses HS256 (symmetric key signing).

## OAuth Flow

### Authorization Flow Sequence

1. **Client initiates authorization**
   - Client sends user to: `/authorize?client_id=...&redirect_uri=...&response_type=code&scope=...&state=...&code_challenge=...&code_challenge_method=S256&resource=...`
   - PKCE is mandatory (code_challenge required)
   - Resource parameter (RFC 8707) is optional but recommended

2. **Server redirects to Microsoft**
   - Server stores session data (state, PKCE, redirect_uri, resource)
   - Redirects to: `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize`

3. **User authenticates with Microsoft**
   - User completes authentication at Microsoft
   - Microsoft redirects back to: `/auth/callback?code=...&state=...`

4. **Server processes callback**
   - Exchanges Microsoft code for Microsoft tokens
   - Fetches user info from Microsoft Graph API
   - Generates internal authorization code
   - Redirects to client's redirect_uri with code

5. **Client exchanges code for token**
   - Client posts to: `/token` with code, code_verifier, and optional resource
   - Server validates PKCE
   - Server creates JWT with its own issuer
   - Returns access token

### Token Exchange

**Request:**
```
POST /token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&
code=...&
client_id=...&
code_verifier=...&
resource=https://app-telnyxmcp-staging-eus2-001.azurewebsites.net
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 86400,
  "scope": "openid profile email mcp:read mcp:write mcp:execute"
}
```

### JWT Token Structure

Tokens issued by the server include:

```json
{
  "sub": "user-id",
  "email": "user@example.com",
  "name": "User Name",
  "exp": 1234567890,
  "iat": 1234567890,
  "iss": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net",
  "aud": "https://app-telnyxmcp-staging-eus2-001.azurewebsites.net"
}
```

The `iss` claim MUST match the issuer in the authorization server metadata.

## Authentication Methods

### 1. OAuth Bearer Token

Standard OAuth flow as described above. Tokens sent via Authorization header:

```
Authorization: Bearer eyJ...
```

### 2. Azure Built-in Authentication (Easy Auth)

When deployed to Azure App Service with Built-in Authentication enabled:
- Browser-based clients can use `/.auth/login/aad`
- Server validates via `X-MS-CLIENT-PRINCIPAL` header
- No client secrets required due to Federated Identity Credentials

## Implementation Details

### Endpoint Summary

| Endpoint | Purpose |
|----------|---------|
| `POST /mcp` | Main MCP endpoint (requires auth except for initialize) |
| `GET /mcp` | SSE stream endpoint (requires auth) |
| `GET /.well-known/oauth-protected-resource` | RFC 9728 resource metadata |
| `GET /.well-known/oauth-authorization-server` | RFC 8414 AS metadata |
| `GET /authorize` | OAuth authorization endpoint |
| `POST /token` | OAuth token endpoint |
| `GET /auth/callback` | Microsoft OAuth callback handler |
| `POST /register` | Dynamic client registration |

### Security Considerations

1. **PKCE Required**: All authorization requests must include code_challenge
2. **Token Signing**: Uses HS256 with server-side secret
3. **Token Validation**: Server validates its own tokens on each request
4. **Code Replay Prevention**: Authorization codes marked as used after first exchange
5. **Audience Validation**: Tokens include audience claim when resource parameter provided

### Error Handling

All OAuth errors follow RFC 6749 error response format:

```json
{
  "error": "invalid_grant",
  "error_description": "Authorization code is invalid or expired"
}
```

401 responses for MCP endpoints have empty bodies to trigger OAuth discovery.

## Deployment Configuration

Required environment variables:

- `AZURE_TENANT_ID`: Microsoft tenant ID
- `AZURE_CLIENT_ID`: Azure AD application ID
- `AZURE_CLIENT_SECRET`: Azure AD application secret
- `AZURE_REDIRECT_URI`: OAuth callback URL
- `BASE_URL`: Server base URL for issuer identity
- `JWT_SECRET_KEY`: Secret for signing JWT tokens
- `WEBSITE_AUTH_ENABLED`: Set to "true" when using Azure Built-in Auth

## Testing OAuth Flow

### Quick Validation Tests

1. **Check 401 response format:**
   ```bash
   curl -i -X POST https://server/mcp \
     -d '{"method":"tools/list","jsonrpc":"2.0"}'
   ```
   Should return 401 with WWW-Authenticate header and empty body.

2. **Verify resource metadata:**
   ```bash
   curl https://server/.well-known/oauth-protected-resource
   ```
   Should show authorization_servers pointing to server itself.

3. **Verify AS metadata:**
   ```bash
   curl https://server/.well-known/oauth-authorization-server
   ```
   Should show issuer matching server URL.

### Full Flow Test

1. Initialize connection and verify OAuth capability advertised
2. Attempt authenticated method and receive 401
3. Follow OAuth flow to obtain token
4. Retry request with token in Authorization header
5. Verify successful response
