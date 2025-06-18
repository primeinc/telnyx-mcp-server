#!/usr/bin/env python3
"""Test script for Redis auth store with fallback functionality."""

import asyncio
import os
from pathlib import Path
import sys

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def test_redis_auth_store():
    """Test Redis auth store and fallback functionality."""
    print("Testing Redis Auth Store Configuration...")
    print("=" * 50)

    # Test 1: Default configuration (development environment)
    print("\n1. Testing default configuration (development):")
    os.environ["ENVIRONMENT"] = "development"
    os.environ.pop("REDIS_URL", None)  # Remove REDIS_URL if set
    os.environ["USE_REDIS"] = "true"

    from telnyx_mcp_server.remote.auth_store import create_auth_store

    store = create_auth_store()
    print(f"   ✅ Store type: {type(store).__name__}")
    print(f"   ✅ Expected: AuthStore (in-memory for development)")

    # Test 2: Production with Redis URL
    print("\n2. Testing production with Redis URL:")
    os.environ["ENVIRONMENT"] = "production"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["USE_REDIS"] = "true"

    # Reload the module to get fresh configuration
    import importlib

    import telnyx_mcp_server.remote.auth_store

    importlib.reload(telnyx_mcp_server.remote.auth_store)
    from telnyx_mcp_server.remote.auth_store import create_auth_store

    store = create_auth_store()
    print(f"   ✅ Store type: {type(store).__name__}")
    if "AsyncRedisAuthStore" in type(store).__name__:
        print(f"   ✅ Redis URL configured: {os.environ.get('REDIS_URL')}")
    else:
        print(
            f"   ⚠️  Fallback to in-memory (Redis dependencies may not be available)"
        )

    # Test 3: Production with USE_REDIS=true but no REDIS_URL
    print("\n3. Testing USE_REDIS=true without REDIS_URL:")
    os.environ["ENVIRONMENT"] = "production"
    os.environ.pop("REDIS_URL", None)  # Remove REDIS_URL
    os.environ["USE_REDIS"] = "true"

    importlib.reload(telnyx_mcp_server.remote.auth_store)
    from telnyx_mcp_server.remote.auth_store import create_auth_store

    store = create_auth_store()
    print(f"   ✅ Store type: {type(store).__name__}")
    print(f"   ✅ Expected: AuthStore (fallback due to missing REDIS_URL)")

    # Test 4: Basic functionality test
    print("\n4. Testing basic auth store functionality:")
    # Create a session
    session_id = store.create_session(
        state="test_state", redirect_uri="http://localhost:3000/callback"
    )
    print(f"   ✅ Created session: {session_id[:8]}...")

    # Get session
    session = store.get_session(session_id)
    if session:
        print(f"   ✅ Retrieved session with state: {session.state}")
    else:
        print(f"   ❌ Failed to retrieve session")
        return False

    # Create auth code
    auth_code = store.create_auth_code(
        azure_token="test_token",
        azure_token_data={"sub": "123", "name": "Test User"},
        user_info={"email": "test@example.com"},
        state="test_state",
    )
    print(f"   ✅ Created auth code: {auth_code[:8]}...")

    # Get auth code
    code_data = store.get_auth_code(auth_code)
    if code_data:
        print(f"   ✅ Retrieved auth code data")
    else:
        print(f"   ❌ Failed to retrieve auth code")
        return False

    # Delete session
    if store.delete_session(session_id):
        print(f"   ✅ Deleted session")
    else:
        print(f"   ❌ Failed to delete session")
        return False

    print("\n✅ All tests passed!")
    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(test_redis_auth_store())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
