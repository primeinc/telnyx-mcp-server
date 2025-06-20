"""Pydantic models for Azure Easy Auth (Built-in Authentication)."""

from typing import List, Optional

from pydantic import BaseModel, Field


class AzureClaim(BaseModel):
    """Represents a single claim from Azure AD."""

    typ: str = Field(
        ...,
        description="The claim type (e.g., 'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier')",
    )
    val: str = Field(..., description="The claim value")


class AzureClientPrincipal(BaseModel):
    """Represents the decoded X-MS-CLIENT-PRINCIPAL header from Azure Easy Auth.

    This model maps the principal data injected by Azure App Service
    Built-in Authentication (Easy Auth) into request headers.
    """

    auth_typ: str = Field(
        ..., alias="authTyp", description="Authentication type (e.g., 'aad')"
    )
    claims: List[AzureClaim] = Field(
        ..., description="List of user claims from Azure AD"
    )
    name_typ: str = Field(
        ..., alias="nameTyp", description="Name identifier type"
    )
    role_typ: str = Field(..., alias="roleTyp", description="Role claim type")

    @property
    def user_id(self) -> Optional[str]:
        """Get the user's unique identifier (subject/nameidentifier claim)."""
        return self.get_claim_value(
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"
        )

    @property
    def email(self) -> Optional[str]:
        """Get the user's email address."""
        email_claim_types = [
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            "emails",
            "email",
            "preferred_username",
        ]

        for claim_type in email_claim_types:
            value = self.get_claim_value(claim_type)
            if value:
                return value
        return None

    @property
    def name(self) -> Optional[str]:
        """Get the user's display name."""
        name_claim_types = [
            "name",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
            "given_name",
        ]

        for claim_type in name_claim_types:
            value = self.get_claim_value(claim_type)
            if value:
                return value
        return None

    @property
    def roles(self) -> List[str]:
        """Get the user's roles."""
        roles = []
        role_claim_types = ["roles", "role", self.role_typ]

        for claim_type in role_claim_types:
            for claim in self.claims:
                if claim.typ == claim_type:
                    roles.append(claim.val)

        return roles

    def get_claim_value(self, claim_type: str) -> Optional[str]:
        """Get the value of a specific claim by type.

        Args:
            claim_type: The claim type to look for

        Returns:
            The claim value if found, None otherwise
        """
        for claim in self.claims:
            if claim.typ == claim_type:
                return claim.val
        return None

    def has_role(self, role: str) -> bool:
        """Check if the user has a specific role.

        Args:
            role: The role to check for

        Returns:
            True if the user has the role, False otherwise
        """
        return role in self.roles

    def to_dict(self) -> dict:
        """Convert to a dictionary suitable for API responses."""
        return {
            "id": self.user_id,
            "email": self.email,
            "name": self.name,
            "roles": self.roles,
            "auth_type": self.auth_typ,
        }


class AzureTokenStoreResponse(BaseModel):
    """Response from Azure Easy Auth token store (/.auth/me endpoint)."""

    provider_name: str = Field(
        ...,
        alias="provider_name",
        description="Identity provider name (e.g., 'aad')",
    )
    user_id: str = Field(..., alias="user_id", description="User identifier")
    user_claims: List[dict] = Field(
        ..., alias="user_claims", description="User claims"
    )
    access_token: Optional[str] = Field(
        None,
        alias="access_token",
        description="Access token for downstream APIs",
    )
    refresh_token: Optional[str] = Field(
        None, alias="refresh_token", description="Refresh token"
    )
    id_token: Optional[str] = Field(
        None, alias="id_token", description="ID token"
    )
    expires_on: Optional[str] = Field(
        None, alias="expires_on", description="Token expiration time"
    )
