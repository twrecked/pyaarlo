import pytest
from unittest import TestCase
from pyaarlo.core.backend.session import ArloSession
from pyaarlo.core.cfg import ArloCfg


class FakeLogger(object):
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


class FakeConnection(object):
    def __init__(self, response):
        self.response = response

    def post(self, url, json=None, headers=None, timeout=None, cookies=None):
        return self.response


@pytest.mark.asyncio
async def test_body_parse_failure_preserves_http_error_status():
    log = FakeLogger()
    cfg = ArloCfg(log=log, host="https://arlo.example", request_timeout=60)
    session = ArloSession(cfg, log)
    session.details.connection = FakeConnection(
        FakeResponse(
            429,
            headers={"Content-Type": "application/json"},
            text="not json",
        )
    )

    code, body = await session.request_tuple("/test", method="POST")

    assert code == 429
    assert body is None
    assert log.warnings == ["body-error=ValueError"]


@pytest.mark.asyncio
async def test_body_parse_failure_for_http_success_remains_request_failure():
    log = FakeLogger()
    cfg = ArloCfg(log=log, host="https://arlo.example", request_timeout=60)
    session = ArloSession(cfg, log)
    session.details.connection = FakeConnection(
        FakeResponse(
            200,
            headers={"Content-Type": "application/json"},
            text="not json",
        )
    )

    code, body = await session.request_tuple("/test", method="POST")

    assert code == 500
    assert body is None


@pytest.mark.asyncio
async def test_missing_content_type_on_http_error_preserves_status():
    log = FakeLogger()
    cfg = ArloCfg(log=log, host="https://arlo.example", request_timeout=60)
    session = ArloSession(cfg, log)
    session.details.connection = FakeConnection(FakeResponse(500, text="server error"))

    code, body = await session.request_tuple("/test", method="POST", raw=True)

    assert code == 500
    assert body is None


@pytest.mark.asyncio
async def test_http_success_text_body_is_not_treated_as_envelope():
    log = FakeLogger()
    cfg = ArloCfg(log=log, host="https://arlo.example", request_timeout=60)
    session = ArloSession(cfg, log)
    session.details.connection = FakeConnection(
        FakeResponse(
            200,
            headers={"Content-Type": "text/plain"},
            text='{"meta": {"code": 200}, "data": {}}',
        )
    )

    code, body = await session.request_tuple("/test", method="POST")

    assert code == 500
    assert body is None
