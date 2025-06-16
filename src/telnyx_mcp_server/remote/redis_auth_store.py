"""Redis-backed store for OAuth authorization codes and sessions."""

import asyncio
import json
import secrets
import time
from typing import Dict, Optional, Any, Union
from dataclasses import dataclass, field, asdict
import logging
import os

try:
    import redis.asyncio as redis
    from redis.asyncio import Redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None
    Redis = None

try:
    import fakeredis.aioredis as fakeredis
    FAKEREDIS_AVAILABLE = True
except ImportError:
    FAKEREDIS_AVAILABLE = False
    fakeredis = None

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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuthCodeData":
        """Create from dictionary loaded from JSON."""
        return cls(**data)

@dataclass
class SessionData:
    """OAuth session data."""
    session_id: str
    state: str
    redirect_uri: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    pkce_challenge: Optional[str] = None
    pkce_method: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionData":
        """Create from dictionary loaded from JSON."""
        return cls(**data)


class AsyncRedisAuthStore:
    """Redis-backed store for OAuth codes and sessions with fallback to in-memory.
    
    Features:
    - Async Redis operations
    - TTL support with Redis expiration
    - Environment-configurable Redis URL
    - Fallback to in-memory store for dev/test
    - Connection health checks and retry logic
    """
    
    def __init__(
        self, 
        redis_url: Optional[str] = None,
        code_ttl: int = 60, 
        session_ttl: int = 3600,
        use_fakeredis: bool = False
    ):
        """Initialize the Redis auth store.
        
        Args:
            redis_url: Redis connection URL (defaults to env REDIS_URL)
            code_ttl: Time-to-live for auth codes in seconds (default: 60 seconds)
            session_ttl: Time-to-live for sessions in seconds (default: 1 hour)
            use_fakeredis: Use fakeredis for testing (default: False)
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.code_ttl = code_ttl
        self.session_ttl = session_ttl
        self.use_fakeredis = use_fakeredis
        self._redis: Optional[Redis] = None
        self._connected = False
        self._fallback_store: Dict[str, Any] = {}  # In-memory fallback
        
        # Key prefixes for Redis
        self.CODE_PREFIX = "mcp:auth:code:"
        self.SESSION_PREFIX = "mcp:auth:session:"
        self.STATE_INDEX_PREFIX = "mcp:auth:state:"
    
    async def _get_redis(self) -> Optional[Redis]:
        """Get Redis connection with health check."""
        if self._redis is None:
            await self._connect()
        
        if self._redis and self._connected:
            try:
                # Quick health check
                await self._redis.ping()
                return self._redis
            except Exception as e:
                logger.warning(f"Redis health check failed: {e}")
                self._connected = False
                return None
        
        return None
    
    async def _connect(self) -> bool:
        """Connect to Redis with fallback handling."""
        if not REDIS_AVAILABLE and not self.use_fakeredis:
            logger.warning("Redis not available, using in-memory fallback")
            return False
        
        try:
            if self.use_fakeredis and FAKEREDIS_AVAILABLE:
                # Use fakeredis for testing
                self._redis = fakeredis.FakeRedis.from_url(
                    self.redis_url,
                    decode_responses=True
                )
                logger.info("Connected to FakeRedis for testing")
            elif REDIS_AVAILABLE:
                # Use real Redis
                self._redis = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
                logger.info(f"Connected to Redis at {self.redis_url}")
            else:
                logger.warning("Neither Redis nor FakeRedis available")
                return False
            
            # Test connection
            await self._redis.ping()
            self._connected = True
            return True
            
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}, using in-memory fallback")
            self._connected = False
            return False
    
    async def _store_in_redis(self, key: str, data: Dict[str, Any], ttl: int) -> bool:
        """Store data in Redis with TTL."""
        redis_client = await self._get_redis()
        if not redis_client:
            return False
        
        try:
            serialized = json.dumps(data)
            await redis_client.setex(key, ttl, serialized)
            return True
        except Exception as e:
            logger.error(f"Failed to store in Redis: {e}")
            return False
    
    async def _get_from_redis(self, key: str) -> Optional[Dict[str, Any]]:
        """Get data from Redis."""
        redis_client = await self._get_redis()
        if not redis_client:
            return None
        
        try:
            data = await redis_client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get from Redis: {e}")
            return None
    
    async def _delete_from_redis(self, key: str) -> bool:
        """Delete data from Redis."""
        redis_client = await self._get_redis()
        if not redis_client:
            return False
        
        try:
            await redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete from Redis: {e}")
            return False
    
    def _fallback_store_key(self, key: str) -> str:
        """Generate fallback store key."""
        return key.replace(":", "_")
    
    async def create_auth_code(
        self,
        azure_token: str,
        azure_token_data: Dict[str, Any],
        user_info: Dict[str, Any],
        state: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        pkce_challenge: Optional[str] = None,
        pkce_method: Optional[str] = None
    ) -> str:
        """Create a new authorization code.
        
        Returns:
            The generated authorization code
        """
        # Generate a cryptographically secure code
        code = secrets.token_urlsafe(32)
        
        # Create auth code data
        auth_data = AuthCodeData(
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
            pkce_method=pkce_method
        )
        
        # Store in Redis first, fallback to memory
        key = f"{self.CODE_PREFIX}{code}"
        success = await self._store_in_redis(key, auth_data.to_dict(), self.code_ttl)
        
        if not success:
            # Fallback to in-memory store
            fallback_key = self._fallback_store_key(key)
            self._fallback_store[fallback_key] = {
                "data": auth_data.to_dict(),
                "expires_at": time.time() + self.code_ttl
            }
            logger.info(f"Stored auth code in fallback store for user: {user_info.get('email', 'unknown')}")
        else:
            logger.info(f"Stored auth code in Redis for user: {user_info.get('email', 'unknown')}")
        
        return code
    
    async def get_auth_code(self, code: str) -> Optional[AuthCodeData]:
        """Retrieve auth code data.
        
        Args:
            code: The authorization code
            
        Returns:
            AuthCodeData if valid and not expired, None otherwise
        """
        key = f"{self.CODE_PREFIX}{code}"
        
        # Try Redis first
        data_dict = await self._get_from_redis(key)
        
        if not data_dict:
            # Try fallback store
            fallback_key = self._fallback_store_key(key)
            fallback_entry = self._fallback_store.get(fallback_key)
            
            if fallback_entry:
                # Check if expired
                if time.time() > fallback_entry["expires_at"]:
                    del self._fallback_store[fallback_key]
                    logger.warning(f"Auth code expired in fallback store: {code[:8]}...")
                    return None
                
                data_dict = fallback_entry["data"]
            else:
                logger.warning(f"Auth code not found: {code[:8]}...")
                return None
        
        try:
            auth_data = AuthCodeData.from_dict(data_dict)
            
            # Check if expired (double-check for Redis entries)
            if time.time() > auth_data.expires_at:
                logger.warning(f"Auth code expired: {code[:8]}...")
                await self._delete_from_redis(key)
                return None
            
            # Check if already used
            if auth_data.used:
                logger.warning(f"Auth code already used: {code[:8]}...")
                return None
            
            return auth_data
            
        except Exception as e:
            logger.error(f"Failed to deserialize auth code data: {e}")
            return None
    
    async def mark_code_used(self, code: str) -> bool:
        """Mark an authorization code as used.
        
        Args:
            code: The authorization code
            
        Returns:
            True if successfully marked, False if not found
        """
        key = f"{self.CODE_PREFIX}{code}"
        
        # Try to get and update in Redis
        data_dict = await self._get_from_redis(key)
        
        if data_dict:
            data_dict["used"] = True
            # Update with remaining TTL
            auth_data = AuthCodeData.from_dict(data_dict)
            remaining_ttl = max(1, int(auth_data.expires_at - time.time()))
            success = await self._store_in_redis(key, data_dict, remaining_ttl)
            
            if success:
                logger.info(f"Marked auth code as used in Redis: {code[:8]}...")
                return True
        
        # Try fallback store
        fallback_key = self._fallback_store_key(key)
        fallback_entry = self._fallback_store.get(fallback_key)
        
        if fallback_entry:
            fallback_entry["data"]["used"] = True
            logger.info(f"Marked auth code as used in fallback store: {code[:8]}...")
            return True
        
        return False
    
    async def create_session(
        self,
        state: str,
        redirect_uri: Optional[str] = None,
        pkce_challenge: Optional[str] = None,
        pkce_method: Optional[str] = None
    ) -> str:
        """Create a new OAuth session.
        
        Returns:
            The session ID
        """
        session_id = secrets.token_urlsafe(32)
        
        session_data = SessionData(
            session_id=session_id,
            state=state,
            redirect_uri=redirect_uri,
            created_at=time.time(),
            pkce_challenge=pkce_challenge,
            pkce_method=pkce_method
        )
        
        # Store session in Redis first, fallback to memory
        session_key = f"{self.SESSION_PREFIX}{session_id}"
        success = await self._store_in_redis(session_key, session_data.to_dict(), self.session_ttl)
        
        # Also create state index for lookups
        state_key = f"{self.STATE_INDEX_PREFIX}{state}"
        await self._store_in_redis(state_key, {"session_id": session_id}, self.session_ttl)
        
        if not success:
            # Fallback to in-memory store
            fallback_session_key = self._fallback_store_key(session_key)
            fallback_state_key = self._fallback_store_key(state_key)
            
            expires_at = time.time() + self.session_ttl
            self._fallback_store[fallback_session_key] = {
                "data": session_data.to_dict(),
                "expires_at": expires_at
            }
            self._fallback_store[fallback_state_key] = {
                "data": {"session_id": session_id},
                "expires_at": expires_at
            }
            logger.info(f"Stored session in fallback store: {session_id[:8]}...")
        else:
            logger.info(f"Stored session in Redis: {session_id[:8]}...")
        
        return session_id
    
    async def get_session(self, session_id: str) -> Optional[SessionData]:
        """Get session data.
        
        Args:
            session_id: The session ID
            
        Returns:
            SessionData if found and not expired, None otherwise
        """
        key = f"{self.SESSION_PREFIX}{session_id}"
        
        # Try Redis first
        data_dict = await self._get_from_redis(key)
        
        if not data_dict:
            # Try fallback store
            fallback_key = self._fallback_store_key(key)
            fallback_entry = self._fallback_store.get(fallback_key)
            
            if fallback_entry:
                # Check if expired
                if time.time() > fallback_entry["expires_at"]:
                    del self._fallback_store[fallback_key]
                    return None
                
                data_dict = fallback_entry["data"]
            else:
                return None
        
        try:
            session_data = SessionData.from_dict(data_dict)
            
            # Check if expired (double-check for Redis entries)
            if time.time() > (session_data.created_at + self.session_ttl):
                logger.warning(f"Session expired: {session_id[:8]}...")
                await self._delete_from_redis(key)
                return None
            
            return session_data
            
        except Exception as e:
            logger.error(f"Failed to deserialize session data: {e}")
            return None
    
    async def get_session_by_state(self, state: str) -> Optional[SessionData]:
        """Find a session by state parameter.
        
        Args:
            state: The OAuth state parameter
            
        Returns:
            SessionData if found, None otherwise
        """
        state_key = f"{self.STATE_INDEX_PREFIX}{state}"
        
        # Try Redis first
        index_data = await self._get_from_redis(state_key)
        
        if not index_data:
            # Try fallback store
            fallback_state_key = self._fallback_store_key(state_key)
            fallback_entry = self._fallback_store.get(fallback_state_key)
            
            if fallback_entry:
                # Check if expired
                if time.time() > fallback_entry["expires_at"]:
                    del self._fallback_store[fallback_state_key]
                    return None
                
                index_data = fallback_entry["data"]
            else:
                return None
        
        if index_data and "session_id" in index_data:
            return await self.get_session(index_data["session_id"])
        
        return None
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            True if deleted, False if not found
        """
        # Get session to find state for cleanup
        session = await self.get_session(session_id)
        
        session_key = f"{self.SESSION_PREFIX}{session_id}"
        success = await self._delete_from_redis(session_key)
        
        # Also clean up state index
        if session and session.state:
            state_key = f"{self.STATE_INDEX_PREFIX}{session.state}"
            await self._delete_from_redis(state_key)
        
        # Clean up fallback store
        fallback_session_key = self._fallback_store_key(session_key)
        if fallback_session_key in self._fallback_store:
            del self._fallback_store[fallback_session_key]
            success = True
        
        if session and session.state:
            fallback_state_key = self._fallback_store_key(f"{self.STATE_INDEX_PREFIX}{session.state}")
            if fallback_state_key in self._fallback_store:
                del self._fallback_store[fallback_state_key]
        
        if success:
            logger.info(f"Deleted session: {session_id[:8]}...")
        
        return success
    
    async def cleanup_expired(self) -> int:
        """Clean up expired entries from fallback store.
        
        Redis handles expiration automatically.
        
        Returns:
            Number of entries cleaned up
        """
        current_time = time.time()
        expired_keys = []
        
        for key, entry in self._fallback_store.items():
            if current_time > entry["expires_at"]:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._fallback_store[key]
        
        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired entries from fallback store")
        
        return len(expired_keys)
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of the auth store.
        
        Returns:
            Health status information
        """
        redis_client = await self._get_redis()
        redis_connected = redis_client is not None
        
        return {
            "redis_connected": redis_connected,
            "redis_url": self.redis_url,
            "fallback_entries": len(self._fallback_store),
            "code_ttl": self.code_ttl,
            "session_ttl": self.session_ttl
        }
    
    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._connected = False