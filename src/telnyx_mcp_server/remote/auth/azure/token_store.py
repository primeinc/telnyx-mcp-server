"""Azure Easy Auth Token Store access for user-delegated API calls."""

import logging
from typing import Optional

from fastapi import HTTPException, Request, status
import httpx

from .models import AzureTokenStoreResponse

logger = logging.getLogger(__name__)


class AzureTokenStore:
    """Access the Azure Easy Auth token store for user-delegated tokens.

    Azure App Service Built-in Authentication provides a token store that
    contains the access tokens, refresh tokens, and ID tokens for authenticated
    users. This is accessible via the /.auth/me endpoint when the user's
    session cookie is provided.

    The token store is useful when you need to make API calls on behalf of
    the user (delegated permissions) rather than as the application itself
    (application permissions via Managed Identity).
    """

    @staticmethod
    async def get_user_tokens(
        request: Request,
    ) -> Optional[AzureTokenStoreResponse]:
        """Retrieve user tokens from the Easy Auth token store.

        This makes a server-side request to the /.auth/me endpoint,
        forwarding the user's session cookie to authenticate the request.

        Args:
            request: The FastAPI request containing the user's session cookie

        Returns:
            The token store response containing user tokens, or None if not available

        Raises:
            HTTPException: If the token store request fails
        """
        # Get the session cookie
        session_cookie = request.cookies.get("AppServiceAuthSession")
        if not session_cookie:
            logger.debug("No AppServiceAuthSession cookie found")
            return None

        # Build the token store URL
        # In production, this will be the same domain
        # In local development, you might need to configure this differently
        base_url = str(request.base_url).rstrip("/")
        token_store_url = f"{base_url}/.auth/me"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    token_store_url,
                    cookies={"AppServiceAuthSession": session_cookie},
                    headers={
                        "X-Forwarded-Host": request.headers.get("host", ""),
                        "X-Forwarded-Proto": request.url.scheme,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    if data and isinstance(data, list) and len(data) > 0:
                        # The response is an array, take the first provider's data
                        provider_data = data[0]
                        return AzureTokenStoreResponse(**provider_data)
                    else:
                        logger.debug("Empty token store response")
                        return None
                elif response.status_code == 401:
                    logger.debug(
                        "Token store returned 401 - session may be expired"
                    )
                    return None
                else:
                    logger.error(
                        f"Token store request failed with status {response.status_code}",
                        extra={"response_text": response.text},
                    )
                    return None

        except httpx.RequestError as e:
            logger.error(
                "Failed to connect to token store",
                extra={"error": str(e), "url": token_store_url},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to retrieve user tokens from token store",
            )
        except Exception as e:
            logger.error(
                "Unexpected error accessing token store",
                extra={"error": str(e), "error_type": type(e).__name__},
            )
            return None

    @staticmethod
    async def get_access_token(request: Request) -> Optional[str]:
        """Get the user's access token for downstream API calls.

        This is a convenience method that retrieves just the access token
        from the token store.

        Args:
            request: The FastAPI request containing the user's session cookie

        Returns:
            The access token if available, None otherwise
        """
        token_response = await AzureTokenStore.get_user_tokens(request)
        if token_response:
            return token_response.access_token
        return None

    @staticmethod
    async def get_id_token(request: Request) -> Optional[str]:
        """Get the user's ID token.

        This is a convenience method that retrieves just the ID token
        from the token store.

        Args:
            request: The FastAPI request containing the user's session cookie

        Returns:
            The ID token if available, None otherwise
        """
        token_response = await AzureTokenStore.get_user_tokens(request)
        if token_response:
            return token_response.id_token
        return None

    @staticmethod
    def is_token_store_available() -> bool:
        """Check if the token store is likely to be available.

        This checks environment variables to determine if we're running
        in an Azure App Service environment with Easy Auth enabled.

        Returns:
            True if token store should be available, False otherwise
        """
        import os

        # Check for Azure App Service environment variables
        website_instance_id = os.getenv("WEBSITE_INSTANCE_ID")
        website_auth_enabled = (
            os.getenv("WEBSITE_AUTH_ENABLED", "false").lower() == "true"
        )

        return bool(website_instance_id and website_auth_enabled)
