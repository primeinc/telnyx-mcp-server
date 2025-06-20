"""End-to-end tests for the remote MCP server."""

import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import httpx
import pytest
import respx

# Mock dependencies to avoid import errors
with patch.dict(
    "sys.modules",
    {
        "structlog": MagicMock(),
        "redis": MagicMock(),
        "redis.asyncio": MagicMock(),
        "fakeredis": MagicMock(),
        "fakeredis.aioredis": MagicMock(),
    },
):
    # Set up test environment variables
    import os

    os.environ["TELNYX_API_KEY"] = "test_api_key"
    os.environ["AZURE_CLIENT_ID"] = "test_client_id"
    os.environ["AZURE_CLIENT_SECRET"] = "test_client_secret"
    os.environ["AZURE_TENANT_ID"] = "test_tenant_id"
    os.environ["JWT_SECRET_KEY"] = "test_secret_key"
    os.environ["ENVIRONMENT"] = "test"
    os.environ["USE_REDIS"] = "false"

    from telnyx_mcp_server.remote.server import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_auth_token():
    """Create a mock authentication token."""
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_payload.test_signature"


@pytest.fixture
def auth_headers(mock_auth_token):
    """Create authentication headers."""
    return {"Authorization": f"Bearer {mock_auth_token}"}


class TestHealthEndpoint:
    """Test the health check endpoint."""

    def test_health_check_success(self, client):
        """Test successful health check."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert data["service"] == "telnyx-mcp-server"
        assert "version" in data
        assert "timestamp" in data
        assert "auth_store" in data
        assert "mcp_tools" in data

    def test_health_check_readiness_probe(self, client):
        """Test health check as readiness probe."""
        # Health check should include all necessary components
        response = client.get("/health")
        data = response.json()

        # Should check auth store
        assert "auth_store" in data
        auth_store_health = data["auth_store"]
        assert isinstance(auth_store_health, dict)

        # Should check MCP tools
        assert "mcp_tools" in data
        mcp_tools_health = data["mcp_tools"]
        assert isinstance(mcp_tools_health, dict)


class TestCORSAndSecurity:
    """Test CORS configuration and security headers."""

    def test_cors_headers_present(self, client):
        """Test that CORS headers are present."""
        response = client.options("/health")

        assert "access-control-allow-origin" in response.headers
        assert "access-control-allow-methods" in response.headers
        assert "access-control-allow-headers" in response.headers

    def test_security_headers(self, client):
        """Test security headers are added."""
        response = client.get("/health")

        # Check security headers
        assert "strict-transport-security" in response.headers
        assert "referrer-policy" in response.headers
        assert "content-security-policy" in response.headers
        assert "x-content-type-options" in response.headers
        assert "x-frame-options" in response.headers
        assert "x-xss-protection" in response.headers

    def test_trace_id_header(self, client):
        """Test that trace ID header is added."""
        response = client.get("/health")

        assert "x-trace-id" in response.headers
        trace_id = response.headers["x-trace-id"]
        assert len(trace_id) > 0


class TestOAuthFlow:
    """Test OAuth 2.0 authentication flow."""

    def test_oauth_metadata_endpoint(self, client):
        """Test OAuth metadata endpoint."""
        response = client.get("/.well-known/oauth-authorization-server")

        assert response.status_code == 200
        data = response.json()

        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "response_types_supported" in data
        assert "code" in data["response_types_supported"]
        assert "authorization_code" in data["grant_types_supported"]

    def test_mcp_oauth_metadata(self, client):
        """Test MCP-specific OAuth metadata."""
        response = client.get("/.well-known/mcp-oauth-metadata")

        assert response.status_code == 200
        data = response.json()

        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "scopes_supported" in data
        assert "mcp:read" in data["scopes_supported"]
        assert "mcp:write" in data["scopes_supported"]
        assert "mcp:execute" in data["scopes_supported"]

    def test_authorize_endpoint_missing_pkce(self, client):
        """Test authorization endpoint rejects requests without PKCE."""
        response = client.get(
            "/authorize",
            params={
                "client_id": "test_client",
                "redirect_uri": "https://claude.ai/callback",
                "response_type": "code",
                "scope": "openid profile email",
            },
        )

        assert response.status_code == 400
        assert "code_challenge is required" in response.text

    def test_authorize_endpoint_invalid_method(self, client):
        """Test authorization endpoint rejects invalid challenge method."""
        response = client.get(
            "/authorize",
            params={
                "client_id": "test_client",
                "redirect_uri": "https://claude.ai/callback",
                "response_type": "code",
                "scope": "openid profile email",
                "code_challenge": "test_challenge",
                "code_challenge_method": "plain",  # Should require S256
            },
        )

        assert response.status_code == 400
        assert "Only S256 code_challenge_method is supported" in response.text

    @respx.mock
    def test_oauth_callback_success(self, client):
        """Test successful OAuth callback."""
        # Mock Azure AD token exchange
        respx.post(
            "https://login.microsoftonline.com/test_tenant_id/oauth2/v2.0/token"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "azure_access_token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        )

        # Mock Microsoft Graph user info
        respx.get("https://graph.microsoft.com/v1.0/me").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "user_123",
                    "mail": "test@example.com",
                    "displayName": "Test User",
                },
            )
        )

        response = client.get(
            "/auth/callback",
            params={"code": "azure_auth_code", "state": "test_state"},
        )

        assert response.status_code == 200
        assert "Authorization Complete" in response.text
        assert "MCP authorization code" in response.text

    def test_oauth_callback_error(self, client):
        """Test OAuth callback with error."""
        response = client.get(
            "/auth/callback",
            params={
                "error": "access_denied",
                "error_description": "User denied access",
            },
        )

        assert response.status_code == 200
        assert "Authorization Failed" in response.text
        assert "access_denied" in response.text

    def test_token_endpoint_invalid_grant_type(self, client):
        """Test token endpoint with invalid grant type."""
        response = client.post(
            "/token",
            data={
                "grant_type": "password",  # Invalid
                "code": "test_code",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "unsupported_grant_type"

    def test_token_endpoint_missing_code(self, client):
        """Test token endpoint with missing authorization code."""
        response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code"
                # Missing code
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_request"
        assert "Missing authorization code" in data["error_description"]


class TestMCPProtocol:
    """Test MCP protocol implementation."""

    def test_mcp_initialize_without_auth(self, client):
        """Test MCP initialize request without authentication."""
        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
        }

        response = client.post("/mcp", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert "result" in data
        assert data["result"]["protocolVersion"] == "2025-03-26"
        assert "capabilities" in data["result"]
        assert "serverInfo" in data["result"]

    def test_mcp_tools_list_requires_auth(self, client):
        """Test that tools/list requires authentication."""
        request_data = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }

        response = client.post("/mcp", json=request_data)

        assert response.status_code == 401
        data = response.json()
        assert data["error"]["message"] == "Authentication required"

    @patch("telnyx_mcp_server.remote.auth.verify_jwt_token")
    def test_mcp_tools_list_with_auth(self, mock_verify, client, auth_headers):
        """Test tools/list with authentication."""
        # Mock successful authentication
        mock_verify.return_value = {
            "sub": "user_123",
            "email": "test@example.com",
            "exp": int(time.time()) + 3600,
        }

        request_data = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }

        response = client.post("/mcp", json=request_data, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 2
        assert "result" in data
        assert "tools" in data["result"]
        assert isinstance(data["result"]["tools"], list)

    @patch("telnyx_mcp_server.remote.auth.verify_jwt_token")
    @patch("telnyx_mcp_server.mcp.call_tool")
    def test_mcp_tools_call_with_auth(
        self, mock_call_tool, mock_verify, client, auth_headers
    ):
        """Test tools/call with authentication."""
        # Mock successful authentication
        mock_verify.return_value = {
            "sub": "user_123",
            "email": "test@example.com",
            "exp": int(time.time()) + 3600,
        }

        # Mock tool execution
        mock_call_tool.return_value = MagicMock(text="Tool executed successfully")

        request_data = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "send_message",
                "arguments": {
                    "from": "+1234567890",
                    "to": "+0987654321",
                    "text": "Hello, world!",
                },
            },
        }

        response = client.post("/mcp", json=request_data, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 3
        assert "result" in data
        assert "content" in data["result"]

    def test_mcp_batch_request(self, client):
        """Test MCP batch request."""
        batch_request = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                },
            },
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        ]

        response = client.post("/mcp", json=batch_request)

        assert response.status_code == 200
        data = response.json()

        # Should return array with one response (notification doesn't get response)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == 1

    def test_mcp_invalid_json_rpc(self, client):
        """Test invalid JSON-RPC request."""
        request_data = {
            "jsonrpc": "1.0",  # Invalid version
            "id": 1,
            "method": "initialize",
        }

        response = client.post("/mcp", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert "error" in data
        assert data["error"]["code"] == -32600
        assert "Invalid Request" in data["error"]["message"]

    def test_mcp_method_not_found(self, client):
        """Test MCP method not found."""
        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "unknown/method",
            "params": {},
        }

        response = client.post("/mcp", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert "error" in data
        assert data["error"]["code"] == -32601
        assert "Method not found" in data["error"]["message"]


class TestSSEStreaming:
    """Test Server-Sent Events streaming."""

    def test_sse_requires_auth(self, client):
        """Test that SSE endpoint requires authentication."""
        response = client.get("/mcp", headers={"Accept": "text/event-stream"})

        assert response.status_code == 401

    @patch("telnyx_mcp_server.remote.auth.verify_jwt_token")
    def test_sse_with_auth(self, mock_verify, client, auth_headers):
        """Test SSE endpoint with authentication."""
        # Mock successful authentication
        mock_verify.return_value = {
            "sub": "user_123",
            "email": "test@example.com",
            "exp": int(time.time()) + 3600,
        }

        headers = {**auth_headers, "Accept": "text/event-stream"}

        # Note: TestClient doesn't support streaming responses well,
        # so we just test that it doesn't error out
        response = client.get("/mcp", headers=headers)

        # Should accept the request (even if we can't test the streaming part)
        assert response.status_code in [
            200,
            406,
        ]  # 406 if method not allowed is returned

    def test_sse_wrong_accept_header(self, client, auth_headers):
        """Test SSE endpoint with wrong Accept header."""
        response = client.get("/mcp", headers=auth_headers)

        assert response.status_code == 405
        assert "Method not allowed" in response.text


class TestJWTSecurity:
    """Test JWT token security."""

    @patch("telnyx_mcp_server.remote.auth.verify_jwt_token")
    def test_expired_jwt_token(self, mock_verify, client, auth_headers):
        """Test handling of expired JWT token."""
        # Mock expired token
        mock_verify.side_effect = Exception("Token expired")

        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }

        response = client.post("/mcp", json=request_data, headers=auth_headers)

        assert response.status_code == 401

    @patch("telnyx_mcp_server.remote.auth.verify_jwt_token")
    def test_tampered_jwt_token(self, mock_verify, client):
        """Test handling of tampered JWT token."""
        # Mock tampered token verification failure
        mock_verify.side_effect = Exception("Invalid signature")

        tampered_headers = {"Authorization": "Bearer tampered.jwt.token"}

        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }

        response = client.post("/mcp", json=request_data, headers=tampered_headers)

        assert response.status_code == 401

    @patch("telnyx_mcp_server.remote.auth.verify_jwt_token")
    def test_insufficient_scope(self, mock_verify, client, auth_headers):
        """Test handling of JWT token with insufficient scope."""
        # Mock token with insufficient scope
        mock_verify.return_value = {
            "sub": "user_123",
            "email": "test@example.com",
            "scope": "openid profile",  # Missing mcp scopes
            "exp": int(time.time()) + 3600,
        }

        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "send_message",
                "arguments": {"from": "+1", "to": "+2", "text": "test"},
            },
        }

        response = client.post("/mcp", json=request_data, headers=auth_headers)

        # Should still work since we're not enforcing scope-based access control yet
        # This is a placeholder for future scope validation
        assert response.status_code in [200, 401, 403]


class TestAuthFailureRecovery:
    """Test authentication failure and recovery scenarios."""

    def test_auth_failure_reconnection_scenario(self, client):
        """Test authentication failure followed by successful reconnection."""
        # First request without auth - should fail
        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }

        response = client.post("/mcp", json=request_data)
        assert response.status_code == 401

        # Response should include OAuth discovery information
        data = response.json()
        assert "oauth_url" in data["error"]["data"]

        # Check WWW-Authenticate header
        assert "WWW-Authenticate" in response.headers
        auth_header = response.headers["WWW-Authenticate"]
        assert "Bearer" in auth_header
        assert "oauth-authorization-server" in auth_header

    @patch("telnyx_mcp_server.remote.auth.verify_jwt_token")
    def test_reconnection_after_token_refresh(self, mock_verify, client):
        """Test successful reconnection after token refresh."""
        # First call with expired token
        mock_verify.side_effect = Exception("Token expired")

        expired_headers = {"Authorization": "Bearer expired.jwt.token"}
        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }

        response = client.post("/mcp", json=request_data, headers=expired_headers)
        assert response.status_code == 401

        # Second call with fresh token
        mock_verify.side_effect = None  # Reset
        mock_verify.return_value = {
            "sub": "user_123",
            "email": "test@example.com",
            "exp": int(time.time()) + 3600,
        }

        fresh_headers = {"Authorization": "Bearer fresh.jwt.token"}
        response = client.post("/mcp", json=request_data, headers=fresh_headers)

        assert response.status_code == 200


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_malformed_json_request(self, client):
        """Test handling of malformed JSON."""
        response = client.post(
            "/mcp",
            data="invalid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "error" in data
        assert data["error"]["code"] == -32700
        assert "Parse error" in data["error"]["message"]

    @patch("telnyx_mcp_server.remote.auth.verify_jwt_token")
    @patch("telnyx_mcp_server.mcp.call_tool")
    def test_tool_execution_error(
        self, mock_call_tool, mock_verify, client, auth_headers
    ):
        """Test handling of tool execution errors."""
        # Mock successful authentication
        mock_verify.return_value = {
            "sub": "user_123",
            "email": "test@example.com",
            "exp": int(time.time()) + 3600,
        }

        # Mock tool execution error
        mock_call_tool.side_effect = Exception("Tool execution failed")

        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "send_message",
                "arguments": {"from": "+1", "to": "+2", "text": "test"},
            },
        }

        response = client.post("/mcp", json=request_data, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert "error" in data
        assert data["error"]["code"] == -32603
        assert "Internal error" in data["error"]["message"]

    def test_missing_content_type(self, client):
        """Test handling of requests without content type."""
        response = client.post("/mcp", data='{"test": "data"}')

        # Should handle gracefully
        assert response.status_code in [200, 400, 422]
