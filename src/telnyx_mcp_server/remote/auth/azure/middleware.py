"""Azure Easy Auth middleware for FastAPI."""

import base64
import json
import logging
from typing import Optional

from fastapi import Request, Response
import jwt
from jwt import PyJWKClient
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)

from .models import AzureClientPrincipal

logger = logging.getLogger(__name__)


class AzureEasyAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to parse Azure Easy Auth headers and inject user information.

    This middleware supports two authentication methods:

    1. Azure App Service Built-in Authentication (Easy Auth) headers:
       - X-MS-CLIENT-PRINCIPAL: Base64-encoded JSON with user claims
       - X-MS-CLIENT-PRINCIPAL-ID: User's unique identifier
       - X-MS-CLIENT-PRINCIPAL-NAME: User's display name
       - X-MS-CLIENT-PRINCIPAL-IDP: Identity provider used
       - X-MS-TOKEN-AAD-ACCESS-TOKEN: Azure AD access token (if configured)
       - X-MS-TOKEN-AAD-ID-TOKEN: Azure AD ID token (if configured)

    2. OAuth Bearer tokens in Authorization header:
       - Authorization: Bearer <token>
       - Validates tokens against Azure AD
       - Extracts user claims from validated tokens

    This middleware parses these headers and makes the user information available
    via request.state.user as an AzureClientPrincipal object.
    """

    def __init__(self, app):
        super().__init__(app)
        # Cache for JWKS client - initialized on first use
        self._jwks_client = None
        self._tenant_id = None

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

        # First, check for Easy Auth headers
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

        # If no Easy Auth headers, check for Bearer token
        if not request.state.user:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]  # Remove "Bearer " prefix
                logger.debug("Found Bearer token in Authorization header")

                # Validate the Bearer token
                user = await self.validate_bearer_token(token)
                if user:
                    request.state.user = user
                    # Store the access token for downstream use
                    request.state.azure_tokens["access_token"] = token

                    logger.info(
                        "Bearer token authenticated successfully",
                        extra={
                            "auth_type": "bearer",
                            "has_email": user.email is not None,
                            "has_name": user.name is not None,
                        },
                    )
                else:
                    logger.warning("Bearer token validation failed")

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

    async def validate_bearer_token(
        self, token: str
    ) -> Optional[AzureClientPrincipal]:
        """Validate an OAuth Bearer token and extract user information.

        Args:
            token: The Bearer token to validate

        Returns:
            AzureClientPrincipal if token is valid, None otherwise
        """
        try:
            # Get tenant ID from environment or config
            import os

            if not self._tenant_id:
                self._tenant_id = os.getenv("AZURE_TENANT_ID", "common")

            # Initialize JWKS client if needed
            if not self._jwks_client:
                jwks_url = f"https://login.microsoftonline.com/{self._tenant_id}/discovery/v2.0/keys"
                self._jwks_client = PyJWKClient(jwks_url)

            # Get the signing key from Azure AD
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)

            # Decode and validate the token
            # Note: We're validating against common Azure AD audiences
            client_id = os.getenv("AZURE_CLIENT_ID")
            audiences = [
                client_id,  # App-specific audience
                f"api://{client_id}",  # API audience format
                "00000003-0000-0000-c000-000000000000",  # Microsoft Graph
            ]

            decoded_token = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=audiences,
                issuer=[
                    f"https://login.microsoftonline.com/{self._tenant_id}/v2.0",
                    f"https://sts.windows.net/{self._tenant_id}/",
                ],
                options={
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                },
            )

            # Extract user information from token claims
            # Map JWT claims to AzureClientPrincipal format
            claims = []

            # Standard claims mapping
            claim_mappings = {
                "oid": "http://schemas.microsoft.com/identity/claims/objectidentifier",
                "tid": "http://schemas.microsoft.com/identity/claims/tenantid",
                "name": "name",
                "preferred_username": "preferred_username",
                "email": "email",
                "upn": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
                "unique_name": "unique_name",
                "sub": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
            }

            for jwt_claim, principal_claim in claim_mappings.items():
                if jwt_claim in decoded_token:
                    claims.append(
                        {
                            "typ": principal_claim,
                            "val": decoded_token[jwt_claim],
                        }
                    )

            # Add roles if present
            roles = decoded_token.get("roles", [])
            if isinstance(roles, list):
                for role in roles:
                    claims.append({"typ": "roles", "val": role})

            # Create principal data matching Easy Auth format
            principal_data = {
                "auth_typ": "aad",  # Azure AD
                "claims": claims,
                "name_typ": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                "role_typ": "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
            }

            # Create and return AzureClientPrincipal
            return AzureClientPrincipal(**principal_data)

        except jwt.ExpiredSignatureError:
            logger.warning("Bearer token is expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid Bearer token: {e}")
            return None
        except Exception as e:
            logger.error(f"Error validating Bearer token: {e}", exc_info=True)
            return None
