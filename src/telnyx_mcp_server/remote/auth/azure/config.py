"""Configuration for Azure Easy Auth."""

from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class AzureAuthConfig(BaseSettings):
    """Configuration for Azure Easy Auth and related services.

    This configuration class centralizes all Azure-related settings
    and provides validation and defaults.
    """

    # Azure AD Configuration
    tenant_id: Optional[str] = Field(
        default=None, env="AZURE_TENANT_ID", description="Azure AD tenant ID"
    )

    client_id: Optional[str] = Field(
        default=None,
        env="AZURE_CLIENT_ID",
        description="Azure AD application (client) ID",
    )

    # Easy Auth Configuration
    auth_enabled: bool = Field(
        default=False,
        env="WEBSITE_AUTH_ENABLED",
        description="Whether Azure Easy Auth is enabled (set by App Service)",
    )

    auth_enforce: bool = Field(
        default=True,
        env="WEBSITE_AUTH_ENFORCE",
        description="Whether to enforce authentication for all requests",
    )

    # Environment Detection
    website_instance_id: Optional[str] = Field(
        default=None,
        env="WEBSITE_INSTANCE_ID",
        description="Azure App Service instance ID (present when running in App Service)",
    )

    environment: str = Field(
        default="development",
        env="ENVIRONMENT",
        description="Application environment (development, staging, production)",
    )

    # CORS Configuration
    allowed_origins: List[str] = Field(
        default=["*"],
        env="MCP_ALLOWED_ORIGINS",
        description="Comma-separated list of allowed CORS origins",
    )

    # Security Headers
    strict_transport_security: str = Field(
        default="max-age=31536000; includeSubDomains",
        env="STRICT_TRANSPORT_SECURITY",
        description="HSTS header value",
    )

    referrer_policy: str = Field(
        default="strict-origin-when-cross-origin",
        env="REFERRER_POLICY",
        description="Referrer-Policy header value",
    )

    content_security_policy: Optional[str] = Field(
        default=None,
        env="CONTENT_SECURITY_POLICY",
        description="Content-Security-Policy header value",
    )

    # Token Validation
    validate_tokens: bool = Field(
        default=False,
        env="VALIDATE_AZURE_TOKENS",
        description="Whether to perform additional token validation",
    )

    token_validation_audience: Optional[str] = Field(
        default=None,
        env="TOKEN_VALIDATION_AUDIENCE",
        description="Expected audience for token validation (defaults to client_id)",
    )

    # Key Vault Configuration
    key_vault_uri: Optional[str] = Field(
        default=None,
        env="KEY_VAULT_URI",
        description="Azure Key Vault URI for secret storage",
    )

    # Managed Identity Configuration
    use_managed_identity: bool = Field(
        default=True,
        env="USE_MANAGED_IDENTITY",
        description="Whether to use Managed Identity for Azure services",
    )

    managed_identity_client_id: Optional[str] = Field(
        default=None,
        env="MANAGED_IDENTITY_CLIENT_ID",
        description="Client ID of user-assigned managed identity (optional)",
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v):
        """Parse comma-separated origins string into list."""
        if isinstance(v, str):
            return [
                origin.strip() for origin in v.split(",") if origin.strip()
            ]
        return v

    @field_validator(
        "auth_enabled",
        "auth_enforce",
        "use_managed_identity",
        "validate_tokens",
        mode="before",
    )
    @classmethod
    def parse_bool_from_string(cls, v):
        """Parse boolean from string values."""
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return bool(v)

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() == "production"

    @property
    def is_app_service(self) -> bool:
        """Check if running in Azure App Service."""
        return bool(self.website_instance_id)

    @property
    def is_easy_auth_available(self) -> bool:
        """Check if Easy Auth is available and enabled."""
        return self.is_app_service and self.auth_enabled

    @property
    def default_csp(self) -> str:
        """Get default Content-Security-Policy based on environment."""
        if self.is_production:
            # Stricter CSP for production - no unsafe-inline
            return (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:; "
                "connect-src 'self'"
            )
        else:
            # More permissive CSP for development
            return (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self'"
            )

    def get_csp_header(self) -> str:
        """Get the Content-Security-Policy header value."""
        return self.content_security_policy or self.default_csp

    def get_validation_audience(self) -> Optional[str]:
        """Get the audience for token validation."""
        return self.token_validation_audience or self.client_id

    def should_validate_tokens(self) -> bool:
        """Determine if additional token validation should be performed."""
        return self.validate_tokens and self.tenant_id is not None

    def log_configuration(self, logger):
        """Log non-sensitive configuration for debugging."""
        logger.info(
            "Azure Auth Configuration",
            extra={
                "environment": self.environment,
                "is_production": self.is_production,
                "is_app_service": self.is_app_service,
                "auth_enabled": self.auth_enabled,
                "auth_enforce": self.auth_enforce,
                "tenant_id_set": bool(self.tenant_id),
                "client_id_set": bool(self.client_id),
                "key_vault_configured": bool(self.key_vault_uri),
                "use_managed_identity": self.use_managed_identity,
                "validate_tokens": self.validate_tokens,
                "cors_origins_count": len(self.allowed_origins),
            },
        )


# Global configuration instance
_config = None


def get_azure_auth_config() -> AzureAuthConfig:
    """Get the global Azure auth configuration instance.

    Returns:
        The AzureAuthConfig instance
    """
    global _config
    if _config is None:
        _config = AzureAuthConfig()
    return _config
