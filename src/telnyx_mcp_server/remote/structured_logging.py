"""Structured logging configuration with PII redaction for MCP server."""

from contextvars import ContextVar
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Union
import uuid

try:
    import structlog
    from structlog.processors import JSONRenderer

    STRUCTLOG_AVAILABLE = True
except ImportError:
    structlog = None
    JSONRenderer = None
    STRUCTLOG_AVAILABLE = False


# Context variable for trace ID tracking
trace_id_context: ContextVar[Optional[str]] = ContextVar(
    "trace_id", default=None
)


class PIIRedactorProcessor:
    """Processor to redact PII and sensitive information from log records."""

    # Patterns for sensitive data
    SENSITIVE_PATTERNS = {
        "token": re.compile(
            r'(bearer\s+|token["\s]*[:=]\s*["\']?)([a-zA-Z0-9_\-\.]{20,})',
            re.IGNORECASE,
        ),
        "authorization": re.compile(
            r'(authorization["\s]*[:=]\s*["\']?)([a-zA-Z0-9_\-\.\/\+]{20,})',
            re.IGNORECASE,
        ),
        "api_key": re.compile(
            r'(api[_\s]*key["\s]*[:=]\s*["\']?)([a-zA-Z0-9_\-]{20,})',
            re.IGNORECASE,
        ),
        "password": re.compile(
            r'(password["\s]*[:=]\s*["\']?)([^"\s]{3,})', re.IGNORECASE
        ),
        "secret": re.compile(
            r'(secret["\s]*[:=]\s*["\']?)([a-zA-Z0-9_\-]{10,})', re.IGNORECASE
        ),
        "email": re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
        ),
        "phone": re.compile(
            r"(\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})"
        ),
        "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
        "ssn": re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b"),
    }

    # Keys that should be redacted entirely
    SENSITIVE_KEYS = {
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "jwt_token",
        "authorization",
        "auth",
        "bearer",
        "api_key",
        "apikey",
        "key",
        "password",
        "passwd",
        "pwd",
        "secret",
        "client_secret",
        "user_data",
        "personal_info",
        "pii",
        "email",
        "mail",
        "phone",
        "telephone",
        "mobile",
        "ssn",
        "social_security",
        "credit_card",
        "cc",
        "card_number",
        "account_number",
    }

    def __init__(self, redaction_string: str = "[REDACTED]"):
        """Initialize the PII redactor.

        Args:
            redaction_string: String to replace sensitive data with
        """
        self.redaction_string = redaction_string

    def __call__(
        self, logger: Any, method_name: str, event_dict: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process the event dictionary to redact sensitive information.

        Args:
            logger: The logger instance
            method_name: The log method name (info, error, etc.)
            event_dict: The event dictionary to process

        Returns:
            The processed event dictionary with redacted PII
        """
        return self._redact_dict(event_dict)

    def _redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively redact sensitive data from a dictionary."""
        redacted = {}

        for key, value in data.items():
            redacted_key = key.lower()

            # Check if key itself is sensitive
            if any(
                sensitive_key in redacted_key
                for sensitive_key in self.SENSITIVE_KEYS
            ):
                redacted[key] = self.redaction_string
                continue

            # Process value based on type
            if isinstance(value, dict):
                redacted[key] = self._redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = self._redact_list(value)
            elif isinstance(value, str):
                redacted[key] = self._redact_string(value)
            else:
                redacted[key] = value

        return redacted

    def _redact_list(self, data: List[Any]) -> List[Any]:
        """Recursively redact sensitive data from a list."""
        redacted = []

        for item in data:
            if isinstance(item, dict):
                redacted.append(self._redact_dict(item))
            elif isinstance(item, list):
                redacted.append(self._redact_list(item))
            elif isinstance(item, str):
                redacted.append(self._redact_string(item))
            else:
                redacted.append(item)

        return redacted

    def _redact_string(self, text: str) -> str:
        """Redact sensitive patterns from a string."""
        if not isinstance(text, str):
            return text

        redacted_text = text

        # Apply each pattern
        for pattern_name, pattern in self.SENSITIVE_PATTERNS.items():
            if pattern_name in [
                "token",
                "authorization",
                "api_key",
                "password",
                "secret",
            ]:
                # For tokens and keys, keep the prefix but redact the value
                redacted_text = pattern.sub(
                    r"\1" + self.redaction_string, redacted_text
                )
            else:
                # For other patterns like email, phone, redact entirely
                redacted_text = pattern.sub(
                    self.redaction_string, redacted_text
                )

        return redacted_text


def add_trace_id(
    logger: Any, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Add trace ID to log events."""
    trace_id = trace_id_context.get()
    if trace_id:
        event_dict["trace_id"] = trace_id
    return event_dict


def add_timestamp(
    logger: Any, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Add timestamp to log events."""
    event_dict["timestamp"] = time.time()
    return event_dict


def add_log_level(
    logger: Any, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Add log level to log events."""
    event_dict["level"] = method_name.upper()
    return event_dict


def add_logger_name(
    logger: Any, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Add logger name to log events."""
    if hasattr(logger, "name"):
        event_dict["logger"] = logger.name
    return event_dict


class TraceIdMiddleware:
    """Middleware to add trace IDs to requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Generate or extract trace ID
            headers = dict(scope.get("headers", []))
            trace_id = None

            # Look for existing trace ID in headers
            for name, value in headers.items():
                if name.decode().lower() in [
                    "x-trace-id",
                    "x-request-id",
                    "mcp-session-id",
                ]:
                    trace_id = value.decode()
                    break

            # Generate new trace ID if not found
            if not trace_id:
                trace_id = str(uuid.uuid4())

            # Set in context
            trace_id_context.set(trace_id)

            # Add to response headers
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers = message.get("headers", [])
                    headers.append([b"x-trace-id", trace_id.encode()])
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)


def configure_structlog(
    log_level: str = "INFO",
    enable_pii_redaction: bool = True,
    application_insights_key: Optional[str] = None,
) -> None:
    """Configure structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        enable_pii_redaction: Whether to enable PII redaction
        application_insights_key: Azure Application Insights instrumentation key
    """
    if not STRUCTLOG_AVAILABLE:
        # Fallback to standard logging if structlog not available
        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.INFO),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        return

    # Configure processors
    processors = [
        add_timestamp,
        add_log_level,
        add_logger_name,
        add_trace_id,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
    ]

    # Add PII redaction if enabled
    if enable_pii_redaction:
        processors.append(PIIRedactorProcessor())

    # Add JSON renderer for production
    environment = os.getenv("ENVIRONMENT", "development")
    if environment == "production":
        processors.append(JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(message)s",
    )

    # Configure Application Insights if key provided
    if application_insights_key:
        try:
            from opencensus.ext.azure.log_exporter import AzureLogHandler

            azure_handler = AzureLogHandler(
                connection_string=f"InstrumentationKey={application_insights_key}"
            )
            logging.getLogger().addHandler(azure_handler)
        except ImportError:
            logging.warning(
                "Application Insights requested but opencensus-ext-azure not available"
            )


def get_logger(name: str) -> Union["structlog.BoundLogger", logging.Logger]:
    """Get a configured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    if STRUCTLOG_AVAILABLE:
        return structlog.get_logger(name)
    else:
        return logging.getLogger(name)


def set_trace_id(trace_id: str) -> None:
    """Set the trace ID for the current context.

    Args:
        trace_id: The trace ID to set
    """
    trace_id_context.set(trace_id)


def get_trace_id() -> Optional[str]:
    """Get the current trace ID.

    Returns:
        The current trace ID or None if not set
    """
    return trace_id_context.get()


def clear_trace_id() -> None:
    """Clear the trace ID for the current context."""
    trace_id_context.set(None)
