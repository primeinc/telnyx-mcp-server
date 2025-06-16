"""Tests for the Redis-backed auth store."""

import pytest
import time
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Dict, Any

# Mock Redis to avoid import errors in test environment
redis_mock = MagicMock()
redis_mock.from_url = AsyncMock()
redis_mock.ping = AsyncMock()
redis_mock.setex = AsyncMock()
redis_mock.get = AsyncMock()
redis_mock.delete = AsyncMock()
redis_mock.close = AsyncMock()

with patch.dict('sys.modules', {
    'redis': redis_mock,
    'redis.asyncio': redis_mock,
    'fakeredis': MagicMock(),
    'fakeredis.aioredis': MagicMock()
}):
    from telnyx_mcp_server.remote.redis_auth_store import (
        AsyncRedisAuthStore, AuthCodeData, SessionData
    )


class TestAuthCodeData:
    """Test the AuthCodeData dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        data = AuthCodeData(
            code="test_code",
            azure_token="test_token",
            azure_token_data={"access_token": "token"},
            user_info={"email": "test@example.com"},
            created_at=1234567890,
            expires_at=1234567950,
            used=False,
            state="test_state"
        )
        
        result = data.to_dict()
        assert isinstance(result, dict)
        assert result["code"] == "test_code"
        assert result["azure_token"] == "test_token"
        assert result["used"] is False
    
    def test_from_dict(self):
        """Test creation from dictionary."""
        data_dict = {
            "code": "test_code",
            "azure_token": "test_token",
            "azure_token_data": {"access_token": "token"},
            "user_info": {"email": "test@example.com"},
            "created_at": 1234567890,
            "expires_at": 1234567950,
            "used": False,
            "state": "test_state",
            "redirect_uri": None,
            "pkce_challenge": None,
            "pkce_method": None
        }
        
        data = AuthCodeData.from_dict(data_dict)
        assert data.code == "test_code"
        assert data.azure_token == "test_token"
        assert data.used is False


class TestSessionData:
    """Test the SessionData dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        data = SessionData(
            session_id="test_session",
            state="test_state",
            redirect_uri="http://example.com/callback",
            created_at=1234567890
        )
        
        result = data.to_dict()
        assert isinstance(result, dict)
        assert result["session_id"] == "test_session"
        assert result["state"] == "test_state"
    
    def test_from_dict(self):
        """Test creation from dictionary."""
        data_dict = {
            "session_id": "test_session",
            "state": "test_state",
            "redirect_uri": "http://example.com/callback",
            "created_at": 1234567890,
            "pkce_challenge": None,
            "pkce_method": None
        }
        
        data = SessionData.from_dict(data_dict)
        assert data.session_id == "test_session"
        assert data.state == "test_state"


@pytest.mark.asyncio
class TestAsyncRedisAuthStore:
    """Test the AsyncRedisAuthStore class."""
    
    @pytest.fixture
    def store(self):
        """Create a test store instance."""
        return AsyncRedisAuthStore(
            redis_url="redis://localhost:6379/0",
            code_ttl=60,
            session_ttl=3600,
            use_fakeredis=True
        )
    
    async def test_initialization(self, store):
        """Test store initialization."""
        assert store.redis_url == "redis://localhost:6379/0"
        assert store.code_ttl == 60
        assert store.session_ttl == 3600
        assert store.use_fakeredis is True
    
    async def test_create_auth_code_fallback(self, store):
        """Test creating auth code with fallback to in-memory store."""
        # Mock Redis failure
        store._get_redis = AsyncMock(return_value=None)
        
        code = await store.create_auth_code(
            azure_token="test_token",
            azure_token_data={"access_token": "token"},
            user_info={"email": "test@example.com"},
            state="test_state"
        )
        
        assert isinstance(code, str)
        assert len(code) > 20  # Should be a secure token
        
        # Should be stored in fallback
        assert len(store._fallback_store) > 0
    
    async def test_get_auth_code_fallback(self, store):
        """Test getting auth code from fallback store."""
        # Mock Redis failure
        store._get_redis = AsyncMock(return_value=None)
        
        # Create a code
        code = await store.create_auth_code(
            azure_token="test_token",
            azure_token_data={"access_token": "token"},
            user_info={"email": "test@example.com"}
        )
        
        # Retrieve it
        auth_data = await store.get_auth_code(code)
        assert auth_data is not None
        assert auth_data.code == code
        assert auth_data.azure_token == "test_token"
        assert auth_data.used is False
    
    async def test_mark_code_used_fallback(self, store):
        """Test marking code as used in fallback store."""
        # Mock Redis failure
        store._get_redis = AsyncMock(return_value=None)
        
        # Create and mark as used
        code = await store.create_auth_code(
            azure_token="test_token",
            azure_token_data={"access_token": "token"},
            user_info={"email": "test@example.com"}
        )
        
        success = await store.mark_code_used(code)
        assert success is True
        
        # Should be marked as used
        auth_data = await store.get_auth_code(code)
        assert auth_data is None  # Should return None for used codes
    
    async def test_create_session_fallback(self, store):
        """Test creating session with fallback store."""
        # Mock Redis failure
        store._get_redis = AsyncMock(return_value=None)
        
        session_id = await store.create_session(
            state="test_state",
            redirect_uri="http://example.com/callback"
        )
        
        assert isinstance(session_id, str)
        assert len(session_id) > 20
    
    async def test_get_session_fallback(self, store):
        """Test getting session from fallback store."""
        # Mock Redis failure
        store._get_redis = AsyncMock(return_value=None)
        
        # Create session
        session_id = await store.create_session(
            state="test_state",
            redirect_uri="http://example.com/callback"
        )
        
        # Retrieve it
        session_data = await store.get_session(session_id)
        assert session_data is not None
        assert session_data.session_id == session_id
        assert session_data.state == "test_state"
    
    async def test_get_session_by_state_fallback(self, store):
        """Test finding session by state in fallback store."""
        # Mock Redis failure
        store._get_redis = AsyncMock(return_value=None)
        
        # Create session
        session_id = await store.create_session(
            state="unique_test_state",
            redirect_uri="http://example.com/callback"
        )
        
        # Find by state
        session_data = await store.get_session_by_state("unique_test_state")
        assert session_data is not None
        assert session_data.session_id == session_id
        assert session_data.state == "unique_test_state"
    
    async def test_delete_session_fallback(self, store):
        """Test deleting session from fallback store."""
        # Mock Redis failure
        store._get_redis = AsyncMock(return_value=None)
        
        # Create session
        session_id = await store.create_session(
            state="test_state",
            redirect_uri="http://example.com/callback"
        )
        
        # Delete it
        success = await store.delete_session(session_id)
        assert success is True
        
        # Should not be found
        session_data = await store.get_session(session_id)
        assert session_data is None
    
    async def test_expired_code_handling(self, store):
        """Test that expired codes are properly handled."""
        # Mock Redis failure
        store._get_redis = AsyncMock(return_value=None)
        
        # Create store with very short TTL
        short_ttl_store = AsyncRedisAuthStore(code_ttl=1, use_fakeredis=True)
        short_ttl_store._get_redis = AsyncMock(return_value=None)
        
        # Create code
        code = await short_ttl_store.create_auth_code(
            azure_token="test_token",
            azure_token_data={"access_token": "token"},
            user_info={"email": "test@example.com"}
        )
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        
        # Should return None for expired code
        auth_data = await short_ttl_store.get_auth_code(code)
        assert auth_data is None
    
    async def test_cleanup_expired(self, store):
        """Test cleanup of expired entries."""
        # Mock Redis failure
        store._get_redis = AsyncMock(return_value=None)
        
        # Manually add expired entry
        key = "test_key"
        store._fallback_store[key] = {
            "data": {"test": "data"},
            "expires_at": time.time() - 3600  # Expired 1 hour ago
        }
        
        # Run cleanup
        cleaned_count = await store.cleanup_expired()
        assert cleaned_count >= 1
        assert key not in store._fallback_store
    
    async def test_health_check(self, store):
        """Test health check functionality."""
        health = await store.health_check()
        
        assert isinstance(health, dict)
        assert "redis_connected" in health
        assert "redis_url" in health
        assert "fallback_entries" in health
        assert "code_ttl" in health
        assert "session_ttl" in health
    
    async def test_redis_connection_success(self, store):
        """Test successful Redis connection."""
        # Mock successful Redis connection
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.get = AsyncMock(return_value='{"test": "data"}')
        mock_redis.delete = AsyncMock()
        
        store._redis = mock_redis
        store._connected = True
        
        # Test storing data
        test_data = {"test": "data"}
        success = await store._store_in_redis("test_key", test_data, 60)
        assert success is True
        mock_redis.setex.assert_called_once()
        
        # Test getting data
        data = await store._get_from_redis("test_key")
        assert data == {"test": "data"}
        mock_redis.get.assert_called_once()
        
        # Test deleting data
        success = await store._delete_from_redis("test_key")
        assert success is True
        mock_redis.delete.assert_called_once()
    
    async def test_redis_connection_failure(self, store):
        """Test Redis connection failure handling."""
        # Mock Redis connection failure
        store._redis = None
        store._connected = False
        
        # Should return None for failed connection
        redis_client = await store._get_redis()
        assert redis_client is None
        
        # Operations should return False
        success = await store._store_in_redis("test_key", {"test": "data"}, 60)
        assert success is False
        
        data = await store._get_from_redis("test_key")
        assert data is None
        
        success = await store._delete_from_redis("test_key")
        assert success is False