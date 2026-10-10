import threading
from unittest import TestCase

from pyaarlo.backend import ArloBackEnd


class FakeCfg(object):
    host = "https://arlo.example"
    request_timeout = 60


class FakeArlo(object):
    cfg = FakeCfg()

    def __init__(self):
        self.warnings = []
        self.debugs = []

    def warning(self, msg):
        self.warnings.append(msg)

    def debug(self, msg):
        self.debugs.append(msg)

    def vdebug(self, msg):
        pass


class FakeResponse(object):
    def __init__(self, status_code, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        raise ValueError("bad json")


class FakeSession(object):
    def __init__(self, response):
        self.response = response

    def post(self, url, json=None, headers=None, timeout=None, cookies=None):
        return self.response


class TestRequestTuple(TestCase):
    def _backend_with_response(self, response):
        backend = ArloBackEnd.__new__(ArloBackEnd)
        backend._arlo = FakeArlo()
        backend._req_lock = threading.Lock()
        backend._session = FakeSession(response)
        return backend

    def test_body_parse_failure_preserves_http_error_status(self):
        backend = self._backend_with_response(
            FakeResponse(
                429,
                headers={"Content-Type": "application/json"},
                text="not json",
            )
        )

        code, body = backend._request_tuple("/test", method="POST")

        self.assertEqual(code, 429)
        self.assertIsNone(body)
        self.assertEqual(backend._arlo.warnings, ["body-error=ValueError"])

    def test_body_parse_failure_for_http_success_remains_request_failure(self):
        backend = self._backend_with_response(
            FakeResponse(
                200,
                headers={"Content-Type": "application/json"},
                text="not json",
            )
        )

        code, body = backend._request_tuple("/test", method="POST")

        self.assertEqual(code, 500)
        self.assertIsNone(body)

    def test_missing_content_type_on_http_error_preserves_status(self):
        backend = self._backend_with_response(FakeResponse(500, text="server error"))

        code, body = backend._request_tuple("/test", method="POST", raw=True)

        self.assertEqual(code, 500)
        self.assertIsNone(body)

    def test_http_success_text_body_is_not_treated_as_envelope(self):
        backend = self._backend_with_response(
            FakeResponse(
                200,
                headers={"Content-Type": "text/plain"},
                text='{"meta": {"code": 200}, "data": {}}',
            )
        )

        code, body = backend._request_tuple("/test", method="POST")

        self.assertEqual(code, 500)
        self.assertIsNone(body)
