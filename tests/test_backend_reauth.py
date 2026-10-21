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
    cfg = ArloCfg(log=log, host="https://arlo.example", request_timeout=60, reconnect_every=90 * 60)
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
async def test_start_schedules_reconnect_configured(session_and_backend):
    _, backend = session_and_backend
    backend._cfg._kw["reconnect_every"] = 60  # 60 minutes = 3600 seconds
    mock_tasks = MagicMock()
    backend._tasks = mock_tasks

    backend._event = MagicMock()
    async def fake_event_loop():
        backend._event.stream_connected = True
    backend._event_loop = fake_event_loop

    await backend.start()

    mock_tasks.run_in.assert_called_once_with(backend._scheduled_token_renewal, 3600)
    assert backend._reconnect_job is not None


@pytest.mark.asyncio
async def test_start_schedules_reconnect_fallback_expires_in(session_and_backend):
    session, backend = session_and_backend
    backend._cfg._kw["reconnect_every"] = 0
    session.details.token_expires_in = int(time.time()) + 7200
    mock_tasks = MagicMock()
    backend._tasks = mock_tasks

    backend._event = MagicMock()
    async def fake_event_loop():
        backend._event.stream_connected = True
    backend._event_loop = fake_event_loop

    await backend.start()

    # Expires in 7200s - 300s margin = 6900s
    args, _ = mock_tasks.run_in.call_args
    assert args[0] == backend._scheduled_token_renewal
    assert 6800 <= args[1] <= 6900
    assert backend._reconnect_job is not None


@pytest.mark.asyncio
async def test_scheduled_token_renewal_forces_reauth(session_and_backend):
    _, backend = session_and_backend
    backend._event_reconnect = AsyncMock()
    backend._auth.force_reauth = False

    await backend._scheduled_token_renewal()

    assert backend._auth.force_reauth is True
    backend._event_reconnect.assert_awaited_once()


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
