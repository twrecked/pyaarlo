from unittest import TestCase
from unittest.mock import MagicMock, patch

from pyaarlo.backend import ArloBackEnd, AuthResult
from pyaarlo.constant import AUTH_FINISH_PATH, AUTH_GET_FACTORID, AUTH_PATH, AUTH_START_PATH
import tests.arlo


class TestPushAuth(TestCase):
    """The push-approval poll stops on answers that more polling cannot change."""

    def _backend(self, finish_answers):
        be = ArloBackEnd.__new__(ArloBackEnd)
        be._arlo = tests.arlo.PyArlo(username="user@example.com", password="secret", tfa_source="push",
                                     tfa_type="PUSH", tfa_retries=10, tfa_delay=1)
        be.debug = be._arlo.debug
        be._cookies = None
        be._user_agent = "test"
        be.auth_options = MagicMock(return_value=None)
        be.auth_get = MagicMock(return_value={"items": [{"factorType": "PUSH", "factorNickname": "phone", "factorId": "f1"}]})
        answers = iter(finish_answers)
        self.finish_calls = 0

        def auth_post(path, params=None, headers=None, raw=False, timeout=None, cookies=None):
            if path == AUTH_PATH:
                return 200, {"authCompleted": False, "token": "dG9rZW4=", "userId": "u1", "expiresIn": 3600, "mfa": True}
            if path == AUTH_GET_FACTORID:
                return 400, "browser not trusted"
            if path == AUTH_START_PATH:
                return 200, {"factorAuthCode": "code"}
            if path == AUTH_FINISH_PATH:
                self.finish_calls += 1
                return next(answers)
            raise AssertionError(path)

        be.auth_post = auth_post
        return be

    @patch("pyaarlo.backend.time.sleep")
    def test_pending_answers_keep_polling_until_approved(self, _sleep):
        pending = (400, "Authentication is not finished yet")
        be = self._backend([pending, pending, (200, {"token": "dG9rZW4=", "userId": "u1", "expiresIn": 3600,
                                                      "authCompleted": True})])
        self.assertEqual(be._auth(), AuthResult.SUCCESS)
        self.assertEqual(self.finish_calls, 3)

    @patch("pyaarlo.backend.time.sleep")
    def test_too_many_requests_stops_polling_at_once(self, _sleep):
        be = self._backend([(400, "Too many requests")] * 10)
        self.assertEqual(be._auth(), AuthResult.FAILED)
        self.assertEqual(self.finish_calls, 1)
        self.assertIn("rate limiting", be._arlo.last_error)

    @patch("pyaarlo.backend.time.sleep")
    def test_an_expired_request_stops_polling(self, _sleep):
        be = self._backend([(400, "Maximum permitted time for authentication exceeded")] * 10)
        self.assertEqual(be._auth(), AuthResult.FAILED)
        self.assertEqual(self.finish_calls, 1)
