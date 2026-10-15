import threading
from unittest import TestCase
from unittest.mock import MagicMock, patch

from pyaarlo.backend import ArloBackEnd


class FakeCfg(object):
    host = "https://arlo.example"
    request_timeout = 60
    reconnect_every = 90 * 60
    mqtt_host = "mqtt.example"
    mqtt_port = 8883
    mqtt_transport = "websockets"
    mqtt_hostname_check = True


class FakeBg(object):
    def __init__(self):
        self.jobs = []

    def run_every(self, cb, seconds, **kwargs):
        job = {"cb": cb, "seconds": seconds, "kwargs": kwargs}
        self.jobs.append(job)
        return job

    def run(self, cb, *args, **kwargs):
        pass

    def cancel(self, job):
        if job in self.jobs:
            self.jobs.remove(job)


class FakeArlo(object):
    def __init__(self):
        self.cfg = FakeCfg()
        self.bg = FakeBg()
        self.devices = []
        self.warnings = []
        self.debugs = []

    def warning(self, msg):
        self.warnings.append(msg)

    def debug(self, msg):
        self.debugs.append(msg)

    def vdebug(self, msg):
        pass


class FakeResponse(object):
    def __init__(self, status_code, headers=None, json_data=None, text=""):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is not None:
            return self._json_data
        raise ValueError("no json")


class SequentialSession(object):
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


class TestBackendReauth(TestCase):
    def _create_backend(self):
        backend = ArloBackEnd.__new__(ArloBackEnd)
        backend._arlo = FakeArlo()
        backend._req_lock = threading.Lock()
        backend._lock = threading.Condition()
        backend._login_lock = threading.RLock()
        backend._last_login_time = 0
        backend._is_logging_in = False
        backend._reconnect_job = None
        backend._mqtt_reconnect_attempts = 0
        backend._user_id = "user123"
        return backend

    def test_request_tuple_retries_on_401_after_successful_relogin(self):
        backend = self._create_backend()
        resp_401 = FakeResponse(401, text="Unauthorized")
        resp_200 = FakeResponse(200, json_data={"data": {"success": True}, "meta": {"code": 200}})
        session = SequentialSession([resp_401, resp_200])
        backend._session = session

        relogin_called = []

        def fake_relogin():
            relogin_called.append(True)
            return True

        backend._relogin = fake_relogin

        code, body = backend._request_tuple("/users/locations/123/modes", method="PUT", params={"mode": "armHome"})

        self.assertEqual(code, 200)
        self.assertEqual(body, {"success": True})
        self.assertEqual(len(relogin_called), 1)
        self.assertEqual(len(session.calls), 2)

    def test_request_tuple_returns_401_if_relogin_fails(self):
        backend = self._create_backend()
        resp_401 = FakeResponse(401, text="Unauthorized")
        session = SequentialSession([resp_401])
        backend._session = session

        backend._relogin = lambda: False

        code, body = backend._request_tuple("/users/locations/123/modes", method="PUT")

        self.assertEqual(code, 401)
        self.assertIsNone(body)
        self.assertEqual(len(session.calls), 1)

    def test_request_tuple_retries_on_meta_error_9204(self):
        backend = self._create_backend()
        resp_expired = FakeResponse(200, json_data={"meta": {"code": 401, "error": 9204, "message": "Expired"}})
        resp_200 = FakeResponse(200, json_data={"meta": {"code": 200}, "data": {"modes": ["armed", "home"]}})
        session = SequentialSession([resp_expired, resp_200])
        backend._session = session

        relogin_called = []

        def fake_relogin():
            relogin_called.append(True)
            return True

        backend._relogin = fake_relogin

        code, body = backend._request_tuple("/users/locations/123/modes", method="GET")

        self.assertEqual(code, 200)
        self.assertEqual(body, {"modes": ["armed", "home"]})
        self.assertEqual(len(relogin_called), 1)
        self.assertEqual(len(session.calls), 2)

    def test_event_reconnect_disconnects_mqtt_client(self):
        backend = self._create_backend()
        backend._use_mqtt = True
        mock_client = MagicMock()
        backend._event_client = mock_client

        backend._event_reconnect()

        mock_client.disconnect.assert_called_once()
        mock_client.stop.assert_not_called()

    def test_event_reconnect_stops_sse_client(self):
        backend = self._create_backend()
        backend._use_mqtt = False
        mock_client = MagicMock()
        backend._event_client = mock_client

        backend._event_reconnect()

        mock_client.stop.assert_called_once()
        mock_client.disconnect.assert_not_called()

    def test_mqtt_on_connect_success_resets_reconnects_and_runs_devices(self):
        backend = self._create_backend()
        backend._event_client = MagicMock()
        backend._event_connected = False
        backend._mqtt_reconnect_attempts = 2

        devices_called = []
        backend._arlo.bg.run = lambda cb: devices_called.append(cb)
        backend.devices = lambda: None
        backend._mqtt_subscribe = MagicMock()

        backend._mqtt_on_connect(backend._event_client, None, {}, 0)

        self.assertEqual(backend._mqtt_reconnect_attempts, 0)
        self.assertTrue(backend._event_connected)
        backend._mqtt_subscribe.assert_called_once()
        self.assertEqual(devices_called, [backend.devices])

    def test_mqtt_on_connect_auth_failure_disconnects(self):
        backend = self._create_backend()
        mock_client = MagicMock()
        backend._event_client = mock_client
        backend._event_connected = True

        backend._mqtt_on_connect(mock_client, None, {}, 5)

        self.assertFalse(backend._event_connected)
        mock_client.disconnect.assert_called_once()

    def test_mqtt_on_disconnect_forces_disconnect_on_repeated_failures(self):
        backend = self._create_backend()
        mock_client = MagicMock()
        backend._event_client = mock_client
        backend._event_connected = True

        # First unexpected disconnect
        backend._mqtt_on_disconnect(mock_client, None, 7)
        self.assertFalse(backend._event_connected)
        self.assertEqual(backend._mqtt_reconnect_attempts, 1)
        mock_client.disconnect.assert_not_called()

        # Second unexpected disconnect
        backend._mqtt_on_disconnect(mock_client, None, 7)
        self.assertEqual(backend._mqtt_reconnect_attempts, 2)
        mock_client.disconnect.assert_not_called()

        # Third unexpected disconnect forces disconnect for full re-login
        backend._mqtt_on_disconnect(mock_client, None, 7)
        self.assertEqual(backend._mqtt_reconnect_attempts, 3)
        mock_client.disconnect.assert_called_once()

    def test_start_monitoring_schedules_reconnect_configured(self):
        backend = self._create_backend()
        backend._arlo.cfg.reconnect_every = 3600
        backend._select_backend = MagicMock()
        backend._event_main = MagicMock()
        backend._use_mqtt = True
        backend._expires_in = 7200

        # Simulate stream coming up immediately
        def fake_start():
            backend._event_connected = True

        mock_thread = MagicMock()
        mock_thread.start = fake_start

        with patch("threading.Thread", return_value=mock_thread):
            backend.start_monitoring()

        self.assertIsNotNone(backend._reconnect_job)
        self.assertEqual(backend._reconnect_job["seconds"], 3600)
        self.assertEqual(backend._reconnect_job["cb"], backend._event_reconnect)

    def test_start_monitoring_schedules_reconnect_fallback_expires_in(self):
        backend = self._create_backend()
        backend._arlo.cfg.reconnect_every = 0
        backend._select_backend = MagicMock()
        backend._event_main = MagicMock()
        backend._use_mqtt = True
        backend._expires_in = 7200

        def fake_start():
            backend._event_connected = True

        mock_thread = MagicMock()
        mock_thread.start = fake_start

        with patch("threading.Thread", return_value=mock_thread):
            backend.start_monitoring()

        self.assertIsNotNone(backend._reconnect_job)
        self.assertEqual(backend._reconnect_job["seconds"], 6900)

    def test_stop_cancels_reconnect_job(self):
        backend = self._create_backend()
        backend._reconnect_job = {"job": 1}
        backend._event_client = None
        backend._event_thread = None

        backend.stop()

        self.assertIsNone(backend._reconnect_job)
