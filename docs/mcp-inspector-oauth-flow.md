# MCP Inspector OAuth Flow Specification

This document captures the exact OAuth flow used by MCP Inspector v0.14.3 when connecting to an MCP server.

## Overview

MCP Inspector performs OAuth 2.0 authentication using the authorization code flow with PKCE. The flow consists of several discovery steps followed by dynamic client registration and standard OAuth authorization.

## Flow Sequence

### 1. OAuth Protected Resource Discovery

**Request:**
```
OPTIONS /.well-known/oauth-protected-resource HTTP/1.1
Host: localhost:8000
Connection: keep-alive
Accept: */*
Access-Control-Request-Method: GET
Access-Control-Request-Headers: mcp-protocol-version
Origin: http://localhost:6274
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36
Sec-Fetch-Mode: cors
Sec-Fetch-Site: same-site
Sec-Fetch-Dest: empty
Referer: http://localhost:6274/
Accept-Encoding: gzip, deflate, br, zstd
Accept-Language: en-US,en;q=0.9
```

**Expected Response:**
```
HTTP/1.1 200 OK
Content-Type: application/json
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: *
Content-Length: 0
```

**Request:**
```
GET /.well-known/oauth-protected-resource HTTP/1.1
Host: localhost:8000
Connection: keep-alive
sec-ch-ua-platform: "Windows"
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36
sec-ch-ua: "Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"
sec-ch-ua-mobile: ?0
Accept: */*
Origin: http://localhost:6274
Sec-Fetch-Site: same-site
Sec-Fetch-Mode: cors
Sec-Fetch-Dest: empty
Referer: http://localhost:6274/
Accept-Encoding: gzip, deflate, br, zstd
Accept-Language: en-US,en;q=0.9
```

**Expected Response:**
```json
{
  "resource": "http://localhost:8000/mcp",
  "www-authenticate": "Bearer"
}
```

### 2. OAuth Authorization Server Discovery

**Request:**
```
OPTIONS /.well-known/oauth-authorization-server HTTP/1.1
Host: localhost:8000
Connection: keep-alive
Accept: */*
Access-Control-Request-Method: GET
Access-Control-Request-Headers: mcp-protocol-version
Origin: http://localhost:6274
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36
Sec-Fetch-Mode: cors
Sec-Fetch-Site: same-site
Sec-Fetch-Dest: empty
Referer: http://localhost:6274/
Accept-Encoding: gzip, deflate, br, zstd
Accept-Language: en-US,en;q=0.9
```

**Request:**
```
GET /.well-known/oauth-authorization-server HTTP/1.1
Host: localhost:8000
Connection: keep-alive
sec-ch-ua-platform: "Windows"
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36
sec-ch-ua: "Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"
sec-ch-ua-mobile: ?0
Accept: */*
Origin: http://localhost:6274
Sec-Fetch-Site: same-site
Sec-Fetch-Mode: cors
Sec-Fetch-Dest: empty
Referer: http://localhost:6274/
Accept-Encoding: gzip, deflate, br, zstd
Accept-Language: en-US,en;q=0.9
```

**Expected Response:**
```json
{
  "issuer": "http://localhost:8000",
  "authorization_endpoint": "http://localhost:8000/authorize",
  "token_endpoint": "http://localhost:8000/token",
  "registration_endpoint": "http://localhost:8000/register",
  "response_types_supported": ["code", "token"],
  "grant_types_supported": ["authorization_code", "implicit"],
  "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
  "scopes_supported": ["openid", "profile", "email", "offline_access"],
  "code_challenge_methods_supported": ["S256"]
}
```

### 3. Dynamic Client Registration

**Request:**
```
OPTIONS /register HTTP/1.1
Host: localhost:8000
Connection: keep-alive
Accept: */*
Access-Control-Request-Method: POST
Access-Control-Request-Headers: content-type
Origin: http://localhost:6274
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36
Sec-Fetch-Mode: cors
Sec-Fetch-Site: same-site
Sec-Fetch-Dest: empty
Referer: http://localhost:6274/
Accept-Encoding: gzip, deflate, br, zstd
Accept-Language: en-US,en;q=0.9
```

**Request:**
```
POST /register HTTP/1.1
Host: localhost:8000
Connection: keep-alive
Content-Length: 320
sec-ch-ua-platform: "Windows"
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36
sec-ch-ua: "Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"
Content-Type: application/json
sec-ch-ua-mobile: ?0
Accept: */*
Origin: http://localhost:6274
Sec-Fetch-Site: same-site
Sec-Fetch-Mode: cors
Sec-Fetch-Dest: empty
Referer: http://localhost:6274/
Accept-Encoding: gzip, deflate, br, zstd
Accept-Language: en-US,en;q=0.9

{
  "redirect_uris": ["http://localhost:6274/oauth/callback/debug"],
  "token_endpoint_auth_method": "none",
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "client_name": "MCP Inspector",
  "client_uri": "https://github.com/modelcontextprotocol/inspector",
  "scope": "openid profile email offline_access"
}
```

**Expected Response:**
```json
{
  "client_id": "test-client-123",
  "client_secret": "test-secret-456",
  "redirect_uris": ["http://localhost:6274/oauth-callback"],
  "grant_types": ["authorization_code"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "client_secret_post"
}
```

### 4. Authorization Request

**Request:**
```
GET /authorize?response_type=code&client_id=test-client-123&code_challenge=SC73ETR9NBFy_orCV6dahnkyi3GsyPfmtUXRHuIKeRQ&code_challenge_method=S256&redirect_uri=http%3A%2F%2Flocalhost%3A6274%2Foauth%2Fcallback%2Fdebug&scope=openid+profile+email+offline_access HTTP/1.1
Host: localhost:8000
Connection: keep-alive
sec-ch-ua: "Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "Windows"
Upgrade-Insecure-Requests: 1
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7
Sec-Fetch-Site: same-site
Sec-Fetch-Mode: navigate
Sec-Fetch-User: ?1
Sec-Fetch-Dest: document
Accept-Encoding: gzip, deflate, br, zstd
Accept-Language: en-US,en;q=0.9
```

**Expected Response:**
```
HTTP/1.1 302 Found
Location: http://localhost:6274/oauth/callback/debug?code=fake-auth-code-123&state=test
Content-Length: 0
```

### 5. Token Exchange

**Request:**
```
POST /token HTTP/1.1
Host: localhost:8000
Connection: keep-alive
Content-Length: 237
sec-ch-ua-platform: "Windows"
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36
sec-ch-ua: "Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"
Content-Type: application/x-www-form-urlencoded
sec-ch-ua-mobile: ?0
Accept: */*
Origin: http://localhost:6274
Sec-Fetch-Site: same-site
Sec-Fetch-Mode: cors
Sec-Fetch-Dest: empty
Referer: http://localhost:6274/
Accept-Encoding: gzip, deflate, br, zstd
Accept-Language: en-US,en;q=0.9

grant_type=authorization_code&code=fake-auth-code-123&redirect_uri=http%3A%2F%2Flocalhost%3A6274%2Foauth%2Fcallback%2Fdebug&code_verifier=[PKCE_CODE_VERIFIER]&client_id=test-client-123
```

**Expected Response:**
```json
{
  "access_token": "fake-access-token-456",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "fake-refresh-token-789",
  "scope": "openid profile email offline_access"
}
```

## Key Requirements

1. **CORS Support**: All endpoints must support CORS preflight requests (OPTIONS) and include appropriate CORS headers.

2. **OAuth Discovery**: The server must implement:
   - `/.well-known/oauth-protected-resource` - Indicates the resource requires OAuth
   - `/.well-known/oauth-authorization-server` - Provides OAuth server metadata

3. **Dynamic Client Registration**: The server must support dynamic client registration at the `/register` endpoint.

4. **PKCE Support**: The authorization flow uses PKCE (Proof Key for Code Exchange) with S256 challenge method.

5. **Required OAuth Endpoints**:
   - `/register` - Dynamic client registration
   - `/authorize` - Authorization endpoint
   - `/token` - Token exchange endpoint

6. **Response Types**: The server must support at least the `code` response type for authorization code flow.

## Notes

- MCP Inspector runs on port 6274 by default
- The OAuth callback URL is `http://localhost:6274/oauth/callback/debug`
- The client uses `token_endpoint_auth_method: "none"` in registration, indicating public client authentication
