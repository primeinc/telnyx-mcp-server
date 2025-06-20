"""Tests for structured logging and PII redaction."""

from unittest.mock import MagicMock, patch

import pytest

# Mock structlog to avoid import errors in test environment
structlog_mock = MagicMock()
structlog_mock.get_logger = MagicMock()
structlog_mock.configure = MagicMock()
structlog_mock.dev = MagicMock()
structlog_mock.stdlib = MagicMock()
structlog_mock.processors = MagicMock()
structlog_mock.make_filtering_bound_logger = MagicMock()

with patch.dict("sys.modules", {"structlog": structlog_mock}):
    from telnyx_mcp_server.remote.structured_logging import (
        PIIRedactorProcessor,
        add_log_level,
        add_logger_name,
        add_timestamp,
        add_trace_id,
        clear_trace_id,
        configure_structlog,
        get_logger,
        get_trace_id,
        set_trace_id,
    )


class TestPIIRedactorProcessor:
    """Test the PII redaction processor."""

    @pytest.fixture
    def redactor(self):
        """Create a PII redactor instance."""
        return PIIRedactorProcessor()

    def test_redact_sensitive_keys(self, redactor):
        """Test redaction of sensitive keys."""
        event_dict = {
            "message": "User login",
            "token": "secret_token_123",
            "password": "secret_password",
            "api_key": "api_key_abc123",
            "email": "user@example.com",
            "normal_field": "normal_value",
        }

        result = redactor(None, "info", event_dict)

        assert result["token"] == "[REDACTED]"
        assert result["password"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"
        assert result["email"] == "[REDACTED]"
        assert result["normal_field"] == "normal_value"

    def test_redact_authorization_headers(self, redactor):
        """Test redaction of authorization headers."""
        event_dict = {
            "headers": {
                "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
                "content-type": "application/json",
            }
        }

        result = redactor(None, "info", event_dict)

        assert result["headers"]["authorization"] == "[REDACTED]"
        assert result["headers"]["content-type"] == "application/json"

    def test_redact_string_patterns(self, redactor):
        """Test redaction of sensitive patterns in strings."""
        event_dict = {
            "message": "User bearer token abc123def456 was used for API call",
            "request_data": "Authorization: Bearer xyz789 and password=secret123",
        }

        result = redactor(None, "info", event_dict)

        # Should redact token patterns
        assert "abc123def456" not in result["message"]
        assert "[REDACTED]" in result["message"]
        assert "secret123" not in result["request_data"]

    def test_redact_nested_structures(self, redactor):
        """Test redaction in nested dictionaries and lists."""
        event_dict = {
            "user_data": {
                "name": "John Doe",
                "email": "john@example.com",
                "credentials": {"password": "secret", "api_key": "key123"},
            },
            "api_calls": [
                {"method": "GET", "url": "/api/users"},
                {
                    "method": "POST",
                    "headers": {"authorization": "Bearer token123"},
                },
            ],
        }

        result = redactor(None, "info", event_dict)

        assert result["user_data"]["email"] == "[REDACTED]"
        assert result["user_data"]["credentials"]["password"] == "[REDACTED]"
        assert result["user_data"]["credentials"]["api_key"] == "[REDACTED]"
        assert result["api_calls"][1]["headers"]["authorization"] == "[REDACTED]"
        assert result["user_data"]["name"] == "John Doe"  # Non-sensitive data preserved

    def test_redact_phone_numbers(self, redactor):
        """Test redaction of phone number patterns."""
        event_dict = {
            "message": "Called phone number +1-555-123-4567 for verification",
            "contact": "Phone: (555) 987-6543",
        }

        result = redactor(None, "info", event_dict)

        assert "+1-555-123-4567" not in result["message"]
        assert "(555) 987-6543" not in result["contact"]
        assert "[REDACTED]" in result["message"]
        assert "[REDACTED]" in result["contact"]

    def test_redact_credit_cards(self, redactor):
        """Test redaction of credit card patterns."""
        event_dict = {
            "payment_info": "Credit card 4532-1234-5678-9012 was charged",
            "card_data": "Card number: 4111 1111 1111 1111",
        }

        result = redactor(None, "info", event_dict)

        assert "4532-1234-5678-9012" not in result["payment_info"]
        assert "4111 1111 1111 1111" not in result["card_data"]
        assert "[REDACTED]" in result["payment_info"]
        assert "[REDACTED]" in result["card_data"]

    def test_preserve_non_sensitive_data(self, redactor):
        """Test that non-sensitive data is preserved."""
        event_dict = {
            "timestamp": "2023-01-01T12:00:00Z",
            "level": "INFO",
            "logger": "test_logger",
            "message": "User performed action",
            "user_id": "user_123",
            "action": "login",
            "status": "success",
        }

        result = redactor(None, "info", event_dict)

        # All non-sensitive data should be preserved
        assert result["timestamp"] == "2023-01-01T12:00:00Z"
        assert result["level"] == "INFO"
        assert result["logger"] == "test_logger"
        assert result["message"] == "User performed action"
        assert result["user_id"] == "user_123"
        assert result["action"] == "login"
        assert result["status"] == "success"

    def test_custom_redaction_string(self):
        """Test using custom redaction string."""
        redactor = PIIRedactorProcessor(redaction_string="***HIDDEN***")

        event_dict = {"token": "secret_token", "password": "secret_password"}

        result = redactor(None, "info", event_dict)

        assert result["token"] == "***HIDDEN***"
        assert result["password"] == "***HIDDEN***"


class TestLoggingProcessors:
    """Test logging processors."""

    def test_add_trace_id(self):
        """Test adding trace ID to log events."""
        set_trace_id("test_trace_123")

        event_dict = {"message": "test message"}
        result = add_trace_id(None, "info", event_dict)

        assert result["trace_id"] == "test_trace_123"

        clear_trace_id()

    def test_add_trace_id_when_none(self):
        """Test adding trace ID when none is set."""
        clear_trace_id()

        event_dict = {"message": "test message"}
        result = add_trace_id(None, "info", event_dict)

        assert "trace_id" not in result

    def test_add_timestamp(self):
        """Test adding timestamp to log events."""
        event_dict = {"message": "test message"}
        result = add_timestamp(None, "info", event_dict)

        assert "timestamp" in result
        assert isinstance(result["timestamp"], float)

    def test_add_log_level(self):
        """Test adding log level to log events."""
        event_dict = {"message": "test message"}
        result = add_log_level(None, "warning", event_dict)

        assert result["level"] == "WARNING"

    def test_add_logger_name(self):
        """Test adding logger name to log events."""
        mock_logger = MagicMock()
        mock_logger.name = "test.logger"

        event_dict = {"message": "test message"}
        result = add_logger_name(mock_logger, "info", event_dict)

        assert result["logger"] == "test.logger"

    def test_add_logger_name_no_name(self):
        """Test adding logger name when logger has no name."""
        mock_logger = MagicMock()
        del mock_logger.name  # Remove name attribute

        event_dict = {"message": "test message"}
        result = add_logger_name(mock_logger, "info", event_dict)

        assert "logger" not in result


class TestTraceIdManagement:
    """Test trace ID context management."""

    def test_set_get_trace_id(self):
        """Test setting and getting trace ID."""
        test_id = "trace_123"
        set_trace_id(test_id)

        assert get_trace_id() == test_id

        clear_trace_id()

    def test_clear_trace_id(self):
        """Test clearing trace ID."""
        set_trace_id("trace_123")
        clear_trace_id()

        assert get_trace_id() is None

    def test_get_trace_id_when_none(self):
        """Test getting trace ID when none is set."""
        clear_trace_id()

        assert get_trace_id() is None


class TestConfigureStructlog:
    """Test structlog configuration."""

    def test_configure_structlog_with_structlog_available(self):
        """Test configuration when structlog is available."""
        with patch(
            "telnyx_mcp_server.remote.structured_logging.STRUCTLOG_AVAILABLE",
            True,
        ):
            configure_structlog(
                log_level="INFO",
                enable_pii_redaction=True,
                application_insights_key=None,
            )

            # Should call structlog.configure
            structlog_mock.configure.assert_called()

    def test_configure_structlog_without_structlog(self):
        """Test configuration fallback when structlog not available."""
        with patch(
            "telnyx_mcp_server.remote.structured_logging.STRUCTLOG_AVAILABLE",
            False,
        ):
            with patch("logging.basicConfig") as mock_basic_config:
                configure_structlog(
                    log_level="INFO",
                    enable_pii_redaction=True,
                    application_insights_key=None,
                )

                # Should fall back to basic config
                mock_basic_config.assert_called()

    def test_get_logger_with_structlog(self):
        """Test getting logger when structlog is available."""
        with patch(
            "telnyx_mcp_server.remote.structured_logging.STRUCTLOG_AVAILABLE",
            True,
        ):
            get_logger("test.logger")

            # Should call structlog.get_logger
            structlog_mock.get_logger.assert_called_with("test.logger")

    def test_get_logger_without_structlog(self):
        """Test getting logger when structlog is not available."""
        with patch(
            "telnyx_mcp_server.remote.structured_logging.STRUCTLOG_AVAILABLE",
            False,
        ):
            with patch("logging.getLogger") as mock_get_logger:
                get_logger("test.logger")

                # Should fall back to standard logging
                mock_get_logger.assert_called_with("test.logger")


class TestTraceIdMiddleware:
    """Test trace ID middleware functionality."""

    @pytest.mark.asyncio
    async def test_trace_id_middleware_generates_id(self):
        """Test that middleware generates trace ID when none provided."""
        from telnyx_mcp_server.remote.structured_logging import (
            TraceIdMiddleware,
        )

        # Mock app
        mock_app = MagicMock()
        mock_app.return_value = None

        middleware = TraceIdMiddleware(mock_app)

        # Mock scope for HTTP request
        scope = {"type": "http", "headers": []}

        # Mock send function to capture headers
        sent_messages = []

        async def mock_send(message):
            sent_messages.append(message)

        # Mock receive function
        async def mock_receive():
            return {"type": "http.request", "body": b""}

        # Run middleware
        await middleware(scope, mock_receive, mock_send)

        # Should call the wrapped app
        mock_app.assert_called()

    @pytest.mark.asyncio
    async def test_trace_id_middleware_uses_existing_id(self):
        """Test that middleware uses existing trace ID from headers."""
        from telnyx_mcp_server.remote.structured_logging import (
            TraceIdMiddleware,
        )

        # Mock app
        mock_app = MagicMock()
        mock_app.return_value = None

        middleware = TraceIdMiddleware(mock_app)

        # Mock scope with existing trace ID
        scope = {
            "type": "http",
            "headers": [(b"x-trace-id", b"existing_trace_123")],
        }

        # Mock send and receive
        async def mock_send(message):
            pass

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        # Run middleware
        await middleware(scope, mock_receive, mock_send)

        # Should call the wrapped app
        mock_app.assert_called()

    @pytest.mark.asyncio
    async def test_trace_id_middleware_non_http_request(self):
        """Test middleware with non-HTTP request."""
        from telnyx_mcp_server.remote.structured_logging import (
            TraceIdMiddleware,
        )

        # Mock app
        mock_app = MagicMock()
        mock_app.return_value = None

        middleware = TraceIdMiddleware(mock_app)

        # Mock scope for non-HTTP request
        scope = {"type": "websocket"}

        # Mock send and receive
        async def mock_send(message):
            pass

        async def mock_receive():
            return {"type": "websocket.connect"}

        # Run middleware
        await middleware(scope, mock_receive, mock_send)

        # Should call the wrapped app directly
        mock_app.assert_called_with(scope, mock_receive, mock_send)
