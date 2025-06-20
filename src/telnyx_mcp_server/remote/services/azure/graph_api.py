"""Microsoft Graph API service for user and application operations."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import Request
import httpx

from ...auth.azure.managed_identity import get_managed_identity
from ...auth.azure.token_store import AzureTokenStore

logger = logging.getLogger(__name__)


class MicrosoftGraphService:
    """Service for interacting with Microsoft Graph API.

    This service supports both:
    1. Application-level calls using Managed Identity
    2. User-delegated calls using tokens from Easy Auth token store

    Example usage:
        # Application-level call
        graph = MicrosoftGraphService()
        users = await graph.list_users()

        # User-delegated call
        profile = await graph.get_user_profile(request)
    """

    def __init__(self, api_version: str = "v1.0"):
        """Initialize the Graph API service.

        Args:
            api_version: The Graph API version to use (default: v1.0)
        """
        self.base_url = f"https://graph.microsoft.com/{api_version}"
        self.api_version = api_version
        self._app_token = None

    async def _get_app_token(self) -> Optional[str]:
        """Get an application token using Managed Identity.

        Returns:
            The access token for MS Graph if successful, None otherwise
        """
        if self._app_token is None:
            identity = get_managed_identity()
            self._app_token = await identity.get_graph_token()
        return self._app_token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        token: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make a request to the Graph API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: The API endpoint (without base URL)
            token: The access token
            json_data: Optional JSON data for POST/PUT requests
            params: Optional query parameters

        Returns:
            The response data if successful, None otherwise
        """
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    params=params,
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 204:
                    # No content (successful DELETE, etc.)
                    return {}
                else:
                    logger.error(
                        f"Graph API request failed",
                        extra={
                            "status_code": response.status_code,
                            "endpoint": endpoint,
                            "error": response.text,
                        },
                    )
                    return None

        except Exception as e:
            logger.error(
                f"Error calling Graph API",
                extra={
                    "endpoint": endpoint,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            return None

    # User-delegated operations (using user's token from Easy Auth)

    async def get_user_profile(
        self, request: Request
    ) -> Optional[Dict[str, Any]]:
        """Get the current user's profile.

        This is a user-delegated call that uses the user's token.

        Args:
            request: The FastAPI request containing the user's session

        Returns:
            The user's profile data if successful, None otherwise
        """
        token = await AzureTokenStore.get_access_token(request)
        if not token:
            logger.warning("No user access token available for Graph API")
            return None

        return await self._make_request("GET", "/me", token)

    async def get_user_photo(self, request: Request) -> Optional[bytes]:
        """Get the current user's profile photo.

        Args:
            request: The FastAPI request containing the user's session

        Returns:
            The photo bytes if successful, None otherwise
        """
        token = await AzureTokenStore.get_access_token(request)
        if not token:
            return None

        url = f"{self.base_url}/me/photo/$value"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    return response.content
                return None
        except Exception as e:
            logger.error(f"Failed to get user photo: {e}")
            return None

    async def list_user_groups(
        self, request: Request
    ) -> Optional[List[Dict[str, Any]]]:
        """List the groups the current user is a member of.

        Args:
            request: The FastAPI request containing the user's session

        Returns:
            List of groups if successful, None otherwise
        """
        token = await AzureTokenStore.get_access_token(request)
        if not token:
            return None

        result = await self._make_request("GET", "/me/memberOf", token)
        if result:
            return result.get("value", [])
        return None

    async def send_mail(
        self,
        request: Request,
        to_recipients: List[str],
        subject: str,
        body: str,
        body_type: str = "text",
    ) -> bool:
        """Send an email on behalf of the user.

        Args:
            request: The FastAPI request containing the user's session
            to_recipients: List of email addresses
            subject: Email subject
            body: Email body
            body_type: Body content type ("text" or "html")

        Returns:
            True if sent successfully, False otherwise
        """
        token = await AzureTokenStore.get_access_token(request)
        if not token:
            return False

        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": body_type, "content": body},
                "toRecipients": [
                    {"emailAddress": {"address": email}}
                    for email in to_recipients
                ],
            }
        }

        result = await self._make_request(
            "POST", "/me/sendMail", token, json_data=message
        )
        return result is not None

    # Application-level operations (using Managed Identity)

    async def list_users(
        self,
        select: Optional[List[str]] = None,
        filter_query: Optional[str] = None,
        top: int = 100,
    ) -> Optional[List[Dict[str, Any]]]:
        """List users in the directory (requires application permissions).

        Args:
            select: Fields to include in response
            filter_query: OData filter query
            top: Maximum number of results

        Returns:
            List of users if successful, None otherwise
        """
        token = await self._get_app_token()
        if not token:
            logger.error("Failed to get application token for Graph API")
            return None

        params = {"$top": top}
        if select:
            params["$select"] = ",".join(select)
        if filter_query:
            params["$filter"] = filter_query

        result = await self._make_request(
            "GET", "/users", token, params=params
        )
        if result:
            return result.get("value", [])
        return None

    async def get_user_by_id(
        self, user_id: str, select: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """Get a specific user by ID (requires application permissions).

        Args:
            user_id: The user's ID or UPN
            select: Fields to include in response

        Returns:
            User data if found, None otherwise
        """
        token = await self._get_app_token()
        if not token:
            return None

        params = {}
        if select:
            params["$select"] = ",".join(select)

        return await self._make_request(
            "GET", f"/users/{user_id}", token, params=params
        )

    async def list_groups(
        self,
        select: Optional[List[str]] = None,
        filter_query: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """List groups in the directory (requires application permissions).

        Args:
            select: Fields to include in response
            filter_query: OData filter query

        Returns:
            List of groups if successful, None otherwise
        """
        token = await self._get_app_token()
        if not token:
            return None

        params = {}
        if select:
            params["$select"] = ",".join(select)
        if filter_query:
            params["$filter"] = filter_query

        result = await self._make_request(
            "GET", "/groups", token, params=params
        )
        if result:
            return result.get("value", [])
        return None

    async def check_group_membership(
        self, user_id: str, group_ids: List[str]
    ) -> Optional[List[str]]:
        """Check which groups a user is a member of.

        Args:
            user_id: The user's ID
            group_ids: List of group IDs to check

        Returns:
            List of group IDs the user is a member of
        """
        token = await self._get_app_token()
        if not token:
            return None

        data = {"groupIds": group_ids}
        result = await self._make_request(
            "POST",
            f"/users/{user_id}/checkMemberGroups",
            token,
            json_data=data,
        )
        if result:
            return result.get("value", [])
        return None


# Global instance for convenience
_default_graph = None


def get_graph_service() -> MicrosoftGraphService:
    """Get the default Microsoft Graph service instance.

    Returns:
        The MicrosoftGraphService instance
    """
    global _default_graph
    if _default_graph is None:
        _default_graph = MicrosoftGraphService()
    return _default_graph
