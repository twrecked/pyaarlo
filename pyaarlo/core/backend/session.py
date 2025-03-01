from __future__ import annotations

import pickle
import pprint
import uuid
import threading
import cloudscraper
from http.cookiejar import LWPCookieJar

from ...constant import (
    ORIGIN_HOST,
    REFERER_HOST,
)
from ...utils import (
    time_to_arlotime,
    to_b64,
)
from ..cfg import ArloCfg
from ..logger import ArloLogger


class ArloSessionDetails:
    """This holds everything needed for the current RESTAPI session with Arlo.

    It is built up during the authentication phase and remains constistent
    during the non-authentication phase. It contains:
     - ids
     - tokens
     - the connection
     - cookies
    """
    # Session objects.
    device_id: str | None = None
    user_id: str | None = None
    web_id: str | None = None
    sub_id: str | None = None
    token: str | None = None
    token64: str | None = None
    token_expires_in: int | None = None
    user_agent: str | None = None
    headers: dict[str, str]
    auth_headers: dict[str, str]

    # Connection Objects.
    connection: cloudscraper.CloudScraper | None = None
    cookies: LWPCookieJar | None = None


class ArloSession:
    """Helper class for ArloSessionDetails
    """
    # Session details.
    details: ArloSessionDetails

    # Core objects.
    _cfg: ArloCfg | None = None
    _log: ArloLogger | None = None

    # Internal state/fields for the object.
    _lock = threading.Lock()
    _save_info: dict[str, {str, str}] | None = {}
    _save_enabled: bool = True
    _save_filename: str | None = None
    _save_username: str | None = None

    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        self.details = ArloSessionDetails()

        self._cfg = cfg
        self._log = log

        self._save_enabled = cfg.save_session
        self._save_filename = cfg.session_file
        self._save_username = cfg.username

    def _debug(self, msg: str):
        self._log.debug(f"session: {msg}")

    def _vdebug(self, msg: str):
        self._log.vdebug(f"session: {msg}")

    def _transaction_id(self):
        return 'FE!' + str(uuid.uuid4())

    def _build_url(self, url, tid):
        sep = "&" if "?" in url else "?"
        now = time_to_arlotime()
        return f"{url}{sep}eventId={tid}&time={now}"

    def load(self):

        # Clear out what we have.
        self.details.device_id = None
        self.details.user_id = None
        self.details.web_id = None
        self.details.sub_id = None
        self.details.token = None
        self.details.token_expires_in = 0
        self.details.token64 = None

        try:
            with open(self._save_filename, "rb") as dump:
                ArloSession._save_info = pickle.load(dump)
                session_info: dict[str, {str, str}] | None = ArloSession._save_info.get(self._save_username, None)
                if session_info is not None:
                    # Read in values.
                    self.details.device_id = session_info["device_id"]
                    self.details.user_id = session_info["user_id"]
                    self.details.web_id = session_info["web_id"]
                    self.details.sub_id = session_info["sub_id"]
                    self.details.token = session_info["token"]
                    self.details.token_expires_in = int(session_info["expires_in"])
                    # Build remaining.
                    self.details.token64 = to_b64(self.details.token)
                    self._debug(f"load saved={ArloSession._save_info}")
                    self._debug(f"load toke64={self.details.token64}")
                else:
                    self._debug("load failed")
        except Exception:
            self._debug("session file not read")
            ArloSession._save_info = {
                "version": "2",
            }

    def save(self):
        try:
            with open(self._save_filename, "wb") as dump:
                ArloSession._save_info[self._save_username] = {
                    "device_id": self.details.device_id,
                    "user_id": self.details.user_id,
                    "web_id": self.details.web_id,
                    "sub_id": self.details.sub_id,
                    "token": self.details.token,
                    "expires_in": str(self.details.token_expires_in),
                }
                # noinspection PyTypeChecker
                pickle.dump(ArloSession._save_info, dump)
                self._debug(f"save session_info={ArloSession._save_info}")
        except Exception as e:
            self._debug(f"session file not written {str(e)}")

    def save_cookies(self):
        if self.details.cookies is not None:
            self._debug(f"saving-cookies={self.details.cookies}")
            self.details.cookies.save(ignore_discard=True)

    def load_cookies(self):
        self.details.cookies = LWPCookieJar(self._cfg.cookies_file)
        try:
            self.details.cookies.load()
        except Exception as _e:
            pass
        self._debug(f"loading cookies={self.details.cookies}")

    def auth_headers(self) -> dict[str, str]:
        """Build headers needed for authentication phase.

        This list was determined by packet inspection when logging onto the
        my.arlo.com website. We need to keep it as close as possible. The
        commented out code is still being passed by the web browser we just
        don't seem to need it, I left it in to make adding it back easier.

        Note, we add and update an 'Authentication' field as the login process
        progresses.
        """
        self.details.auth_headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            # "Dnt": "1",
            "Origin": ORIGIN_HOST,
            "Pragma": "no-cache",
            "Priority": "u=1, i",
            "Referer": REFERER_HOST,
            # "Sec-Ch-Ua": '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
            # "Sec-Ch-Ua-Mobile": "?0",
            # "Sec-Ch-Ua-Platform": "Linux",
            # "Sec-Fetch-Dest": "empty",
            # "Sec-Fetch-Mode": "cors",
            # "Sec-Fetch-Site": "same-site",
            "User-Agent": self.details.user_agent,
            "X-Service-Version": "v3",
            "X-User-Device-Automation-Name": "QlJPV1NFUg==",
            "X-User-Device-Id": self.details.device_id,
            "X-User-Device-Type": "BROWSER",
        }

        # Add Source if asked for.
        if self._cfg.send_source:
            self.details.auth_headers.update({
                "Source": "arloCamWeb",
            })

        return self.details.auth_headers

    def headers(self) -> dict[str, str]:
        """Build headers needed for post-authentication phase.

        This list was determined by packet inspection when logging onto the
        my.arlo.com website. We need to keep it as close as possible. The
        commented out code is still being passed by the web browser we just
        don't seem to need it, I left it in to make adding it back easier.

        This list is built immediately after a successful authentication and
        doesn't change until we reauthenticate.
        """

        self.details.headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
            "Auth-Version": "2",
            "Authorization": self.details.token,
            "Cache-Control": "no-cache",
            "Content-Type": "application/json; charset=utf-8;",
            # "Dnt": "1",
            "Origin": ORIGIN_HOST,
            "Pragma": "no-cache",
            "Priority": "u=1, i",
            "Referer": REFERER_HOST,
            "SchemaVersion": "1",
            # "Sec-Ch-Ua": '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
            # "Sec-Ch-Ua-Mobile": "?0",
            # "Sec-Ch-Ua-Platform": "Linux",
            # "Sec-Fetch-Dest": "empty",
            # "Sec-Fetch-Mode": "cors",
            # "Sec-Fetch-Site": "same-site",
            "User-Agent": self.details.user_agent,
        }
        return self.details.headers

    def update(self, body):
        """Update session details from the packet body passed.

        What we grab is:
         - token
         - our usedID
         - when the token expires

        What we create is:
         - token converted to base64
         - our web id
         - our subscription id
        """

        # If we have this we have to drop down a level.
        if "accessToken" in body:
            body = body["accessToken"]

        self.details.token = body["token"]
        self.details.user_id = body["userId"]
        self.details.token_expires_in = body["expiresIn"]

        self.details.token64 = to_b64(self.details.token)
        self.details.web_id = self.details.user_id + "_web"
        self.details.sub_id = "subscriptions/" + self.details.web_id

    def request_tuple(
            self,
            path,
            method="GET",
            params=None,
            headers=None,
            stream=False,
            raw=False,
            timeout=None,
            host=None,
            authpost=False,
            cookies=None
    ):
        if params is None:
            params = {}
        if headers is None:
            headers = {}
        if timeout is None:
            timeout = self._cfg.request_timeout
        try:
            with self._lock:
                if host is None:
                    host = self._cfg.host
                if authpost:
                    url = host + path
                else:
                    tid = self._transaction_id()
                    url = self._build_url(host + path, tid)
                    headers['x-transaction-id'] = tid

                self._vdebug("request-url={}".format(url))
                self._vdebug("request-params=\n{}".format(pprint.pformat(params)))
                self._vdebug("request-headers=\n{}".format(pprint.pformat(headers)))

                if method == "GET":
                    r = self.details.connection.get(
                        url,
                        params=params,
                        headers=headers,
                        stream=stream,
                        timeout=timeout,
                        cookies=cookies,
                    )
                    if stream is True:
                        return 200, r
                elif method == "PUT":
                    r = self.details.connection.put(
                        url, json=params, headers=headers, timeout=timeout, cookies=cookies,
                    )
                elif method == "POST":
                    r = self.details.connection.post(
                        url, json=params, headers=headers, timeout=timeout, cookies=cookies,
                    )
                elif method == "OPTIONS":
                    self.details.connection.options(
                        url, json=params, headers=headers, timeout=timeout
                    )
                    return 200, None
        except Exception as e:
            self._log.warning("request-error={}".format(type(e).__name__))
            return 500, None

        try:
            if "application/json" in r.headers["Content-Type"]:
                body = r.json()
            else:
                body = r.text
            self._vdebug("request-body=\n{}".format(pprint.pformat(body)))
        except Exception as e:
            self._log.warning("body-error={}".format(type(e).__name__))
            self._debug(f"request-text={r.text}")
            return 500, None

        self._vdebug("request-end={}".format(r.status_code))
        if r.status_code != 200:
            return r.status_code, None

        if raw:
            return 200, body

        # New auth style and TFA helper
        if "meta" in body:
            if body["meta"]["code"] == 200:
                return 200, body["data"]
            else:
                # don't warn on untrusted errors, they just mean we need to log in
                if body["meta"]["error"] != 9204:
                    self._log.warning("error in new response=" + str(body))
                return int(body["meta"]["code"]), body["meta"]["message"]

        # Original response type
        elif "success" in body:
            if body["success"]:
                if "data" in body:
                    return 200, body["data"]
                # success, but no data so fake empty data
                return 200, {}
            else:
                self._log.warning("error in response=" + str(body))

        return 500, None

    def request(
            self,
            path,
            method="GET",
            params=None,
            headers=None,
            stream=False,
            raw=False,
            timeout=None,
            host=None,
            authpost=False,
            cookies=None
    ):
        code, body = self.request_tuple(path=path, method=method, params=params, headers=headers,
                                        stream=stream, raw=raw, timeout=timeout, host=host, authpost=authpost, cookies=cookies)
        return body

