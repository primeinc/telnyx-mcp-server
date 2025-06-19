"""Azure OAuth authentication for remote MCP server."""

import base64
from datetime import datetime, timedelta
import os
import time
from typing import Any, Dict, Optional
import uuid

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
import jwt

# Load environment variables
load_dotenv()

# Configuration
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_REDIRECT_URI = os.getenv(
    "AZURE_REDIRECT_URI", "http://localhost:8000/auth/callback"
)
# Certificate configuration
AZURE_CERTIFICATE_THUMBPRINT = os.getenv("AZURE_CERTIFICATE_THUMBPRINT")
AZURE_KEY_VAULT_NAME = os.getenv("AZURE_KEY_VAULT_NAME")
AZURE_CERTIFICATE_NAME = os.getenv("AZURE_CERTIFICATE_NAME")
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

# Azure OAuth URLs
AZURE_AUTH_URL = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/authorize"
AZURE_TOKEN_URL = (
    f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/token"
)
AZURE_GRAPH_URL = "https://graph.microsoft.com/v1.0/me"

# OAuth scopes
SCOPES = ["openid", "profile", "email", "User.Read"]

security = HTTPBearer()


class AuthService:
    """Azure OAuth authentication service"""

    @staticmethod
    def get_authorization_url(state: str = None) -> str:
        """Generate Azure OAuth authorization URL"""
        if not all([AZURE_CLIENT_ID, AZURE_TENANT_ID]):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OAuth configuration missing. Please set AZURE_CLIENT_ID and AZURE_TENANT_ID.",
            )

        params = {
            "client_id": AZURE_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": AZURE_REDIRECT_URI,
            "scope": " ".join(SCOPES),
            "response_mode": "query",
        }

        if state:
            params["state"] = state

        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{AZURE_AUTH_URL}?{query_string}"

    @staticmethod
    def _create_client_assertion() -> str:
        """Create a client assertion JWT for certificate authentication"""
        if not all([AZURE_KEY_VAULT_NAME, AZURE_CERTIFICATE_NAME]):
            return None

        try:
            # Use managed identity to access Key Vault
            credential = DefaultAzureCredential()

            # Get the certificate from Key Vault as a secret (contains both cert and private key)
            key_vault_url = f"https://{AZURE_KEY_VAULT_NAME}.vault.azure.net/"
            secret_client = SecretClient(
                vault_url=key_vault_url, credential=credential
            )

            # Certificate stored as secret with same name
            certificate_secret = secret_client.get_secret(
                AZURE_CERTIFICATE_NAME
            )
            cert_bytes = base64.b64decode(certificate_secret.value)

            # Load the certificate and private key from the PFX/PKCS12 data
            # Azure Key Vault certificates have no password
            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                cert_bytes, None
            )

            # Create the JWT claims
            now = int(time.time())
            claims = {
                "aud": AZURE_TOKEN_URL,
                "iss": AZURE_CLIENT_ID,
                "sub": AZURE_CLIENT_ID,
                "jti": str(uuid.uuid4()),
                "iat": now,
                "exp": now + 600,  # 10 minutes
                "nbf": now,
            }

            # Get the certificate thumbprint (x5t is base64url encoded SHA1 thumbprint)
            import hashlib

            cert_der = certificate.public_bytes(
                encoding=serialization.Encoding.DER
            )
            sha1_hash = hashlib.sha1(cert_der).digest()
            x5t = base64.urlsafe_b64encode(sha1_hash).decode().rstrip("=")

            # Create the JWT with RS256 algorithm and x5t header
            headers = {"x5t": x5t}
            client_assertion = jwt.encode(
                claims, private_key, algorithm="RS256", headers=headers
            )

            return client_assertion
        except Exception as e:
            # Log but don't fail - fall back to secret
            import logging

            logging.warning(
                f"Failed to create client assertion from Key Vault: {e}"
            )
            return None

    @staticmethod
    async def exchange_code_for_token(code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token using certificate or secret"""

        # Base data for token exchange
        data = {
            "client_id": AZURE_CLIENT_ID,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": AZURE_REDIRECT_URI,
            "scope": " ".join(SCOPES),
        }

        # Try certificate authentication first
        client_assertion = AuthService._create_client_assertion()
        if client_assertion:
            # Use certificate authentication
            data["client_assertion_type"] = (
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            )
            data["client_assertion"] = client_assertion
        elif AZURE_CLIENT_SECRET:
            # Fall back to client secret
            data["client_secret"] = AZURE_CLIENT_SECRET
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OAuth configuration missing. Please set either AZURE_CLIENT_SECRET or configure certificate authentication.",
            )

        async with httpx.AsyncClient() as client:
            response = await client.post(AZURE_TOKEN_URL, data=data)

            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Token exchange failed: {response.text}",
                )

            return response.json()

    @staticmethod
    async def get_user_info(access_token: str) -> Dict[str, Any]:
        """Get user information from Microsoft Graph API"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(AZURE_GRAPH_URL, headers=headers)

            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to get user info: {response.text}",
                )

            return response.json()

    @staticmethod
    def create_jwt_token(user_data: Dict[str, Any]) -> str:
        """Create JWT token for authenticated user"""
        payload = {
            "sub": user_data.get("id"),
            "email": user_data.get("mail")
            or user_data.get("userPrincipalName"),
            "name": user_data.get("displayName"),
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
            "iat": datetime.utcnow(),
        }

        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    @staticmethod
    def decode_jwt_token(
        token: str, audience: Optional[str] = None
    ) -> Dict[str, Any]:
        """Decode and validate JWT token with strict validation per RFC 8725"""
        try:
            # Decode with algorithm whitelisting (never trust alg header)
            # Only allow HS256 which we use for signing
            payload = jwt.decode(
                token,
                JWT_SECRET_KEY,
                algorithms=[JWT_ALGORITHM],
                options={"verify_signature": True, "verify_exp": True},
            )

            # Additional claim validation per RFC 8725
            # Note: PyJWT handles exp validation automatically when verify_exp=True

            # For MCP server, we don't use issuer/audience claims currently
            # but this shows how to validate them if needed:
            # if audience and payload.get("aud") != audience:
            #     raise jwt.InvalidAudienceError("Invalid audience")

            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
            )
        except jwt.InvalidAudienceError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token audience",
            )
        except jwt.InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}",
            )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """Get current user from JWT token"""
    token = credentials.credentials
    user_data = AuthService.decode_jwt_token(token)
    return user_data
