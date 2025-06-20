"""Azure Key Vault service using Managed Identity."""

import logging
from typing import Dict, Optional

from azure.core.exceptions import (
    ClientAuthenticationError,
    ResourceNotFoundError,
)
from azure.keyvault.secrets import SecretClient

from ...auth.azure.config import get_azure_auth_config
from ...auth.azure.managed_identity import get_managed_identity

logger = logging.getLogger(__name__)


class AzureKeyVaultService:
    """Service for accessing Azure Key Vault using Managed Identity.

    This service provides secure access to secrets stored in Azure Key Vault
    using the application's Managed Identity, eliminating the need for
    storing secrets in configuration files or environment variables.

    Example usage:
        vault = AzureKeyVaultService()
        api_key = await vault.get_secret("telnyx-api-key")
    """

    def __init__(self, vault_uri: Optional[str] = None):
        """Initialize the Key Vault service.

        Args:
            vault_uri: The Key Vault URI. If not provided, uses configuration.
        """
        config = get_azure_auth_config()
        self.vault_uri = vault_uri or config.key_vault_uri

        if not self.vault_uri:
            raise ValueError(
                "Key Vault URI must be provided or set in KEY_VAULT_URI environment variable"
            )

        self._client = None
        self._cache: Dict[str, str] = {}

    @property
    def client(self) -> SecretClient:
        """Get or create the Key Vault client.

        Returns:
            The SecretClient instance
        """
        if self._client is None:
            # Get the managed identity credential
            identity = get_managed_identity()

            # Create the Key Vault client
            self._client = SecretClient(
                vault_url=self.vault_uri, credential=identity.credential
            )

            logger.info(
                "Initialized Key Vault client",
                extra={"vault_uri": self.vault_uri},
            )

        return self._client

    async def get_secret(
        self,
        secret_name: str,
        version: Optional[str] = None,
        use_cache: bool = True,
    ) -> Optional[str]:
        """Retrieve a secret from Key Vault.

        Args:
            secret_name: The name of the secret to retrieve
            version: Optional specific version of the secret
            use_cache: Whether to use cached values (default: True)

        Returns:
            The secret value if found, None otherwise
        """
        # Check cache first
        cache_key = f"{secret_name}:{version or 'latest'}"
        if use_cache and cache_key in self._cache:
            logger.debug(
                "Returning cached secret", extra={"secret_name": secret_name}
            )
            return self._cache[cache_key]

        try:
            # Retrieve the secret
            if version:
                secret = self.client.get_secret(secret_name, version=version)
            else:
                secret = self.client.get_secret(secret_name)

            # Cache the value
            if use_cache:
                self._cache[cache_key] = secret.value

            logger.info(
                "Successfully retrieved secret from Key Vault",
                extra={
                    "secret_name": secret_name,
                    "version": version or "latest",
                    "has_value": bool(secret.value),
                },
            )

            return secret.value

        except ResourceNotFoundError:
            logger.warning(
                "Secret not found in Key Vault",
                extra={"secret_name": secret_name, "version": version},
            )
            return None

        except ClientAuthenticationError as e:
            logger.error(
                "Failed to authenticate to Key Vault",
                extra={
                    "secret_name": secret_name,
                    "error": str(e),
                    "vault_uri": self.vault_uri,
                },
            )
            raise

        except Exception as e:
            logger.error(
                "Unexpected error accessing Key Vault",
                extra={
                    "secret_name": secret_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise

    async def set_secret(
        self,
        secret_name: str,
        secret_value: str,
        content_type: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Set or update a secret in Key Vault.

        Args:
            secret_name: The name of the secret
            secret_value: The secret value
            content_type: Optional content type for the secret
            tags: Optional tags for the secret

        Returns:
            True if successful, False otherwise
        """
        try:
            # Set the secret
            secret = self.client.set_secret(
                secret_name, secret_value, content_type=content_type, tags=tags
            )

            # Clear cache for this secret
            cache_keys_to_remove = [
                key for key in self._cache if key.startswith(f"{secret_name}:")
            ]
            for key in cache_keys_to_remove:
                del self._cache[key]

            logger.info(
                "Successfully set secret in Key Vault",
                extra={
                    "secret_name": secret_name,
                    "version": secret.properties.version,
                    "has_tags": bool(tags),
                },
            )

            return True

        except Exception as e:
            logger.error(
                "Failed to set secret in Key Vault",
                extra={
                    "secret_name": secret_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            return False

    async def delete_secret(self, secret_name: str) -> bool:
        """Begin deletion of a secret from Key Vault.

        Note: Key Vault uses soft-delete by default. The secret will be
        marked for deletion and can be recovered during the retention period.

        Args:
            secret_name: The name of the secret to delete

        Returns:
            True if deletion started, False otherwise
        """
        try:
            # Begin deletion
            poller = self.client.begin_delete_secret(secret_name)

            # Clear cache for this secret
            cache_keys_to_remove = [
                key for key in self._cache if key.startswith(f"{secret_name}:")
            ]
            for key in cache_keys_to_remove:
                del self._cache[key]

            logger.info(
                "Started secret deletion in Key Vault",
                extra={"secret_name": secret_name},
            )

            return True

        except ResourceNotFoundError:
            logger.warning(
                "Secret not found for deletion",
                extra={"secret_name": secret_name},
            )
            return False

        except Exception as e:
            logger.error(
                "Failed to delete secret from Key Vault",
                extra={
                    "secret_name": secret_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            return False

    def clear_cache(self):
        """Clear the secret cache."""
        self._cache.clear()
        logger.debug("Cleared Key Vault secret cache")

    async def get_telnyx_api_key(self) -> Optional[str]:
        """Get the Telnyx API key from Key Vault.

        This is a convenience method for the common use case of
        retrieving the Telnyx API key.

        Returns:
            The Telnyx API key if found, None otherwise
        """
        return await self.get_secret("telnyx-api-key")

    async def get_connection_string(self, service: str) -> Optional[str]:
        """Get a connection string from Key Vault.

        This is a convenience method for retrieving connection strings
        following a naming convention.

        Args:
            service: The service name (e.g., "redis", "postgres")

        Returns:
            The connection string if found, None otherwise
        """
        return await self.get_secret(f"{service}-connection-string")


# Global instance for convenience
_default_vault = None


def get_key_vault_service() -> AzureKeyVaultService:
    """Get the default Key Vault service instance.

    Returns:
        The AzureKeyVaultService instance
    """
    global _default_vault
    if _default_vault is None:
        _default_vault = AzureKeyVaultService()
    return _default_vault
