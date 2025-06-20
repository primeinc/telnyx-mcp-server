"""Azure Managed Identity token handling for service-to-service calls."""

import logging
import os
from typing import Optional

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

logger = logging.getLogger(__name__)


class AzureManagedIdentity:
    """Handle Azure Managed Identity tokens for application-level API calls.

    This class provides methods to obtain tokens using the application's
    Managed Identity for service-to-service authentication. This is different
    from user-delegated authentication where you act on behalf of a user.

    Managed Identity tokens are used when the application needs to:
    - Access Key Vault for secrets
    - Call Microsoft Graph API as an application
    - Access other Azure resources with RBAC permissions
    """

    def __init__(self, client_id: Optional[str] = None):
        """Initialize the Managed Identity handler.

        Args:
            client_id: Optional client ID of the user-assigned managed identity.
                      If not provided, system-assigned identity or environment
                      variables will be used.
        """
        self.client_id = client_id or os.getenv("AZURE_CLIENT_ID")
        self._credential = None

    @property
    def credential(self):
        """Get or create the Azure credential.

        Uses DefaultAzureCredential which tries multiple authentication methods:
        1. Environment variables (for local development)
        2. Managed Identity (for Azure App Service)
        3. Azure CLI (for local development)
        4. Azure PowerShell (for local development)

        Returns:
            The Azure credential object
        """
        if self._credential is None:
            if self.is_managed_identity_available():
                # Use ManagedIdentityCredential directly in production
                self._credential = ManagedIdentityCredential(
                    client_id=self.client_id
                )
                logger.info(
                    "Using ManagedIdentityCredential",
                    extra={"client_id": self.client_id},
                )
            else:
                # Use DefaultAzureCredential for flexibility
                self._credential = DefaultAzureCredential(
                    managed_identity_client_id=self.client_id
                )
                logger.info(
                    "Using DefaultAzureCredential",
                    extra={"client_id": self.client_id},
                )

        return self._credential

    async def get_token(self, scope: str) -> Optional[str]:
        """Get an access token for the specified scope.

        Args:
            scope: The scope/resource to get a token for.
                   Examples:
                   - "https://vault.azure.net/.default" for Key Vault
                   - "https://graph.microsoft.com/.default" for MS Graph
                   - "https://management.azure.com/.default" for Azure Management

        Returns:
            The access token if successful, None otherwise
        """
        try:
            # Get token using the credential
            token = self.credential.get_token(scope)

            logger.debug(
                "Successfully obtained Managed Identity token",
                extra={
                    "scope": scope,
                    "expires_on": token.expires_on
                    if hasattr(token, "expires_on")
                    else None,
                },
            )

            return token.token

        except ClientAuthenticationError as e:
            logger.error(
                "Failed to authenticate with Managed Identity",
                extra={
                    "scope": scope,
                    "error": str(e),
                    "client_id": self.client_id,
                },
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error getting Managed Identity token",
                extra={
                    "scope": scope,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            return None

    @staticmethod
    def is_managed_identity_available() -> bool:
        """Check if Managed Identity is likely available.

        This checks environment variables to determine if we're running
        in an Azure environment that supports Managed Identity.

        Returns:
            True if Managed Identity should be available, False otherwise
        """
        # Check for Azure App Service
        if os.getenv("WEBSITE_INSTANCE_ID"):
            return True

        # Check for Azure Container Instances
        if os.getenv("CONTAINER_APP_NAME"):
            return True

        # Check for Azure VM/VMSS (IMDS endpoint)
        if os.getenv("AZURE_POD_IDENTITY_AUTHORITY_HOST"):
            return True

        # Check for generic MSI endpoint
        if os.getenv("MSI_ENDPOINT") or os.getenv("IDENTITY_ENDPOINT"):
            return True

        return False

    async def get_key_vault_token(self) -> Optional[str]:
        """Get a token specifically for Azure Key Vault access.

        This is a convenience method for the common use case of
        accessing Key Vault.

        Returns:
            The access token for Key Vault if successful, None otherwise
        """
        return await self.get_token("https://vault.azure.net/.default")

    async def get_graph_token(self) -> Optional[str]:
        """Get a token specifically for Microsoft Graph API access.

        This is a convenience method for the common use case of
        accessing Microsoft Graph as an application.

        Returns:
            The access token for MS Graph if successful, None otherwise
        """
        return await self.get_token("https://graph.microsoft.com/.default")

    async def get_management_token(self) -> Optional[str]:
        """Get a token specifically for Azure Management API access.

        This is a convenience method for the common use case of
        managing Azure resources.

        Returns:
            The access token for Azure Management if successful, None otherwise
        """
        return await self.get_token("https://management.azure.com/.default")


# Global instance for convenience
_default_identity = None


def get_managed_identity() -> AzureManagedIdentity:
    """Get the default managed identity instance.

    This provides a singleton instance for common use cases.

    Returns:
        The default AzureManagedIdentity instance
    """
    global _default_identity
    if _default_identity is None:
        _default_identity = AzureManagedIdentity()
    return _default_identity


async def create_jwt_assertion(
    managed_identity_client_id: str, client_id: str, audience: str
) -> str:
    """Create a JWT assertion for private_key_jwt client authentication using managed identity.

    This creates a JWT that Azure AD will accept as client authentication when using
    Federated Identity Credentials. The JWT is signed by the managed identity.

    Args:
        managed_identity_client_id: The client ID of the managed identity
        client_id: The client ID of the app registration
        audience: The token endpoint URL

    Returns:
        A JWT assertion that can be used for client authentication

    Raises:
        Exception: If unable to create the assertion
    """

    # Create managed identity instance with the specific client ID
    identity = AzureManagedIdentity(client_id=managed_identity_client_id)

    # Get a token from the managed identity
    # The scope should be for the app registration itself
    scope = f"api://{client_id}/.default"

    try:
        # First, try to get a token with the app's scope
        token = await identity.get_token(scope)
    except Exception as e:
        logger.warning(
            f"Failed to get token with app scope {scope}, trying Azure AD token exchange: {e}"
        )
        # If that fails, try the Azure AD token exchange endpoint
        scope = "api://AzureADTokenExchange"
        token = await identity.get_token(scope)

    if not token:
        raise Exception("Failed to get managed identity token")

    # The token we got from managed identity IS our client assertion
    # Azure AD with FIC will validate this token and accept it as proof of identity
    logger.info(
        f"Successfully obtained JWT assertion from managed identity. "
        f"MI Client ID: {managed_identity_client_id}, "
        f"App Client ID: {client_id}, "
        f"Audience: {audience}, "
        f"Scope: {scope}"
    )

    return token


async def get_managed_identity_assertion(audience: str) -> str:
    """Get a client assertion JWT using managed identity for FIC authentication.

    This is used when the Azure AD app is configured with a Federated Identity Credential
    that trusts the managed identity. The assertion is used as client authentication
    instead of a client secret.

    Args:
        audience: The audience for the assertion (typically the token endpoint URL)

    Returns:
        A JWT assertion signed by the managed identity

    Raises:
        Exception: If unable to get the assertion
    """
    # Get the managed identity instance using the client ID from the override
    override_client_id = os.getenv("OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID")
    if not override_client_id:
        raise ValueError(
            "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID environment variable not set"
        )

    # Create managed identity instance with the specific client ID
    identity = AzureManagedIdentity(client_id=override_client_id)

    # For client assertion, we need a token with the app registration's client ID as the audience
    app_client_id = os.getenv("AZURE_CLIENT_ID")
    if not app_client_id:
        raise ValueError("AZURE_CLIENT_ID environment variable not set")

    # The audience for the assertion should be the app's client ID URI
    # This is what the FIC is configured to trust
    assertion_audience = f"api://{app_client_id}"

    try:
        # Get a token from the managed identity with the app as the audience
        token = await identity.get_token(assertion_audience)
        if not token:
            raise Exception(
                f"Failed to get managed identity token for audience {assertion_audience}"
            )

        logger.info(
            "Successfully obtained managed identity assertion",
            managed_identity_client_id=override_client_id,
            app_client_id=app_client_id,
            assertion_audience=assertion_audience,
        )

        return token
    except Exception as e:
        logger.error(
            f"Failed to get managed identity assertion: {e}",
            managed_identity_client_id=override_client_id,
            app_client_id=app_client_id,
            assertion_audience=assertion_audience,
            error=str(e),
        )
        raise
