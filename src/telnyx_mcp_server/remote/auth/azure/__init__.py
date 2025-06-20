"""Azure Easy Auth (Built-in Authentication) module for Telnyx MCP Server."""

from .dependencies import get_current_user, require_user
from .middleware import AzureEasyAuthMiddleware
from .models import AzureClaim, AzureClientPrincipal

__all__ = [
    "AzureEasyAuthMiddleware",
    "AzureClientPrincipal",
    "AzureClaim",
    "require_user",
    "get_current_user",
]
