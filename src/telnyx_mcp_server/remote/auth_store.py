"""Store for OAuth authorization codes and sessions with Redis and in-memory options."""

from dataclasses import dataclass, field
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class AuthCodeData:
    """Data associated with an authorization code."""

    code: str
    azure_token: str
    azure_token_data: Dict[str, Any]
    user_info: Dict[str, Any]
    created_at: float
    expires_at: float
    used: bool = False
    state: Optional[str] = None
    redirect_uri: Optional[str] = None
    pkce_challenge: Optional[str] = None
    pkce_method: Optional[str] = None
    resource: Optional[str] = None  # RFC 8707 Resource Indicators


@dataclass
class SessionData:
    """OAuth session data."""

    session_id: str
    state: str
    redirect_uri: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    pkce_challenge: Optional[str] = None
    pkce_method: Optional[str] = None
    resource: Optional[str] = None  # RFC 8707 Resource Indicators


@dataclass
class ClientRegistration:
    """OAuth 2.0 Dynamic Client Registration data."""

    client_id: str
    client_secret: str = ""  # Empty for public clients
    redirect_uris: List[str] = field(default_factory=list)
    token_endpoint_auth_method: str = "none"
    grant_types: List[str] = field(
        default_factory=lambda: ["authorization_code"]
    )
    response_types: List[str] = field(default_factory=lambda: ["code"])
    client_name: Optional[str] = None
    client_uri: Optional[str] = None
    logo_uri: Optional[str] = None
    scope: Optional[str] = None
    contacts: List[str] = field(default_factory=list)
    tos_uri: Optional[str] = None
    policy_uri: Optional[str] = None
    jwks_uri: Optional[str] = None
    jwks: Optional[Dict[str, Any]] = None
    software_id: Optional[str] = None
    software_version: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    client_id_issued_at: float = field(default_factory=time.time)
    client_secret_expires_at: int = 0  # 0 means no expiration


class AuthStore:
    """Simple in-memory store for OAuth codes and sessions.

    Note: This is for development/testing. Production should use Redis or a database.
    """

    def __init__(self, code_ttl: int = 60, session_ttl: int = 3600):
        """Initialize the auth store.

        Args:
            code_ttl: Time-to-live for auth codes in seconds (default: 60 seconds)
            session_ttl: Time-to-live for sessions in seconds (default: 1 hour)
        """
        self._codes: Dict[str, AuthCodeData] = {}
        self._sessions: Dict[str, SessionData] = {}
        self._clients: Dict[str, ClientRegistration] = {}
        self.code_ttl = code_ttl
        self.session_ttl = session_ttl

    def create_auth_code(
        self,
        azure_token: str,
        azure_token_data: Dict[str, Any],
        user_info: Dict[str, Any],
        state: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        pkce_challenge: Optional[str] = None,
        pkce_method: Optional[str] = None,
        resource: Optional[str] = None,
    ) -> str:
        """Create a new authorization code.

        Returns:
            The generated authorization code
        """
        # Generate a cryptographically secure code
        code = secrets.token_urlsafe(32)

        # Store the code data
        self._codes[code] = AuthCodeData(
            code=code,
            azure_token=azure_token,
            azure_token_data=azure_token_data,
            user_info=user_info,
            created_at=time.time(),
            expires_at=time.time() + self.code_ttl,
            used=False,
            state=state,
            redirect_uri=redirect_uri,
            pkce_challenge=pkce_challenge,
            pkce_method=pkce_method,
            resource=resource,
        )

        # Clean up expired codes
        self._cleanup_expired_codes()

        logger.info(
            f"Created auth code for user: {user_info.get('email', 'unknown')}"
        )
        return code

    def get_auth_code(self, code: str) -> Optional[AuthCodeData]:
        """Retrieve auth code data.

        Args:
            code: The authorization code

        Returns:
            AuthCodeData if valid and not expired, None otherwise
        """
        data = self._codes.get(code)

        if not data:
            logger.warning(f"Auth code not found: {code[:8]}...")
            return None

        # Check if expired
        if time.time() > data.expires_at:
            logger.warning(f"Auth code expired: {code[:8]}...")
            del self._codes[code]
            return None

        # Check if already used
        if data.used:
            logger.warning(f"Auth code already used: {code[:8]}...")
            return None

        return data

    def mark_code_used(self, code: str) -> bool:
        """Mark an authorization code as used.

        Args:
            code: The authorization code

        Returns:
            True if successfully marked, False if not found
        """
        data = self._codes.get(code)
        if data:
            data.used = True
            logger.info(f"Marked auth code as used: {code[:8]}...")
            return True
        return False

    def create_session(
        self,
        state: str,
        redirect_uri: Optional[str] = None,
        pkce_challenge: Optional[str] = None,
        pkce_method: Optional[str] = None,
        resource: Optional[str] = None,
    ) -> str:
        """Create a new OAuth session.

        Returns:
            The session ID
        """
        session_id = secrets.token_urlsafe(32)

        self._sessions[session_id] = SessionData(
            session_id=session_id,
            state=state,
            redirect_uri=redirect_uri,
            created_at=time.time(),
            pkce_challenge=pkce_challenge,
            pkce_method=pkce_method,
            resource=resource,
        )

        # Clean up expired sessions
        self._cleanup_expired_sessions()

        logger.info(f"Created OAuth session: {session_id[:8]}...")
        return session_id

    def get_session(self, session_id: str) -> Optional[SessionData]:
        """Get session data.

        Args:
            session_id: The session ID

        Returns:
            SessionData if found and not expired, None otherwise
        """
        data = self._sessions.get(session_id)

        if not data:
            return None

        # Check if expired
        if time.time() > (data.created_at + self.session_ttl):
            logger.warning(f"Session expired: {session_id[:8]}...")
            del self._sessions[session_id]
            return None

        return data

    def get_session_by_state(self, state: str) -> Optional[SessionData]:
        """Find a session by state parameter.

        Args:
            state: The OAuth state parameter

        Returns:
            SessionData if found, None otherwise
        """
        for session in self._sessions.values():
            if session.state == state:
                # Check expiry
                if time.time() > (session.created_at + self.session_ttl):
                    continue
                return session
        return None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: The session ID

        Returns:
            True if deleted, False if not found
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Deleted session: {session_id[:8]}...")
            return True
        return False

    def _cleanup_expired_codes(self):
        """Remove expired authorization codes."""
        current_time = time.time()
        expired = [
            code
            for code, data in self._codes.items()
            if current_time > data.expires_at
        ]
        for code in expired:
            del self._codes[code]

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired auth codes")

    def _cleanup_expired_sessions(self):
        """Remove expired sessions."""
        current_time = time.time()
        expired = [
            sid
            for sid, data in self._sessions.items()
            if current_time > (data.created_at + self.session_ttl)
        ]
        for sid in expired:
            del self._sessions[sid]

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")

    def register_client(
        self,
        redirect_uris: List[str],
        token_endpoint_auth_method: str = "none",
        grant_types: Optional[List[str]] = None,
        response_types: Optional[List[str]] = None,
        client_name: Optional[str] = None,
        client_uri: Optional[str] = None,
        logo_uri: Optional[str] = None,
        scope: Optional[str] = None,
        contacts: Optional[List[str]] = None,
        tos_uri: Optional[str] = None,
        policy_uri: Optional[str] = None,
        jwks_uri: Optional[str] = None,
        jwks: Optional[Dict[str, Any]] = None,
        software_id: Optional[str] = None,
        software_version: Optional[str] = None,
    ) -> ClientRegistration:
        """Register a new OAuth client.

        Args:
            redirect_uris: List of allowed redirect URIs
            token_endpoint_auth_method: Authentication method (default: "none" for public clients)
            grant_types: Supported grant types (default: ["authorization_code"])
            response_types: Supported response types (default: ["code"])
            client_name: Human-readable client name
            client_uri: URL of client's homepage
            logo_uri: URL of client's logo
            scope: Space-separated list of default scopes
            contacts: List of contact emails
            tos_uri: URL of terms of service
            policy_uri: URL of privacy policy
            jwks_uri: URL of client's JSON Web Key Set
            jwks: Client's JSON Web Key Set (alternative to jwks_uri)
            software_id: Unique identifier for the client software
            software_version: Version of the client software

        Returns:
            ClientRegistration object with generated client_id
        """
        # Generate a unique client_id
        client_id = f"mcp_{secrets.token_urlsafe(16)}"

        # Generate client_secret for confidential clients
        client_secret = ""
        if token_endpoint_auth_method in [
            "client_secret_post",
            "client_secret_basic",
        ]:
            client_secret = secrets.token_urlsafe(32)

        # Create the registration
        registration = ClientRegistration(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uris=redirect_uris,
            token_endpoint_auth_method=token_endpoint_auth_method,
            grant_types=grant_types or ["authorization_code"],
            response_types=response_types or ["code"],
            client_name=client_name,
            client_uri=client_uri,
            logo_uri=logo_uri,
            scope=scope,
            contacts=contacts or [],
            tos_uri=tos_uri,
            policy_uri=policy_uri,
            jwks_uri=jwks_uri,
            jwks=jwks,
            software_id=software_id,
            software_version=software_version,
            created_at=time.time(),
            client_id_issued_at=int(time.time()),
            client_secret_expires_at=0
            if not client_secret
            else int(
                time.time() + 31536000
            ),  # 1 year for confidential clients
        )

        # Store the registration
        self._clients[client_id] = registration

        logger.info(
            f"Registered new OAuth client: {client_id}, "
            f"name={client_name}, redirect_uris={redirect_uris}"
        )

        return registration

    def get_client(self, client_id: str) -> Optional[ClientRegistration]:
        """Get a registered client by ID.

        Args:
            client_id: The client ID

        Returns:
            ClientRegistration if found, None otherwise
        """
        return self._clients.get(client_id)

    def update_client(
        self,
        client_id: str,
        redirect_uris: Optional[List[str]] = None,
        client_name: Optional[str] = None,
        client_uri: Optional[str] = None,
        logo_uri: Optional[str] = None,
        scope: Optional[str] = None,
        contacts: Optional[List[str]] = None,
        tos_uri: Optional[str] = None,
        policy_uri: Optional[str] = None,
        jwks_uri: Optional[str] = None,
        jwks: Optional[Dict[str, Any]] = None,
        software_version: Optional[str] = None,
    ) -> Optional[ClientRegistration]:
        """Update a registered client.

        Args:
            client_id: The client ID to update
            redirect_uris: Updated redirect URIs (if provided)
            client_name: Updated client name (if provided)
            client_uri: Updated client URI (if provided)
            logo_uri: Updated logo URI (if provided)
            scope: Updated default scope (if provided)
            contacts: Updated contact list (if provided)
            tos_uri: Updated terms of service URI (if provided)
            policy_uri: Updated privacy policy URI (if provided)
            jwks_uri: Updated JWKS URI (if provided)
            jwks: Updated JWKS (if provided)
            software_version: Updated software version (if provided)

        Returns:
            Updated ClientRegistration if found, None otherwise
        """
        client = self._clients.get(client_id)
        if not client:
            return None

        # Update only provided fields
        if redirect_uris is not None:
            client.redirect_uris = redirect_uris
        if client_name is not None:
            client.client_name = client_name
        if client_uri is not None:
            client.client_uri = client_uri
        if logo_uri is not None:
            client.logo_uri = logo_uri
        if scope is not None:
            client.scope = scope
        if contacts is not None:
            client.contacts = contacts
        if tos_uri is not None:
            client.tos_uri = tos_uri
        if policy_uri is not None:
            client.policy_uri = policy_uri
        if jwks_uri is not None:
            client.jwks_uri = jwks_uri
        if jwks is not None:
            client.jwks = jwks
        if software_version is not None:
            client.software_version = software_version

        logger.info(f"Updated OAuth client: {client_id}")
        return client

    def delete_client(self, client_id: str) -> bool:
        """Delete a registered client.

        Args:
            client_id: The client ID to delete

        Returns:
            True if deleted, False if not found
        """
        if client_id in self._clients:
            del self._clients[client_id]
            logger.info(f"Deleted OAuth client: {client_id}")
            return True
        return False


# Global instance for the application
def create_auth_store() -> Union["AsyncRedisAuthStore", "AuthStore"]:
    """Create appropriate auth store based on configuration."""
    # Check if Redis should be used
    redis_url = os.getenv("REDIS_URL")
    use_redis = os.getenv("USE_REDIS", "true").lower() in ("true", "1", "yes")
    environment = os.getenv("ENVIRONMENT", "development")

    # In development/test, prefer in-memory unless explicitly configured
    if environment in ("development", "test") and not redis_url:
        logger.info(
            "Using in-memory auth store for development/test environment"
        )
        return AuthStore()

    # Try to use Redis if available and configured
    if use_redis:
        if not redis_url:
            logger.warning(
                "Redis auth store requested but REDIS_URL not provided, falling back to in-memory"
            )
            return AuthStore()

        try:
            from .redis_auth_store import AsyncRedisAuthStore

            logger.info("Using Redis-backed auth store")
            return AsyncRedisAuthStore(redis_url=redis_url)
        except ImportError:
            logger.warning(
                "Redis auth store requested but dependencies not available, falling back to in-memory"
            )
            return AuthStore()

    logger.info("Using in-memory auth store")
    return AuthStore()


auth_store = create_auth_store()
