"""Azure AD ID token validation for critical operations."""

import logging
import os
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
import httpx
import jwt
from jwt import PyJWKClient

logger = logging.getLogger(__name__)


class AzureTokenValidator:
    """Validate Azure AD ID tokens for enhanced security.

    While Azure Easy Auth validates tokens at the platform level,
    this validator provides an additional layer of security for
    critical operations by cryptographically verifying ID tokens
    against Azure AD's public keys.

    This is recommended for:
    - Financial transactions
    - Administrative operations
    - Sensitive data access
    - Any operation where you need absolute certainty of token validity
    """

    def __init__(self, tenant_id: Optional[str] = None):
        """Initialize the token validator.

        Args:
            tenant_id: Azure AD tenant ID. If not provided, uses environment variable.
        """
        self.tenant_id = tenant_id or os.getenv("AZURE_TENANT_ID")
        if not self.tenant_id:
            raise ValueError(
                "AZURE_TENANT_ID must be provided or set in environment"
            )

        # Azure AD OIDC discovery endpoint
        self.discovery_url = f"https://login.microsoftonline.com/{self.tenant_id}/v2.0/.well-known/openid-configuration"
        self._jwks_client = None
        self._issuer = None

    async def _get_discovery_document(self) -> Dict[str, Any]:
        """Fetch the OpenID Connect discovery document.

        Returns:
            The discovery document containing issuer and JWKS URI
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.discovery_url)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(
                "Failed to fetch OIDC discovery document",
                extra={"error": str(e), "url": self.discovery_url},
            )
            raise

    async def _ensure_jwks_client(self):
        """Ensure the JWKS client is initialized."""
        if self._jwks_client is None:
            discovery = await self._get_discovery_document()
            self._issuer = discovery["issuer"]
            jwks_uri = discovery["jwks_uri"]

            # Initialize the JWKS client with the Azure AD keys endpoint
            self._jwks_client = PyJWKClient(jwks_uri)
            logger.info(
                "Initialized JWKS client",
                extra={"issuer": self._issuer, "jwks_uri": jwks_uri},
            )

    async def validate_id_token(
        self,
        id_token: str,
        expected_audience: Optional[str] = None,
        validate_nonce: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate an Azure AD ID token.

        Args:
            id_token: The ID token to validate
            expected_audience: Expected audience (client ID). If not provided,
                             uses AZURE_CLIENT_ID from environment
            validate_nonce: Optional nonce to validate against

        Returns:
            The decoded and validated token claims

        Raises:
            HTTPException: If validation fails
        """
        await self._ensure_jwks_client()

        if not expected_audience:
            expected_audience = os.getenv("AZURE_CLIENT_ID")
            if not expected_audience:
                raise ValueError(
                    "Expected audience must be provided or AZURE_CLIENT_ID must be set"
                )

        try:
            # Get the signing key from Azure AD
            signing_key = self._jwks_client.get_signing_key_from_jwt(id_token)

            # Decode and validate the token
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=expected_audience,
                issuer=self._issuer,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "require": ["exp", "iat", "nbf", "iss", "aud"],
                },
            )

            # Additional validation for nonce if provided
            if validate_nonce:
                token_nonce = claims.get("nonce")
                if token_nonce != validate_nonce:
                    raise jwt.InvalidTokenError("Nonce validation failed")

            logger.info(
                "ID token validated successfully",
                extra={
                    "subject": claims.get("sub"),
                    "issuer": claims.get("iss"),
                    "audience": claims.get("aud"),
                },
            )

            return claims

        except jwt.ExpiredSignatureError:
            logger.warning("ID token has expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ID token has expired",
            )
        except jwt.InvalidAudienceError:
            logger.warning("ID token has invalid audience")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ID token audience validation failed",
            )
        except jwt.InvalidIssuerError:
            logger.warning("ID token has invalid issuer")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ID token issuer validation failed",
            )
        except jwt.InvalidTokenError as e:
            logger.warning(f"ID token validation failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"ID token validation failed: {str(e)}",
            )
        except Exception as e:
            logger.error(
                "Unexpected error during ID token validation",
                extra={"error": str(e), "error_type": type(e).__name__},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Token validation error",
            )

    async def validate_access_token_claims(
        self, access_token: str, required_scopes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Validate access token claims without signature verification.

        Note: Access tokens from Azure AD are not meant to be validated
        by the client application. They should be validated by the resource
        server (API) they're intended for. This method only decodes and
        checks claims without cryptographic validation.

        Args:
            access_token: The access token to check
            required_scopes: Optional list of required scopes

        Returns:
            The decoded token claims (unverified)
        """
        try:
            # Decode without verification
            claims = jwt.decode(
                access_token, options={"verify_signature": False}
            )

            # Check token version (Azure AD v2.0 tokens have ver=2.0)
            version = claims.get("ver")
            if version not in ["1.0", "2.0"]:
                raise ValueError(f"Unexpected token version: {version}")

            # Check scopes if required
            if required_scopes:
                token_scopes = claims.get("scp", "").split(" ")
                missing_scopes = [
                    s for s in required_scopes if s not in token_scopes
                ]
                if missing_scopes:
                    raise ValueError(
                        f"Missing required scopes: {missing_scopes}"
                    )

            return claims

        except Exception as e:
            logger.error(
                "Failed to decode access token", extra={"error": str(e)}
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token",
            )


# Global validator instance
_validator = None


def get_token_validator() -> AzureTokenValidator:
    """Get the global token validator instance.

    Returns:
        The AzureTokenValidator instance
    """
    global _validator
    if _validator is None:
        _validator = AzureTokenValidator()
    return _validator
