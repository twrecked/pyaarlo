from unittest import TestCase
from unittest.mock import MagicMock
from pyaarlo.backend import ArloBackEnd
import tests.arlo


class TestArloAuth(TestCase):

    def _create_backend(self):
        be = ArloBackEnd.__new__(ArloBackEnd)
        be._arlo = tests.arlo.PyArlo()
        be.debug = be._arlo.debug
        return be

    def test_update_auth_info_mfa_enabled(self):
        be = self._create_backend()
        body = {
            "MFA_State": "ENABLED",
            "mfa": True,
            "authCompleted": False,
            "token": "test-token",
            "userId": "test-user",
            "expiresIn": 3600,
        }
        be._update_auth_info(body)
        self.assertFalse(body["authCompleted"])
        self.assertEqual(be._token, "test-token")
        self.assertEqual(be._user_id, "test-user")

    def test_update_auth_info_mfa_state_disabled(self):
        be = self._create_backend()
        body = {
            "MFA_State": "DISABLED",
            "mfa": True,
            "authCompleted": False,
            "token": "test-token",
            "userId": "test-user",
            "expiresIn": 3600,
        }
        be._update_auth_info(body)
        self.assertTrue(body["authCompleted"])

    def test_update_auth_info_mfa_false(self):
        be = self._create_backend()
        body = {
            "MFA_State": "ENABLED",
            "mfa": False,
            "authCompleted": False,
            "token": "test-token",
            "userId": "test-user",
            "expiresIn": 3600,
        }
        be._update_auth_info(body)
        self.assertTrue(body["authCompleted"])

    def test_update_auth_info_nested_access_token(self):
        be = self._create_backend()
        body = {
            "authCompleted": False,
            "accessToken": {
                "MFA_State": "DISABLED",
                "mfa": True,
                "authCompleted": False,
                "token": "test-token",
                "userId": "test-user",
                "expiresIn": 3600,
            },
        }
        be._update_auth_info(body)
        self.assertTrue(body["authCompleted"])
        self.assertTrue(body["accessToken"]["authCompleted"])

    def test_request_returns_none_on_error(self):
        be = self._create_backend()
        be._request_tuple = MagicMock(return_value=(400, "Mfa disabled by service"))
        res = be._request("/dummy")
        self.assertIsNone(res)

    def test_request_returns_body_on_success(self):
        be = self._create_backend()
        be._request_tuple = MagicMock(return_value=(200, {"data": "ok"}))
        res = be._request("/dummy")
        self.assertEqual(res, {"data": "ok"})
