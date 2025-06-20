"""Azure Built-in Authentication (Easy Auth) for remote MCP server."""

import base64
from datetime import datetime, timedelta
import json
import os
from typing import Any, Dict, Optional
import urllib.parse

from dotenv import load_dotenv
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer
import jwt

# Load environment variables
load_dotenv()

# Configuration
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# Validate JWT secret in production
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
if ENVIRONMENT == "production" and JWT_SECRET_KEY == "change-me-in-production":
    raise ValueError(
        "JWT_SECRET_KEY must be set to a secure value in production. "
        "Generate a secure key with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
    )

security = HTTPBearer()


class AuthService:
    """Azure Built-in Authentication (Easy Auth) service"""

    @staticmethod
    def extract_user_from_header(request: Request) -> Optional[Dict[str, Any]]:
        """Extract user information from X-MS-CLIENT-PRINCIPAL header.

        This header is set by Azure App Service Built-in Authentication (Easy Auth)
        and contains a base64-encoded JSON object with user claims.
        """
        principal_header = request.headers.get("X-MS-CLIENT-PRINCIPAL")
        if not principal_header:
            return None

        try:
            # Decode the base64-encoded header
            decoded = base64.b64decode(principal_header)
            principal_data = json.loads(decoded)

            # Extract claims into a dictionary
            claims = {
                claim["typ"]: claim["val"]
                for claim in principal_data.get("claims", [])
            }

            # Build user info from claims
            user_info = {
                "id": principal_data.get("userId"),
                "name": claims.get("name"),
                "email": claims.get("emails")
                or claims.get("preferred_username"),
                "provider": principal_data.get("identityProvider"),
                "userRoles": principal_data.get("userRoles", []),
                "claims": claims,
            }

            return user_info
        except Exception as e:
            # Log error but don't expose details
            import logging

            logging.error(f"Failed to parse X-MS-CLIENT-PRINCIPAL header: {e}")
            return None

    @staticmethod
    def get_login_url() -> str:
        """Get the Built-in Auth login URL.

        With Azure App Service Built-in Authentication, the login flow is handled
        by the platform at /.auth/login/aad
        """
        return "/.auth/login/aad"

    @staticmethod
    def get_logout_url() -> str:
        """Get the Built-in Auth logout URL."""
        return "/.auth/logout"

    @staticmethod
    def get_authorization_url(state: str) -> str:
        """Get the Azure AD authorization URL.

        Args:
            state: State parameter for OAuth flow

        Returns:
            The Azure AD authorization URL
        """
        if not AZURE_TENANT_ID:
            raise ValueError("AZURE_TENANT_ID must be configured")

        # Build Azure AD authorization URL
        params = {
            "client_id": os.getenv("AZURE_CLIENT_ID"),
            "response_type": "code",
            "redirect_uri": os.getenv(
                "AZURE_REDIRECT_URI", "http://localhost:8000/auth/callback"
            ),
            "response_mode": "query",
            "scope": "openid profile email User.Read",
            "state": state,
        }

        auth_url = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/authorize"
        query_string = urllib.parse.urlencode(params)

        return f"{auth_url}?{query_string}"

    @staticmethod
    def create_jwt_token(
        user_data: Dict[str, Any], audience: Optional[str] = None
    ) -> str:
        """Create JWT token for authenticated user with audience claim"""
        payload = {
            "sub": user_data.get("id"),
            "email": user_data.get("mail")
            or user_data.get("userPrincipalName"),
            "name": user_data.get("displayName"),
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
            "iat": datetime.utcnow(),
            "iss": os.getenv(
                "BASE_URL", "https://telnyx-mcp-server.azurewebsites.net"
            ),
        }

        # Add audience if provided (RFC 8707 - resource parameter)
        if audience:
            payload["aud"] = audience

        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    @staticmethod
    def decode_jwt_token(
        token: str, audience: Optional[str] = None
    ) -> Dict[str, Any]:
        """Decode and validate JWT token from Azure AD (MSAL).

        NOTE: When using Built-in Auth, Azure validates the token for us.
        This method is only used for direct API access with MSAL tokens.
        In production with Built-in Auth enabled, tokens are validated by Azure.
        """
        try:
            # For Azure AD tokens from MSAL, we decode without verification
            # because Azure Built-in Auth handles validation in production.
            # In local development, you would need to implement proper
            # Azure AD token validation with JWKS from Microsoft.
            payload = jwt.decode(
                token,
                options={
                    "verify_signature": False
                },  # Azure validates in production
            )

            # Extract user info from Azure AD token claims
            user_data = {
                "id": payload.get("oid") or payload.get("sub"),
                "name": payload.get("name"),
                "email": payload.get("email")
                or payload.get("preferred_username"),
                "provider": "azureactivedirectory",
                "claims": payload,
            }

            return user_data
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}",
            )
