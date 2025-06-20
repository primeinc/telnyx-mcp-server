"""FastAPI dependencies for Azure Easy Auth."""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status

from .middleware import AzureEasyAuthMiddleware
from .models import AzureClientPrincipal


def get_current_user(request: Request) -> Optional[AzureClientPrincipal]:
    """Get the current authenticated user from the request.

    This dependency extracts the user information that was parsed by the
    AzureEasyAuthMiddleware. It returns None if no user is authenticated.

    Args:
        request: The FastAPI request object

    Returns:
        The authenticated user or None
    """
    return AzureEasyAuthMiddleware.get_user(request)


def require_user(
    user: Optional[AzureClientPrincipal] = Depends(get_current_user),
) -> AzureClientPrincipal:
    """Require an authenticated user for the endpoint.

    This dependency ensures that a user is authenticated before allowing
    access to the endpoint. It raises an HTTP 401 error if no user is found.

    Args:
        user: The current user from get_current_user dependency

    Returns:
        The authenticated user

    Raises:
        HTTPException: 401 Unauthorized if no user is authenticated
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(role: str):
    """Create a dependency that requires a specific role.

    This is a dependency factory that creates a dependency function
    requiring the authenticated user to have a specific role.

    Args:
        role: The required role name

    Returns:
        A dependency function that validates the role

    Example:
        @app.get("/admin", dependencies=[Depends(require_role("admin"))])
        async def admin_endpoint():
            return {"message": "Admin access granted"}
    """

    def role_checker(
        user: AzureClientPrincipal = Depends(require_user),
    ) -> AzureClientPrincipal:
        if not user.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' is required to access this resource",
            )
        return user

    return role_checker


def require_any_role(*roles: str):
    """Create a dependency that requires any of the specified roles.

    This is a dependency factory that creates a dependency function
    requiring the authenticated user to have at least one of the specified roles.

    Args:
        *roles: Variable number of role names

    Returns:
        A dependency function that validates the roles

    Example:
        @app.get("/moderator", dependencies=[Depends(require_any_role("admin", "moderator"))])
        async def moderator_endpoint():
            return {"message": "Moderator access granted"}
    """

    def role_checker(
        user: AzureClientPrincipal = Depends(require_user),
    ) -> AzureClientPrincipal:
        if not any(user.has_role(role) for role in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of these roles is required: {', '.join(roles)}",
            )
        return user

    return role_checker


def get_azure_tokens(request: Request) -> dict:
    """Get Azure tokens from the request.

    This dependency extracts any Azure tokens (access token, ID token)
    that were injected by Easy Auth into the request headers.

    Args:
        request: The FastAPI request object

    Returns:
        Dictionary containing available Azure tokens
    """
    return AzureEasyAuthMiddleware.get_azure_tokens(request)


def require_azure_token(token_type: str = "access_token"):
    """Create a dependency that requires a specific Azure token.

    This is a dependency factory that creates a dependency function
    requiring a specific type of Azure token to be present.

    Args:
        token_type: The type of token required ("access_token" or "id_token")

    Returns:
        A dependency function that returns the token

    Raises:
        HTTPException: 401 Unauthorized if the token is not available
    """

    def token_checker(
        tokens: dict = Depends(get_azure_tokens),
        user: AzureClientPrincipal = Depends(require_user),
    ) -> str:
        token = tokens.get(token_type)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Azure {token_type} is required but not available. "
                "Ensure the App Service is configured to include tokens.",
            )
        return token

    return token_checker
