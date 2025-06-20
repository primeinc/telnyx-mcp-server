"""Azure Easy Auth middleware for FastAPI."""

import base64
import json
import logging
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)

from .models import AzureClientPrincipal

logger = logging.getLogger(__name__)


class AzureEasyAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to parse Azure Easy Auth headers and inject user information.

    Azure App Service Built-in Authentication (Easy Auth) injects several headers
    into requests after successful authentication:
    - X-MS-CLIENT-PRINCIPAL: Base64-encoded JSON with user claims
    - X-MS-CLIENT-PRINCIPAL-ID: User's unique identifier
    - X-MS-CLIENT-PRINCIPAL-NAME: User's display name
    - X-MS-CLIENT-PRINCIPAL-IDP: Identity provider used
    - X-MS-TOKEN-AAD-ACCESS-TOKEN: Azure AD access token (if configured)
    - X-MS-TOKEN-AAD-ID-TOKEN: Azure AD ID token (if configured)

    This middleware parses these headers and makes the user information available
    via request.state.user as an AzureClientPrincipal object.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process the request and extract Azure Easy Auth information.

        Args:
            request: The incoming request
            call_next: The next middleware or endpoint handler

        Returns:
            The response from the next handler
        """
        # Initialize user state
        request.state.user = None
        request.state.azure_tokens = {}

        # Extract the principal header
        principal_header = request.headers.get("X-MS-CLIENT-PRINCIPAL")

        if principal_header:
            try:
                # Decode the base64-encoded header
                decoded_principal = base64.b64decode(principal_header).decode(
                    "utf-8"
                )
                principal_json = json.loads(decoded_principal)

                # Create AzureClientPrincipal instance
                request.state.user = AzureClientPrincipal(**principal_json)

                # Log successful authentication (without PII)
                logger.debug(
                    "Azure Easy Auth user authenticated",
                    extra={
                        "auth_type": request.state.user.auth_typ,
                        "has_email": request.state.user.email is not None,
                        "has_name": request.state.user.name is not None,
                        "roles_count": len(request.state.user.roles),
                    },
                )

                # Extract additional Azure tokens if available
                access_token = request.headers.get(
                    "X-MS-TOKEN-AAD-ACCESS-TOKEN"
                )
                id_token = request.headers.get("X-MS-TOKEN-AAD-ID-TOKEN")

                if access_token:
                    request.state.azure_tokens["access_token"] = access_token
                if id_token:
                    request.state.azure_tokens["id_token"] = id_token

            except json.JSONDecodeError as e:
                logger.error(
                    "Failed to decode X-MS-CLIENT-PRINCIPAL header",
                    extra={"error": str(e)},
                )
            except Exception as e:
                logger.error(
                    "Error parsing Azure Easy Auth headers",
                    extra={"error": str(e), "error_type": type(e).__name__},
                )

        # Process the request
        response = await call_next(request)

        return response

    @staticmethod
    def get_user(request: Request) -> Optional[AzureClientPrincipal]:
        """Get the authenticated user from the request.

        Args:
            request: The FastAPI request object

        Returns:
            The AzureClientPrincipal if authenticated, None otherwise
        """
        return getattr(request.state, "user", None)

    @staticmethod
    def get_azure_tokens(request: Request) -> dict:
        """Get Azure tokens from the request.

        Args:
            request: The FastAPI request object

        Returns:
            Dictionary containing available Azure tokens
        """
        return getattr(request.state, "azure_tokens", {})
