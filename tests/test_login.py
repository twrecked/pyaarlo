import pytest
import responses
import time
from pyaarlo.core.backend import ArloBackEnd
from pyaarlo.core.cfg import ArloCfg
from pyaarlo.core.logger import ArloLogger
from pyaarlo.core.task_manager import ArloTaskManager

@pytest.mark.asyncio
async def test_backend_connect_success(tmp_path):
    """Test the low-level ArloBackEnd.connect() logic."""
    
    # 1. Setup minimal dependencies
    log = ArloLogger(verbose=True)
    cfg = ArloCfg(
        log=log, 
        username="test@example.com", 
        password="test-password",
        http_backend="requests",
        storage_dir=str(tmp_path)
    )
    tasks = ArloTaskManager(log)
    backend = ArloBackEnd(cfg, log, tasks)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # Mocking the auth flow (ocapi-app.arlo.com)
        rsps.add(
            responses.OPTIONS,
            "https://ocapi-app.arlo.com/api/auth",
            status=200
        )
        rsps.add(
            responses.POST,
            "https://ocapi-app.arlo.com/api/auth",
            json={
                "meta": {"code": 200},
                "data": {
                    "token": "mock_token_12345",
                    "userId": "user_mock_67890",
                    "expiresIn": 3600,
                    "authCompleted": True
                }
            },
            status=200
        )
        rsps.add(
            responses.GET,
            "https://ocapi-app.arlo.com/api/validateAccessToken",
            json={"meta": {"code": 200}, "data": {"valid": True}},
            status=200
        )

        # Mocking the session flow (myapi.arlo.com)
        rsps.add(
            responses.GET,
            "https://myapi.arlo.com/hmsweb/users/session/v3",
            json={
                "meta": {"code": 200},
                "data": {
                    "userId": "user_mock_67890",
                    "authenticated": True
                }
            },
            status=200
        )

        # 2. Run ONLY the connection logic
        await backend.connect()

        # 3. Verify
        assert backend.is_connected is True
        assert backend._req.details.token == "mock_token_12345"

@pytest.mark.asyncio
async def test_backend_connect_fail(tmp_path):
    """Test connection failure on invalid credentials."""
    
    log = ArloLogger(verbose=True)
    cfg = ArloCfg(
        log=log, 
        username="test@example.com", 
        password="bad-password",
        http_backend="requests",
        storage_dir=str(tmp_path)
    )
    tasks = ArloTaskManager(log)
    backend = ArloBackEnd(cfg, log, tasks)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.OPTIONS,
            "https://ocapi-app.arlo.com/api/auth",
            status=200
        )
        rsps.add(
            responses.POST,
            "https://ocapi-app.arlo.com/api/auth",
            json={
                "meta": {"code": 401, "message": "Password not correct", "error": 9015}
            },
            status=200
        )

        await backend.connect()

        assert backend.is_connected is False

@pytest.mark.asyncio
async def test_backend_revalidate_token_success(tmp_path):
    """Test that we can skip login if a valid saved token exists."""
    import pickle
    
    # 1. Setup session file with a saved token
    username = "test@example.com"
    storage_dir = tmp_path
    session_file = storage_dir / "test_example_com.session"
    
    save_info = {
        "version": "2",
        "device_id": "saved-device-id",
        "user_id": "user_mock_67890",
        "web_id": "user_mock_67890_web",
        "sub_id": "subscriptions/user_mock_67890_web",
        "token": "saved-token-123",
        "expires_in": str(int(time.time()) + 3600) # Valid for 1 hour
    }
    with open(session_file, "wb") as f:
        pickle.dump(save_info, f)

    # 2. Setup backend
    log = ArloLogger(verbose=True)
    cfg = ArloCfg(
        log=log, 
        username=username, 
        password="test-password",
        http_backend="requests",
        storage_dir=str(storage_dir)
    )
    tasks = ArloTaskManager(log)
    backend = ArloBackEnd(cfg, log, tasks)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # Mock token validation check (re-using the saved token)
        rsps.add(
            responses.GET,
            "https://ocapi-app.arlo.com/api/validateAccessToken",
            json={"meta": {"code": 200}, "data": {"valid": True}},
            status=200,
            match_querystring=False
        )

        # Mock session discovery
        rsps.add(
            responses.GET,
            "https://myapi.arlo.com/hmsweb/users/session/v3",
            json={
                "meta": {"code": 200},
                "data": {
                    "userId": "user_mock_67890",
                    "authenticated": True
                }
            },
            status=200
        )

        # 3. Run the connection logic
        await backend.connect()

        # 4. Verify
        assert backend.is_connected is True
        assert backend._req.details.token == "saved-token-123"
        
        # Verify that we NEVER called the login POST
        for call in rsps.calls:
            assert "/api/auth" not in call.request.url





