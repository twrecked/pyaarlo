import asyncio
import inspect
import os
import pickle
import pprint
import re
import uuid
import traceback

from http.cookiejar import LWPCookieJar
from typing import Any, Callable

from ...constant import (
    ORIGIN_HOST,
    REFERER_HOST,
    TRANSID_PREFIX,
)
from ...utils import (
    time_to_arlotime,
    to_b64,
)
from ..cfg import ArloCfg
from ..logger import ArloLogger


class ArloSessionDetails:
    """This holds everything needed for the current RESTAPI session with Arlo.

    It is built up during the authentication phase and remains unchanged
    during the non-authentication phase. It contains:
     - ids
     - tokens
     - the connection
     - cookies
    """
    def __init__(self):
        self.device_id: str | None = None
        self.user_id: str | None = None
        self.web_id: str | None = None
        self.sub_id: str | None = None
        self.token: str | None = None
        self.token64: str | None = None
        self.token_expires_in: int | None = None
        self.user_agent: str | None = None
        self.headers: dict[str, Any] = {}
        self.auth_headers: dict[str, Any] = {}

        # Connection Objects.
        self.connection: Any = None
        self.async_connection: Any = None
        self.cookies: LWPCookieJar | None = None


class ArloSession:
    """Helper class for ArloSessionDetails
    """

    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        self._cfg: ArloCfg = cfg
        self._log: ArloLogger = log

        self.details: ArloSessionDetails = ArloSessionDetails()

        self._lock = asyncio.Lock()
        self._login_lock: asyncio.Lock | None = None
        self._save_enabled = cfg.save_session
        self._save_filename = cfg.session_file
        self._save_username = cfg.username
        self._save_info: dict[str, dict[str, str]] | None = None
        self._relogin_handler: Callable[..., Any] | None = None
        self._is_logging_in: bool = False
        self._in_flight_count: int = 0
        self._drain_event: asyncio.Event = asyncio.Event()
        self._drain_event.set()
        self._requests: dict[str, Any] = {}
        self._requests_empty_event: asyncio.Event = asyncio.Event()
        self._requests_empty_event.set()

    def set_relogin_handler(self, handler: Callable[..., Any] | None) -> None:
        self._relogin_handler = handler

    def set_login_lock(self, lock: asyncio.Lock | None) -> None:
        self._login_lock = lock

    async def drain_in_flight(self, timeout: float = 3.0) -> None:
        """Wait for currently in-flight non-auth requests to complete."""
        if self._in_flight_count <= 0:
            return
        self._debug(f"draining {self._in_flight_count} in-flight request(s)")
        try:
            await asyncio.wait_for(self._drain_event.wait(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            self._debug(f"draining timed out, {self._in_flight_count} request(s) still in-flight")

    def start_transaction(self, tid: str | None = None) -> str:
        """Start tracking a new transaction awaiting an event stream reply."""
        if tid is None:
            tid = f"{TRANSID_PREFIX}!{uuid.uuid4()}"
        self._vdebug(f"starting transaction-->{tid}")
        self._requests[tid] = {"event": asyncio.Event(), "response": None}
        self._requests_empty_event.clear()
        return tid

    async def wait_for_transaction(self, tid: str, timeout: float | None = None) -> Any:
        """Wait for a tracked transaction to receive its event stream reply."""
        if timeout is None:
            timeout = self._cfg.request_timeout

        self._vdebug(f"finishing transaction-->{tid}")
        response = None
        try:
            req = self._requests.get(tid)
            if req is not None:
                await asyncio.wait_for(req["event"].wait(), timeout)
                response = self._requests.pop(tid, {}).get("response")
            else:
                self._debug(f"transaction {tid} not found")
        except (asyncio.TimeoutError, TimeoutError):
            self._debug(f"transaction {tid} timed out")
            self._requests.pop(tid, None)
            response = None
        finally:
            if not self._requests:
                self._requests_empty_event.set()
        self._vdebug(f"finished transaction-->{tid}")
        return response

    def signal_transaction_completed(self, response: dict[str, Any]) -> bool:
        """Match an incoming stream event packet to waiting transactions.

        Sets the response and signals the waiting event.
        Returns True if matched, False otherwise.
        """
        tid = response.get("transId", None)
        resource = response.get("resource", None)
        device_id = response.get("from", None)
        matched = False

        # Transaction ID: usually returned by notify requests
        if tid and tid in self._requests:
            req = self._requests[tid]
            req["response"] = response
            req["event"].set()
            matched = True

        # Resource: usually returned after POST requests
        if resource:
            if resource in self._requests:
                self._vdebug(f"{resource} found by text!")
                req = self._requests[resource]
                req["response"] = response
                req["event"].set()
                matched = True
            else:
                if device_id:
                    bounded_resource = f"{resource}:{device_id}"
                    self._vdebug(f"{bounded_resource} bounded device!")
                else:
                    bounded_resource = resource

                for request_pattern, req in list(self._requests.items()):
                    if re.match(request_pattern, bounded_resource):
                        self._vdebug(
                            f"{bounded_resource} found by regex {request_pattern}!"
                        )
                        req["response"] = response
                        req["event"].set()
                        matched = True

        return matched

    async def drain_transactions(self, timeout: float = 5.0) -> None:
        """Wait for any pending stream transaction events to arrive."""
        if not self._requests:
            return
        self._debug(f"draining {len(self._requests)} pending transaction(s)")
        try:
            await asyncio.wait_for(self._requests_empty_event.wait(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            self._debug(f"draining transactions timed out, {len(self._requests)} still pending")

    def cancel_transactions(self) -> None:
        """Cancel and unblock any waiting transactions (e.g. on stream stop or disconnect)."""
        if not self._requests:
            return
        self._debug(f"cancelling {len(self._requests)} pending transaction(s)")
        for tid, req in list(self._requests.items()):
            req["response"] = None
            req["event"].set()
        self._requests.clear()
        self._requests_empty_event.set()

    async def drain(self, in_flight_timeout: float = 2.0, transactions_timeout: float = 5.0) -> None:
        """Drain in-flight HTTP requests and pending stream transactions."""
        await self.drain_in_flight(timeout=in_flight_timeout)
        await self.drain_transactions(timeout=transactions_timeout)


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

    async def load(self):

        # Clear out what we have.
        self.details.device_id = None
        self.details.user_id = None
        self.details.web_id = None
        self.details.sub_id = None
        self.details.token = None
        self.details.token_expires_in = 0
        self.details.token64 = None

        try:
            def _do_load():
                with open(self._save_filename, "rb") as dump:
                    return pickle.load(dump)

            self._save_info = await asyncio.to_thread(_do_load)

            # Read in values.
            self.details.device_id = self._save_info["device_id"]
            self.details.user_id = self._save_info["user_id"]
            self.details.web_id = self._save_info["web_id"]
            self.details.sub_id = self._save_info["sub_id"]
            self.details.token = self._save_info["token"]
            self.details.token_expires_in = int(self._save_info["expires_in"])
            # Build remaining.
            self.details.token64 = to_b64(self.details.token)
            self._debug(f"load saved={self._save_info}")
            self._debug(f"load toke64={self.details.token64}")

        except Exception:
            self._debug("session file not read")
            self._save_info = {
                "version": "2",
            }

    async def save(self):
        try:
            def _do_save():
                if self._save_filename:
                    os.makedirs(os.path.dirname(self._save_filename), exist_ok=True)
                with open(self._save_filename, "wb") as dump:
                    save_info = {
                        "version": "2",
                        "device_id": self.details.device_id,
                        "user_id": self.details.user_id,
                        "web_id": self.details.web_id,
                        "sub_id": self.details.sub_id,
                        "token": self.details.token,
                        "expires_in": str(self.details.token_expires_in),
                    }
                    # noinspection PyTypeChecker
                    pickle.dump(save_info, dump)
                    return save_info

            self._save_info = await asyncio.to_thread(_do_save)
            self._debug(f"save session_info={self._save_info}")
        except Exception as e:
            self._debug(f"session file not written {str(e)}")

    async def save_cookies(self):
        if self.details.cookies is not None:
            for conn in (self.details.connection, self.details.async_connection):
                if conn is not None and hasattr(conn, "cookies"):
                    jar = getattr(conn.cookies, "jar", conn.cookies)
                    if jar is not self.details.cookies and hasattr(jar, "__iter__"):
                        for cookie in jar:
                            self.details.cookies.set_cookie(cookie)
            self._debug(f"saving-cookies={self.details.cookies}")
            try:
                def _do_save_cookies():
                    if self.details.cookies is not None and self.details.cookies.filename:
                        os.makedirs(os.path.dirname(self.details.cookies.filename), exist_ok=True)
                        self.details.cookies.save(ignore_discard=True)

                await asyncio.to_thread(_do_save_cookies)
            except Exception as e:
                self._debug(f"cookies file not written {str(e)}")

    async def load_cookies(self):
        self.details.cookies = LWPCookieJar(self._cfg.cookies_file)
        try:
            await asyncio.to_thread(self.details.cookies.load, ignore_discard=True)
        except Exception as _e:
            pass
        self._debug(f"loading cookies={self.details.cookies}")
        if self.details.connection is not None and hasattr(self.details.connection, "cookies"):
            if hasattr(self.details.connection.cookies, "jar"):
                self.details.connection.cookies.jar = self.details.cookies
            else:
                self.details.connection.cookies = self.details.cookies
        if self.details.async_connection is not None and hasattr(self.details.async_connection, "cookies"):
            if hasattr(self.details.async_connection.cookies, "jar"):
                self.details.async_connection.cookies.jar = self.details.cookies
            else:
                self.details.async_connection.cookies = self.details.cookies

    def auth_headers(self) -> dict[str, Any]:
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
            "User-Agent": self.details.user_agent or "",
            "X-Service-Version": "v3",
            "X-User-Device-Automation-Name": "QlJPV1NFUg==",
            "X-User-Device-Id": self.details.device_id or "",
            "X-User-Device-Type": "BROWSER",
        }

        # Add Source if asked for.
        if self._cfg.send_source:
            self.details.auth_headers.update({
                "Source": "arloCamWeb",
            })

        return self.details.auth_headers

    def headers(self) -> dict[str, Any]:
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
            "Authorization": self.details.token or "",
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
            "User-Agent": self.details.user_agent or "",
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
        auth_data = body.get("accessToken", body)

        # Trap disabled MFA state and mark auth complete to skip 2FA
        mfa_state = str(auth_data.get("MFA_State", body.get("MFA_State", ""))).upper()
        mfa = auth_data.get("mfa", body.get("mfa", None))
        if mfa_state in ("DISABLED", "NONE") or mfa is False:
            self._debug(
                f"MFA is disabled (MFA_State={mfa_state}, mfa={mfa}), skipping 2FA"
            )
            body["authCompleted"] = True
            if "accessToken" in body and isinstance(body["accessToken"], dict):
                body["accessToken"]["authCompleted"] = True

        # If we have this we have to drop down a level.
        if "accessToken" in body:
            body = body["accessToken"]

        self.details.token = body["token"]
        self.details.user_id = body["userId"]
        self.details.token_expires_in = body["expiresIn"]

        self.details.token64 = to_b64(self.details.token)
        self.details.web_id = self.details.user_id + "_web"
        self.details.sub_id = "subscriptions/" + self.details.web_id

    async def _request_tuple_impl(
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
            cookies=None,
            retry_401=True,
    ):
        if params is None:
            params = {}
        if headers is None:
            headers = {}
        if timeout is None:
            timeout = self._cfg.request_timeout

        try:
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

            async with self._lock:
                if self.details.async_connection:
                    if method == "GET":
                        r = await self.details.async_connection.get(
                            url,
                            params=params,
                            headers=headers,
                            stream=stream,
                            timeout=timeout,
                            cookies=cookies,
                        )
                        if stream is True:
                            r_or_tuple = 200, r
                        else:
                            r_or_tuple = r
                    elif method == "PUT":
                        r_or_tuple = await self.details.async_connection.put(
                            url, json=params, headers=headers, timeout=timeout, cookies=cookies,
                        )
                    elif method == "POST":
                        r_or_tuple = await self.details.async_connection.post(
                            url, json=params, headers=headers, timeout=timeout, cookies=cookies,
                        )
                    elif method == "OPTIONS":
                        await self.details.async_connection.options(
                            url, json=params, headers=headers, timeout=timeout
                        )
                        r_or_tuple = 200, None
                    else:
                        r_or_tuple = 500, None
                else:
                    # Use run_in_executor to keep cloudscraper (which is blocking) from blocking the event loop
                    def _do_request():
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
                        return r

                    r_or_tuple = await asyncio.get_running_loop().run_in_executor(None, _do_request)

            if isinstance(r_or_tuple, tuple):
                return r_or_tuple
            r = r_or_tuple

        except Exception as e:
            self._log.warning("request-error={}".format(type(e).__name__))
            self._log.warning(traceback.format_exc())
            return 500, None

        try:
            if "application/json" in r.headers.get("Content-Type", ""):
                body = r.json()
            else:
                body = r.text
            self._vdebug("request-body=\n{}".format(pprint.pformat(body)))
        except Exception as e:
            self._log.warning("body-error={}".format(type(e).__name__))
            self._debug(f"request-text={r.text}")
            if r.status_code == 401 and not authpost and retry_401 and not self._is_logging_in:
                self._log.warning(f"request returned 401 Unauthorized for {path}, attempting re-login and retry")
                if self._relogin_handler is not None:
                    res = self._relogin_handler()
                    if await res if inspect.isawaitable(res) else res:
                        return await self.request_tuple(
                            path=path,
                            method=method,
                            params=params,
                            headers=headers,
                            stream=stream,
                            raw=raw,
                            timeout=timeout,
                            host=host,
                            authpost=authpost,
                            cookies=cookies,
                            retry_401=False,
                        )
            return r.status_code if r.status_code != 200 else 500, None

        self._vdebug("request-end={}".format(r.status_code))
        if r.status_code != 200:
            if r.status_code == 401 and not authpost and retry_401 and not self._is_logging_in:
                self._log.warning(f"request returned 401 Unauthorized for {path}, attempting re-login and retry")
                if self._relogin_handler is not None:
                    res = self._relogin_handler()
                    if await res if inspect.isawaitable(res) else res:
                        return await self.request_tuple(
                            path=path,
                            method=method,
                            params=params,
                            headers=headers,
                            stream=stream,
                            raw=raw,
                            timeout=timeout,
                            host=host,
                            authpost=authpost,
                            cookies=cookies,
                            retry_401=False,
                        )
            return r.status_code, None

        if raw:
            return 200, body

        if not isinstance(body, dict):
            return 500, None

        # New auth style and TFA helper
        if "meta" in body:
            if body["meta"]["code"] == 200:
                return 200, body["data"]
            else:
                meta_code = int(body["meta"]["code"])
                if (meta_code == 401 or body["meta"].get("error") == 9204) and not authpost and retry_401 and not self._is_logging_in:
                    self._log.warning(f"response meta error {body['meta'].get('error')} for {path}, attempting re-login and retry")
                    if self._relogin_handler is not None:
                        res = self._relogin_handler()
                        if await res if inspect.isawaitable(res) else res:
                            return await self.request_tuple(
                                path=path,
                                method=method,
                                params=params,
                                headers=headers,
                                stream=stream,
                                raw=raw,
                                timeout=timeout,
                                host=host,
                                authpost=authpost,
                                cookies=cookies,
                                retry_401=False,
                            )
                # don't warn on untrusted errors, they just mean we need to log in
                if body["meta"]["error"] != 9204:
                    self._log.warning("error in new response=" + str(body))
                return meta_code, body["meta"]["message"]

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

    async def request_tuple(
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
            cookies=None,
            retry_401=True,
    ) -> tuple[int, Any]:
        if headers is None:
            headers = {}

        if not authpost and self._is_logging_in and self._login_lock is not None:
            self._debug("waiting for active login/token renewal to complete")
            async with self._login_lock:
                pass
            if "Authorization" in headers:
                headers["Authorization"] = str(self.details.token64 or "")

        is_tracked = not authpost
        if is_tracked:
            self._in_flight_count += 1
            self._drain_event.clear()

        try:
            return await self._request_tuple_impl(
                path=path,
                method=method,
                params=params,
                headers=headers,
                stream=stream,
                raw=raw,
                timeout=timeout,
                host=host,
                authpost=authpost,
                cookies=cookies,
                retry_401=retry_401,
            )
        finally:
            if is_tracked:
                self._in_flight_count -= 1
                if self._in_flight_count <= 0:
                    self._in_flight_count = 0
                    self._drain_event.set()

    async def request(
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
            cookies=None,
            retry_401=True,
    ):
        code, body = await self.request_tuple(path=path, method=method, params=params, headers=headers,
                                              stream=stream, raw=raw, timeout=timeout, host=host, authpost=authpost, cookies=cookies, retry_401=retry_401)
        return body if code == 200 else None


