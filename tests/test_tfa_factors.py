"""2FA factor selection, push approval and the interactive `ArloLogin`.

These run the real login state machine against a small fake of Arlo's auth
API, served through `responses`, so the session file and cookie handling are
exercised for real.
"""

import json
import pickle
import re
import time

import pytest
import responses

from pyaarlo import ArloLogin, LoginStep
from pyaarlo.core.backend import ArloBackEnd
from pyaarlo.core.backend.tfa import ArloTFA
from pyaarlo.core.cfg import ArloCfg
from pyaarlo.core.logger import ArloLogger
from pyaarlo.core.task_manager import ArloTaskManager


AUTH = "https://ocapi-app.arlo.com"
SESSION_V3 = "https://myapi.arlo.com/hmsweb/users/session/v3"

EMAIL = {"factorId": "fid-email", "factorType": "EMAIL", "factorRole": "PRIMARY",
         "factorNickname": "home@example.com"}
SMS = {"factorId": "fid-sms", "factorType": "SMS", "factorRole": "SECONDARY",
       "factorNickname": "+33 6 00 00 00 00"}
PHONE_1 = {"factorId": "fid-push-1", "factorType": "PUSH", "factorRole": "SECONDARY",
           "factorNickname": "Pixel 9"}
PHONE_2 = {"factorId": "fid-push-2", "factorType": "PUSH", "factorRole": "SECONDARY",
           "factorNickname": "iPhone"}
ALL_FACTORS = [EMAIL, SMS, PHONE_1, PHONE_2]


def _ok(data):
    return 200, {"Content-Type": "application/json"}, json.dumps({"meta": {"code": 200}, "data": data})


def _err(code, error, message):
    return 200, {"Content-Type": "application/json"}, json.dumps(
        {"meta": {"code": code, "error": error, "message": message}})


class FakeArloAuth:
    """Just enough of ocapi-app.arlo.com to log in."""

    def __init__(self, rsps, factors=None, trusted=False, push_pending=0, push_answer="approve",
                 otp="123456"):
        self.factors = ALL_FACTORS if factors is None else factors
        self.trusted = trusted
        self.push_pending = push_pending
        self.push_answer = push_answer
        self.otp = otp
        self.started = []
        self.finished = []
        self.paired = 0
        self.signins = 0
        self._current_factor = None

        rsps.add_callback(responses.OPTIONS, re.compile(AUTH + "/api/.*"), callback=lambda r: (200, {}, ""))
        rsps.add_callback(responses.POST, AUTH + "/api/auth", callback=self._auth)
        rsps.add_callback(responses.POST, AUTH + "/api/getFactorId", callback=self._get_factor_id)
        rsps.add_callback(responses.GET, re.compile(AUTH + "/api/getFactors.*"), callback=self._get_factors)
        rsps.add_callback(responses.POST, AUTH + "/api/startAuth", callback=self._start)
        rsps.add_callback(responses.POST, AUTH + "/api/finishAuth", callback=self._finish)
        rsps.add_callback(responses.GET, re.compile(AUTH + "/api/validateAccessToken.*"),
                          callback=lambda r: _ok({"valid": True}))
        rsps.add_callback(responses.POST, AUTH + "/api/startPairingFactor", callback=self._pair)
        rsps.add_callback(responses.GET, SESSION_V3, callback=lambda r: _ok({"userId": "u1"}))

    @staticmethod
    def _full_token():
        return {"token": "full-token", "userId": "u1", "expiresIn": int(time.time()) + 7200,
                "authCompleted": True, "browserAuthCode": "bac-1"}

    def _auth(self, request):
        self.signins += 1
        return _ok({"token": "partial-token", "userId": "u1", "expiresIn": int(time.time()) + 7200,
                    "authCompleted": False})

    def _get_factor_id(self, request):
        if self.trusted:
            return _ok({"factorId": "fid-browser"})
        return _err(400, 9204, "Browser is not trusted")

    def _get_factors(self, request):
        return _ok({"items": self.factors})

    def _start(self, request):
        payload = json.loads(request.body)
        self.started.append(payload)
        if payload["factorId"] == "fid-browser":
            return _ok(self._full_token())
        self._current_factor = payload["factorId"]
        return _ok({"factorAuthCode": "fac-1"})

    def _finish(self, request):
        payload = json.loads(request.body)
        self.finished.append(payload)
        if "otp" in payload:
            if payload["otp"] == self.otp:
                return _ok(self._full_token())
            return _err(400, 9207, "Incorrect one time password")
        if self.push_pending > 0:
            self.push_pending -= 1
            return _err(400, 9233, "Authentication is not finished yet")
        if self.push_answer == "approve":
            return _ok(self._full_token())
        if self.push_answer == "deny":
            return _err(400, 9239, "Push verification failed")
        return _err(400, 9233, "Authentication is not finished yet")

    def _pair(self, request):
        self.paired += 1
        self.trusted = True
        return _ok({})


def _backend(tmp_path, **kwargs):
    log = ArloLogger()
    options = dict(username="test@example.com", password="pw", http_backend="requests",
                   storage_dir=str(tmp_path), tfa_push_poll=0.01)
    options.update(kwargs)
    cfg = ArloCfg(log, **options)
    return ArloBackEnd(cfg, log, ArloTaskManager(log)), log


# --- cfg ---------------------------------------------------------------------

def test_cfg_push_defaults():
    cfg = ArloCfg(ArloLogger())
    assert cfg.tfa_factor_id is None
    assert cfg.tfa_push_timeout == 300
    assert cfg.tfa_push_poll == 5


def test_cfg_push_timeout_honours_explicit_retries():
    cfg = ArloCfg(ArloLogger(), tfa_retries=10, tfa_delay=2)
    assert cfg.tfa_push_timeout == 20
    cfg = ArloCfg(ArloLogger(), tfa_retries=10, tfa_push_timeout=60)
    assert cfg.tfa_push_timeout == 60


def test_cfg_push_source_implies_push_type():
    assert ArloCfg(ArloLogger(), tfa_source="push").tfa_type == "push"
    assert ArloCfg(ArloLogger(), tfa="push").tfa_type == "push"
    assert ArloCfg(ArloLogger(), tfa="sms").tfa_type == "sms"
    assert ArloCfg(ArloLogger(), tfa_factor_id="").tfa_factor_id is None


def test_unknown_tfa_source_is_an_error():
    log = ArloLogger()
    tfa = ArloTFA(ArloCfg(log, tfa_source="pusj"), log)
    assert tfa.is_push is False
    assert "unknown tfa_source 'pusj'" in log.last_error


@pytest.mark.asyncio
async def test_tfa_source_exception_is_a_failed_retrieval():
    log = ArloLogger()
    tfa = ArloTFA(ArloCfg(log, tfa_source="console"), log)

    async def _raise():
        raise EOFError("no tty")

    tfa._handler.get = _raise
    assert await tfa.code() is None


# --- factor selection --------------------------------------------------------

@pytest.mark.asyncio
async def test_select_factor_by_id_wins(tmp_path):
    be, _ = _backend(tmp_path, tfa="email", tfa_factor_id="fid-push-2")
    assert be._auth_select_factor(ALL_FACTORS) is PHONE_2


@pytest.mark.asyncio
async def test_select_factor_unknown_id_lists_factors(tmp_path):
    be, log = _backend(tmp_path, tfa_factor_id="nope")
    assert be._auth_select_factor(ALL_FACTORS) is None
    assert "no factor with id nope" in log.last_error
    assert "PUSH/iPhone (fid-push-2)" in log.last_error


@pytest.mark.asyncio
async def test_select_factor_by_type_and_nickname(tmp_path):
    be, _ = _backend(tmp_path, tfa="push", tfa_nickname="iPhone")
    assert be._auth_select_factor(ALL_FACTORS) is PHONE_2


@pytest.mark.asyncio
async def test_select_factor_falls_back_to_first_of_type(tmp_path):
    be, log = _backend(tmp_path, tfa="push", tfa_nickname="nobody")
    warnings = []
    log.warning = warnings.append
    assert be._auth_select_factor(ALL_FACTORS) is PHONE_1
    assert any("set tfa_factor_id to choose" in w for w in warnings)


@pytest.mark.asyncio
async def test_select_factor_missing_type(tmp_path):
    be, log = _backend(tmp_path, tfa="sms")
    assert be._auth_select_factor([EMAIL, PHONE_1]) is None
    assert "no sms factor" in log.last_error


# --- PyArlo style login ------------------------------------------------------

@pytest.mark.asyncio
async def test_push_factor_id_uses_push_flow_whatever_the_source(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        fake = FakeArloAuth(rsps, push_pending=2)
        be, _ = _backend(tmp_path, tfa="email:console", tfa_factor_id="fid-push-2")
        await be.connect()

    assert be.is_connected
    assert fake.started[0] == {"factorId": "fid-push-2", "factorType": "", "userId": "u1"}
    assert len(fake.finished) == 3
    assert all("otp" not in f for f in fake.finished)
    assert fake.paired == 1


@pytest.mark.asyncio
async def test_push_denied_stops_at_once(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        fake = FakeArloAuth(rsps, push_pending=1, push_answer="deny")
        be, log = _backend(tmp_path, tfa="push", tfa_push_timeout=60)
        await be.connect()

    assert not be.is_connected
    assert len(fake.finished) == 2
    assert "denied" in log.last_error


@pytest.mark.asyncio
async def test_push_times_out(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        FakeArloAuth(rsps, push_answer="never")
        be, log = _backend(tmp_path, tfa="push", tfa_push_timeout=0.05)
        await be.connect()

    assert not be.is_connected
    assert "not approved within" in log.last_error


@pytest.mark.asyncio
async def test_push_source_with_code_factor_is_refused(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        fake = FakeArloAuth(rsps)
        be, log = _backend(tmp_path, tfa_source="push", tfa_factor_id="fid-email")
        await be.connect()

    assert not be.is_connected
    assert fake.started == []
    assert "can't be approved from the phone app" in log.last_error


@pytest.mark.asyncio
async def test_code_factor_reads_the_configured_source(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "123456")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        fake = FakeArloAuth(rsps)
        be, _ = _backend(tmp_path, tfa="sms:console")
        await be.connect()

    assert be.is_connected
    assert fake.started[0]["factorId"] == "fid-sms"
    assert fake.started[0]["factorType"] == "BROWSER"
    assert fake.finished == [{"factorAuthCode": "fac-1", "isBrowserTrusted": True, "otp": "123456"}]


@pytest.mark.asyncio
async def test_tfa_factors_once_logged_in(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        FakeArloAuth(rsps, trusted=True)
        be, _ = _backend(tmp_path)
        await be.connect()
        assert be.is_connected
        assert await be.tfa_factors() == ALL_FACTORS


# --- user agent pinning ------------------------------------------------------

@pytest.mark.asyncio
async def test_paired_user_agent_is_reused(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        FakeArloAuth(rsps, push_answer="approve")
        be, _ = _backend(tmp_path, tfa="push", user_agent="random")
        await be.connect()
        paired = be._req.details.user_agent

    session_file = next(tmp_path.glob("*.session"))
    with open(session_file, "rb") as f:
        saved = pickle.load(f)
    assert saved["user_agent"] == paired
    assert saved["user_agent_cfg"] == "random"

    # Same setting: the identity Arlo trusts is kept, even for `random`.
    be2, _ = _backend(tmp_path, tfa="push", user_agent="random")
    await be2._req.load()
    assert be2._auth_user_agent() == paired

    # The user changed the setting on purpose: honour it.
    be3, _ = _backend(tmp_path, tfa="push", user_agent="!my-agent")
    await be3._req.load()
    assert be3._auth_user_agent() == "my-agent"


# --- interactive login -------------------------------------------------------

def _login(tmp_path, **kwargs):
    options = dict(username="test@example.com", password="pw", http_backend="requests",
                   storage_dir=str(tmp_path), tfa_push_poll=0.01)
    options.update(kwargs)
    return ArloLogin(**options)


@pytest.mark.asyncio
async def test_interactive_push_login(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        fake = FakeArloAuth(rsps, push_pending=2)
        login = _login(tmp_path)

        assert await login.start() == LoginStep.NEEDS_FACTOR
        assert [f["factorId"] for f in login.factors] == [f["factorId"] for f in ALL_FACTORS]

        assert await login.choose_factor("fid-push-2") == LoginStep.AWAITING_PUSH
        assert await login.poll_push() == LoginStep.AWAITING_PUSH
        assert await login.poll_push() == LoginStep.AWAITING_PUSH
        assert await login.poll_push() == LoginStep.SUCCESS
        await login.close()

    assert fake.started[0]["factorType"] == ""
    assert fake.paired == 1
    assert next(tmp_path.glob("*.session")).exists()

    # The trusted browser is reused: no 2fa the second time round.
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        fake = FakeArloAuth(rsps, trusted=True)
        be, _ = _backend(tmp_path)
        be._auth.force_reauth = True
        await be.connect()
        assert be.is_connected
        assert [s["factorId"] for s in fake.started] == ["fid-browser"]


@pytest.mark.asyncio
async def test_interactive_code_login_allows_a_retry(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        fake = FakeArloAuth(rsps)
        login = _login(tmp_path)

        assert await login.start() == LoginStep.NEEDS_FACTOR
        assert await login.choose_factor("fid-email") == LoginStep.AWAITING_CODE
        assert await login.submit_code("000000") == LoginStep.AWAITING_CODE
        assert await login.submit_code(" 123456 ") == LoginStep.SUCCESS

    assert fake.started[0]["factorType"] == "BROWSER"
    assert fake.paired == 1


@pytest.mark.asyncio
async def test_interactive_push_denied(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        FakeArloAuth(rsps, push_answer="deny")
        login = _login(tmp_path)
        assert await login.start() == LoginStep.NEEDS_FACTOR
        assert await login.choose_factor("fid-push-1") == LoginStep.AWAITING_PUSH
        assert await login.poll_push() == LoginStep.FAILED
        assert "denied" in login.last_error


@pytest.mark.asyncio
async def test_interactive_push_times_out(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        FakeArloAuth(rsps, push_answer="never")
        login = _login(tmp_path, tfa_push_timeout=0)
        assert await login.start() == LoginStep.NEEDS_FACTOR
        assert await login.choose_factor("fid-push-1") == LoginStep.AWAITING_PUSH
        assert await login.poll_push() == LoginStep.FAILED
        assert "not approved in time" in login.last_error


@pytest.mark.asyncio
async def test_interactive_trusted_browser_needs_no_factor(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        fake = FakeArloAuth(rsps, trusted=True)
        login = _login(tmp_path)
        assert await login.start() == LoginStep.SUCCESS
    assert fake.signins == 1


@pytest.mark.asyncio
async def test_interactive_always_checks_the_password(tmp_path):
    session_file = tmp_path / "test_example_com.session"
    with open(session_file, "wb") as f:
        pickle.dump({"version": "2", "device_id": "d", "user_id": "u1", "web_id": "u1_web",
                     "sub_id": "subscriptions/u1_web", "token": "still-good",
                     "expires_in": str(int(time.time()) + 3600)}, f)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        fake = FakeArloAuth(rsps, trusted=True)
        login = _login(tmp_path)
        assert await login.start() == LoginStep.SUCCESS
    assert fake.signins == 1


@pytest.mark.asyncio
async def test_interactive_bad_password(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.OPTIONS, AUTH + "/api/auth", status=200)
        rsps.add(responses.POST, AUTH + "/api/auth", status=401)
        login = _login(tmp_path)
        assert await login.start() == LoginStep.FAILED
        assert login.last_error is not None


@pytest.mark.asyncio
async def test_interactive_unknown_factor(tmp_path):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        FakeArloAuth(rsps)
        login = _login(tmp_path)
        assert await login.start() == LoginStep.NEEDS_FACTOR
        assert await login.choose_factor("nope") == LoginStep.FAILED
