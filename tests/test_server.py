import pytest
import responses
import asyncio
from pyaarlo import PyArlo
from .mock_server import ArloMockServer

@pytest.mark.asyncio
async def test_sse_event_reception(tmp_path):
    """Test that PyArlo can receive events from a mock SSE server."""
    
    # 1. Start Mock Server on a random port
    server = ArloMockServer(port=8082)
    await server.start()
    
    try:
        # 2. Setup Login Mocks
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            # Allow requests to the local mock server to pass through
            rsps.add_passthru(f"http://localhost:8082")

            # Initial Authentication (still mocked via responses)
            rsps.add(
                responses.OPTIONS, "https://ocapi-app.arlo.com/api/auth",
                status=200
            )
            rsps.add(
                responses.POST, "https://ocapi-app.arlo.com/api/auth",
                json={
                    "meta": {"code": 200},
                    "data": {
                        "token": "mock-token-sse",
                        "userId": "user-mock-sse",
                        "expiresIn": 3600,
                        "authCompleted": True
                    }
                },
                status=200
            )
            rsps.add(
                responses.GET, "https://ocapi-app.arlo.com/api/validateAccessToken",
                json={"meta": {"code": 200}, "data": {"valid": True}},
                status=200,
                match_querystring=False
            )

            # 3. Initialize PyArlo
            # We point 'host' to our mock server.
            # PyArlo will use http://localhost:8082/... for all subsequent calls.
            arlo = await PyArlo.create(
                username="test-sse@example.com",
                password="password",
                host="http://localhost:8082",
                storage_dir=str(tmp_path),
                http_backend="requests",
                wait_for_initial_setup=True # Waits for SSE "connected"
            )

            assert arlo.is_connected is True
            
            # 4. Subscribe to all events
            received_events = []
            def event_handler(**kwargs):
                resp = kwargs.get("event")
                print(f"DEBUG TEST: received event: {resp}")
                received_events.append(resp)

            arlo.be.add_any_listener(event_handler)

            # 5. Push a test event from the server
            test_event = {
                "action": "is_test",
                "resource": "cameras/mock-id",
                "properties": {"motionDetected": True}
            }
            await server.push_event(test_event)

            # 6. Wait for propagation
            count = 0
            while len(received_events) == 0 and count < 50:
                await asyncio.sleep(0.1)
                count += 1

            assert len(received_events) > 0
            event = received_events[0]
            assert event is not None, f"Received None event! All events: {received_events}"
            assert event["action"] == "is_test"
            assert event["properties"]["motionDetected"] is True

    finally:
        await server.stop()
        # Give some time for background tasks to cleanup
        await asyncio.sleep(0.5)
