import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
import pytest

from pyaarlo.core.backend import ArloBackEnd
from pyaarlo.core.backend.session import ArloSession
from pyaarlo.core.cfg import ArloCfg


class FakeResponse:
    def __init__(self, status_code, headers=None, json_data=None, text=""):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is not None:
            return self._json_data
        raise ValueError("no json")


class SequentialSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, stream=False, timeout=None, cookies=None):
        self.calls.append(("GET", url))
        return self.responses.pop(0)

    def put(self, url, json=None, headers=None, timeout=None, cookies=None):
        self.calls.append(("PUT", url))
        return self.responses.pop(0)

    def post(self, url, json=None, headers=None, timeout=None, cookies=None):
        self.calls.append(("POST", url))
        return self.responses.pop(0)


class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.debugs = []

    def warning(self, msg):
        self.warnings.append(msg)

    def debug(self, msg):
        self.debugs.append(msg)

    def vdebug(self, msg):
        pass


@pytest.fixture
def session_and_backend():
    log = FakeLogger()
    cfg = ArloCfg(log=log, host="https://arlo.example", request_timeout=60)
    session = ArloSession(cfg, log)
    backend = ArloBackEnd.__new__(ArloBackEnd)
    backend._cfg = cfg
    backend._log = log
    backend._req = session
    backend._last_login_time = 0.0
    backend._login_lock = asyncio.Lock()
    backend._reconnect_job = None
    backend._mqtt_reconnect_attempts = 0
    from pyaarlo.core.backend import _AuthDetails
    backend._auth = _AuthDetails()
    backend._debug = MagicMock()
    return session, backend


@pytest.mark.asyncio
async def test_request_tuple_retries_on_401_after_successful_relogin(session_and_backend):
    session, backend = session_and_backend
    resp_401 = FakeResponse(401, text="Unauthorized")
    resp_200 = FakeResponse(200, json_data={"data": {"success": True}, "meta": {"code": 200}})
    seq_conn = SequentialSession([resp_401, resp_200])
    session.details.connection = seq_conn

    relogin_called = []

    async def fake_relogin():
        relogin_called.append(True)
        return True

    session.set_relogin_handler(fake_relogin)

    code, body = await session.request_tuple("/users/locations/123/modes", method="PUT", params={"mode": "armHome"})

    assert code == 200
    assert body == {"success": True}
    assert len(relogin_called) == 1
    assert len(seq_conn.calls) == 2


@pytest.mark.asyncio
async def test_request_tuple_returns_401_if_relogin_fails(session_and_backend):
    session, backend = session_and_backend
    resp_401 = FakeResponse(401, text="Unauthorized")
    seq_conn = SequentialSession([resp_401])
    session.details.connection = seq_conn

    session.set_relogin_handler(lambda: False)

    code, body = await session.request_tuple("/users/locations/123/modes", method="PUT")

    assert code == 401
    assert body is None
    assert len(seq_conn.calls) == 1


@pytest.mark.asyncio
async def test_request_tuple_retries_on_meta_error_9204(session_and_backend):
    session, backend = session_and_backend
    resp_expired = FakeResponse(200, json_data={"meta": {"code": 401, "error": 9204, "message": "Expired"}})
    resp_200 = FakeResponse(200, json_data={"meta": {"code": 200}, "data": {"modes": ["armed", "home"]}})
    seq_conn = SequentialSession([resp_expired, resp_200])
    session.details.connection = seq_conn

    relogin_called = []

    async def fake_relogin():
        relogin_called.append(True)
        return True

    session.set_relogin_handler(fake_relogin)

    code, body = await session.request_tuple("/users/locations/123/modes", method="GET")

    assert code == 200
    assert body == {"modes": ["armed", "home"]}
    assert len(relogin_called) == 1
    assert len(seq_conn.calls) == 2


@pytest.mark.asyncio
async def test_event_reconnect_stops_event_stream(session_and_backend):
    _, backend = session_and_backend
    mock_event = MagicMock()
    mock_event.stop = AsyncMock()
    backend._event = MagicMock()
    backend._event.stream = mock_event

    await backend._event_reconnect()

    mock_event.stop.assert_awaited_once()


def test_mqtt_on_connect_success_resets_reconnects():
    from pyaarlo.core.backend.event import _MQTT
    session = MagicMock()
    session.dispatch_connect.return_value = {"devices": []}
    mqtt_dev = _MQTT(session)
    mqtt_dev._reconnect_attempts = 2

    mock_client = MagicMock()
    mqtt_dev._client = mock_client
    mqtt_dev._on_connect(mock_client, None, {}, 0)

    assert mqtt_dev._reconnect_attempts == 0
    session.dispatch_connect.assert_called_once()


def test_mqtt_on_connect_auth_failure_disconnects():
    from pyaarlo.core.backend.event import _MQTT
    session = MagicMock()
    mqtt_dev = _MQTT(session)
    mock_client = MagicMock()
    mqtt_dev._client = mock_client

    mqtt_dev._on_connect(mock_client, None, {}, 5)

    mock_client.disconnect.assert_called_once()


def test_mqtt_on_disconnect_forces_disconnect_on_repeated_failures():
    from pyaarlo.core.backend.event import _MQTT
    session = MagicMock()
    mqtt_dev = _MQTT(session)
    mock_client = MagicMock()
    mqtt_dev._client = mock_client

    # First disconnect
    mqtt_dev._on_disconnect(mock_client, None, 7)
    assert mqtt_dev._reconnect_attempts == 1
    mock_client.disconnect.assert_not_called()

    # Second disconnect
    mqtt_dev._on_disconnect(mock_client, None, 7)
    assert mqtt_dev._reconnect_attempts == 2
    mock_client.disconnect.assert_not_called()

    # Third disconnect forces disconnect to re-establish session
    mqtt_dev._on_disconnect(mock_client, None, 7)
    assert mqtt_dev._reconnect_attempts == 3
    mock_client.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_start_schedules_reconnect_default(session_and_backend):
    _, backend = session_and_backend
    mock_tasks = MagicMock()
    backend._tasks = mock_tasks

    backend._schedule_token_renewal()

    # When no token_expires_in is present, defaults to 90 minutes (5400s)
    mock_tasks.run_in.assert_called_once_with(backend._scheduled_token_renewal, 5400)
    assert backend._reconnect_job is not None


@pytest.mark.asyncio
async def test_start_schedules_reconnect_fallback_expires_in(session_and_backend):
    session, backend = session_and_backend
    session.details.token_expires_in = int(time.time()) + 7200
    mock_tasks = MagicMock()
    backend._tasks = mock_tasks

    backend._schedule_token_renewal()

    # Expires in 7200s - 300s margin = 6900s
    args, _ = mock_tasks.run_in.call_args
    assert args[0] == backend._scheduled_token_renewal
    assert 6800 <= args[1] <= 6900
    assert backend._reconnect_job is not None


@pytest.mark.asyncio
async def test_scheduled_token_renewal_forces_reauth(session_and_backend):
    _, backend = session_and_backend
    backend._event_reconnect = AsyncMock()
    backend._login_locked = AsyncMock(return_value=True)
    backend._auth.force_reauth = False

    await backend._scheduled_token_renewal()

    assert backend._auth.force_reauth is True
    backend._event_reconnect.assert_awaited_once()
    backend._login_locked.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_cancels_reconnect_job(session_and_backend):
    _, backend = session_and_backend
    mock_tasks = MagicMock()
    backend._tasks = mock_tasks
    backend._reconnect_job = "job-123"
    backend._event_loop_stop = AsyncMock()
    backend._event = MagicMock()
    backend._event.stream = None
    backend._event.loop_task = None

    await backend.stop(logout=False)

    mock_tasks.cancel.assert_called_once_with("job-123")
    assert backend._reconnect_job is None


@pytest.mark.asyncio
async def test_request_tuple_waits_for_login_lock(session_and_backend):
    session, _ = session_and_backend
    lock = asyncio.Lock()
    session.set_login_lock(lock)
    session._is_logging_in = True

    resp_200 = FakeResponse(200, json_data={"data": {"ok": True}, "meta": {"code": 200}})
    session.details.connection = SequentialSession([resp_200])
    session.details.async_connection = None

    order = []

    async def simulate_login():
        async with lock:
            await asyncio.sleep(0.05)
            session._is_logging_in = False
            session.details.token64 = "fresh_token_64"
            order.append("login_done")

    async def make_request():
        order.append("request_start")
        code, _ = await session.request_tuple("/test/path", headers={"Authorization": "old_token"})
        order.append("request_end")
        assert code == 200

    await asyncio.gather(simulate_login(), make_request())
    assert order == ["request_start", "login_done", "request_end"]


@pytest.mark.asyncio
async def test_session_drain_in_flight(session_and_backend):
    session, _ = session_and_backend
    session.details.connection = None
    session.details.async_connection = None

    order = []

    async def long_request():
        order.append("req_start")
        # simulate an in-flight non-auth request
        session._in_flight_count += 1
        session._drain_event.clear()
        await asyncio.sleep(0.05)
        session._in_flight_count -= 1
        session._drain_event.set()
        order.append("req_done")

    async def do_drain():
        await asyncio.sleep(0.01)
        order.append("drain_start")
        await session.drain_in_flight(timeout=1.0)
        order.append("drain_done")

    await asyncio.gather(long_request(), do_drain())
    assert order == ["req_start", "drain_start", "req_done", "drain_done"]


@pytest.mark.asyncio
async def test_session_drain_transactions(session_and_backend):
    session, _ = session_and_backend
    order = []

    tid = session.start_transaction("tid-123")
    assert not session._requests_empty_event.is_set()

    async def fake_incoming_event():
        await asyncio.sleep(0.05)
        order.append("event_arrived")
        matched = session.signal_transaction_completed({"transId": tid, "data": {"ok": True}})
        assert matched is True

    async def do_wait():
        order.append("wait_start")
        resp = await session.wait_for_transaction(tid, timeout=1.0)
        order.append("wait_done")
        assert resp == {"transId": tid, "data": {"ok": True}}

    async def do_drain():
        await asyncio.sleep(0.01)
        order.append("drain_start")
        await session.drain_transactions(timeout=1.0)
        order.append("drain_done")

    await asyncio.gather(fake_incoming_event(), do_wait(), do_drain())
    assert session._requests_empty_event.is_set()
    assert order == ["wait_start", "drain_start", "event_arrived", "wait_done", "drain_done"]


@pytest.mark.asyncio
async def test_session_cancel_transactions(session_and_backend):
    session, _ = session_and_backend
    tid = session.start_transaction("tid-cancel")
    assert not session._requests_empty_event.is_set()

    wait_task = asyncio.create_task(session.wait_for_transaction(tid, timeout=1.0))
    await asyncio.sleep(0.01)

    session.cancel_transactions()
    res = await wait_task
    assert res is None
    assert session._requests_empty_event.is_set()


@pytest.mark.asyncio
async def test_session_signal_transaction_resource_matching(session_and_backend):
    session, _ = session_and_backend
    # Regex pattern transaction
    pattern = "^cameras/.*:DEVICE123$"
    tid = session.start_transaction(pattern)
    assert not session._requests_empty_event.is_set()

    wait_task = asyncio.create_task(session.wait_for_transaction(pattern, timeout=1.0))
    await asyncio.sleep(0.01)

    event_payload = {
        "resource": "cameras/12345",
        "from": "DEVICE123",
        "properties": {"activityState": "idle"},
    }
    matched = session.signal_transaction_completed(event_payload)
    assert matched is True

    res = await wait_task
    assert res == event_payload
    assert session._requests_empty_event.is_set()


@pytest.mark.asyncio
async def test_session_drain_combined(session_and_backend):
    session, _ = session_and_backend
    # When empty, drain completes immediately
    await session.drain(in_flight_timeout=0.1, transactions_timeout=0.1)
    assert session._requests_empty_event.is_set()
    assert session._drain_event.is_set()


@pytest.mark.asyncio
async def test_session_save_and_cookies_create_parent_directory(tmp_path):
    from pyaarlo.core.cfg import ArloCfg
    from pyaarlo.core.logger import ArloLogger
    from pyaarlo.core.backend.session import ArloSession
    from http.cookiejar import LWPCookieJar
    from unittest.mock import MagicMock

    log = MagicMock(spec=ArloLogger)
    nested_dir = tmp_path / "subdir" / "cache"
    cfg = ArloCfg(log=log, host="https://arlo.example")

    session = ArloSession(cfg, log)
    session._save_filename = str(nested_dir / "test_user.session")
    session.details.device_id = "test-device"
    session.details.cookies = LWPCookieJar(str(nested_dir / "test_user.cookies"))

    assert not nested_dir.exists()

    await session.save()
    await session.save_cookies()

    assert nested_dir.exists()
    assert (nested_dir / "test_user.session").exists()
    assert (nested_dir / "test_user.cookies").exists()
