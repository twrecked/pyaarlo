import asyncio
import inspect
import pprint
import time
import uuid
import cloudscraper

from enum import IntEnum
from typing import Any, Callable, cast

from ...constant import (
    AUTH_FINISH_PATH,
    AUTH_GET_FACTORID,
    AUTH_GET_FACTORS,
    AUTH_PATH,
    AUTH_START_PAIRING,
    AUTH_START_PATH,
    AUTH_VALIDATE_PATH,
    DEFAULT_RESOURCES,
    DEVICES_PATH,
    LOGOUT_PATH,
    MQTT_URL_KEY,
    NOTIFY_PATH,
    SESSION_PATH,
    TFA_PUSH_DENIED_ERROR,
    TFA_PUSH_TYPE,
    TRANSID_PREFIX,
)
from ...utils import now_strftime, time_to_arlotime, to_b64
from ..task_manager import ArloTaskManager
from ..cfg import ArloCfg
from ..logger import ArloLogger
from .event import ArloEvent
from .session import ArloSession
from .tfa import ArloTFA


class _AuthState(IntEnum):
    STARTING = 0,
    SUCCESS = 1,
    FAILED = 2,
    LOGIN = 3,
    CURRENT_FACTOR_ID = 4,
    TRUSTED_AUTH = 6,
    NEW_AUTH = 7,
    FINISH_NEW_AUTH = 8,
    VALIDATE_TOKEN = 9,
    TRUST_BROWSER = 10,
    REVALIDATE_TOKEN = 11,


class _FinishResult(IntEnum):
    """What a single finishAuth call told us."""
    SUCCESS = 0
    PENDING = 1
    DENIED = 2
    FINAL = 3


class LoginStep(IntEnum):
    """Where an interactive `login_*` call has left the login.

    `SUCCESS` - logged in, the session and cookies are saved.
    `NEEDS_FACTOR` - call `login_choose_factor()` with one of `login_factors`.
    `AWAITING_PUSH` - call `login_poll_push()` again in `tfa_push_poll`
      seconds, until it stops returning this.
    `AWAITING_CODE` - call `login_submit_code()` with the code the user typed.
    `FAILED` - could not log in, see the logger's `last_error`.
    """
    FAILED = 0
    SUCCESS = 1
    NEEDS_FACTOR = 2
    AWAITING_PUSH = 3
    AWAITING_CODE = 4


class _InteractiveDetails:
    """State for an interactive login driven by the `login_*` methods.
    """
    def __init__(self):
        self.factors: list[dict[str, Any]] = []
        self.factor: dict[str, Any] | None = None
        self.factor_auth_code: str | None = None
        self.push_deadline: float = 0.0


class _AuthDetails:
    """This hold the authentication state.
    """
    def __init__(self):
        self.state: _AuthState = _AuthState.STARTING
        self.headers: dict[str, Any] = {}
        self.browser_code = None
        self.factor_id: str | None = None
        self.needs_pairing: bool = False
        self.tfa_handler: ArloTFA | None = None
        self.attempt: int = 1
        self.curves: list[str] = []
        self.force_reauth: bool = False
        self.was_reused_from_disk: bool = False


class _EventDetails:
    """This tracks the event stream state.
    """
    def __init__(self):
        self.loop_exiting: bool = False
        self.loop_task: asyncio.Task[Any] | None = None
        self.stream: ArloEvent | None = None
        self.stream_connected: bool = False


# include token and session details


def _flatten_intelligence_events(grouped: Any, location_id: str) -> list[dict[str, Any]]:
    """Flatten list- or dict-shaped groupByEvents responses."""
    records: list[dict[str, Any]] = []
    event_keys = {
        "harlem", "feedId", "feedID", "recordingId", "mediaId", "utcCreatedDate",
        "eventTime", "timestamp", "createdAt", "description", "aiDescription",
        "smartDescription", "eventDescription",
    }

    def walk(value: Any, event_id: Any = None, device_id: Any = None) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item, event_id, device_id)
            return
        if not isinstance(value, dict):
            return
        keys = set(value)
        if keys & event_keys and ("harlem" in keys or keys & {
            "feedId", "feedID", "recordingId", "mediaId", "utcCreatedDate",
            "eventTime", "timestamp", "createdAt",
        }):
            item = dict(value)
            if event_id is not None:
                item.setdefault("eventId", event_id)
            item.setdefault("locationId", location_id)
            if device_id is not None:
                item.setdefault("deviceId", device_id)
            records.append(item)
            return
        for key, child in value.items():
            child_event_id = event_id
            child_device_id = device_id
            if event_id is None:
                child_event_id = key
            elif device_id is None and isinstance(key, str):
                child_device_id = key
            walk(child, child_event_id, child_device_id)

    walk(grouped)
    return records

class ArloBackEnd:

    def __init__(self, cfg: ArloCfg, log: ArloLogger, tasks: ArloTaskManager):
        self._cfg: ArloCfg = cfg
        self._log: ArloLogger = log
        self._tasks: ArloTaskManager = tasks

        # These affect how we talk to the backend.
        self._logged_in: bool = False
        self._multi_location: bool = False

        # This holds the request state.
        self._req: ArloSession = ArloSession(cfg, log)

        # This holds the auth details and state.
        self._auth: _AuthDetails = _AuthDetails()
        self._interactive: _InteractiveDetails = _InteractiveDetails()

        # The event stream.
        self._event: _EventDetails = _EventDetails()

        # Remaining state variables.
        self._dump_file = self._cfg.dump_file
        self._callbacks: dict[str, list[Callable[..., Any]]] = {}
        self._resource_types = DEFAULT_RESOURCES
        self._login_lock: asyncio.Lock = asyncio.Lock()
        self._last_login_time: float = 0.0
        self._reconnect_job: str | None = None
        self._mqtt_reconnect_attempts: int = 0
        self._req.set_relogin_handler(self._relogin)
        self._req.set_login_lock(self._login_lock)

    def _debug(self, msg: str) -> None:
        self._log.debug(f"backend: {msg}")

    def _vdebug(self, msg: str) -> None:
        self._log.vdebug(f"backend: {msg}")

    def _event_run_callbacks(self, response):
        """Run registered call backs.

        I'm trying to keep this as generic as possible... but it needs some
        smarts to figure out where to send responses - the packets from Arlo
        are anything but consistent...
        See docs/packets for and idea of what we're parsing.
        """

        responses = []
        resource = response.get("resource", "")

        err = response.get("error", None)
        if err is not None:
            self._log.info(
                "error: code="
                + str(err.get("code", "xxx"))
                + ",message="
                + str(err.get("message", "XXX"))
            )

        # Answer for async ping. Note and finish.
        # Packet type #1
        if resource.startswith("subscriptions/"):
            self._vdebug("packet: async ping response " + resource)
            return

        # These is a base station mode response. Find base station ID and
        # forward response.
        # Packet type #2
        if resource == "activeAutomations":
            self._debug("packet: base station mode response")
            for device_id in response:
                if device_id != "resource":
                    responses.append((device_id, resource, response[device_id]))

        # Mode update response
        # XXX these might be deprecated
        elif "states" in response:
            self._debug("packet: mode update")
            device_id = response.get("from", None)
            if device_id is not None:
                responses.append((device_id, "states", response["states"]))

        # These are individual device updates, they are usually used to signal
        # things like motion detection or temperature changes.
        # Packet type #3
        elif [x for x in self._resource_types if resource.startswith(x + "/")]:
            self._debug("packet: device update")
            device_id = resource.split("/")[1]
            responses.append((device_id, resource, response))

        # Base station its child device statuses. We split this apart here
        # and pass directly to the referenced devices.
        # Packet type #4
        elif resource == 'devices':
            self._debug("packet: base and child statuses")
            for device_id in response.get('devices', {}):
                self._debug(f"DEVICES={device_id}")
                props = response['devices'][device_id]
                responses.append((device_id, resource, props))

        # Base station status / wakeup responses
        elif resource == "basestation":
            self._debug("packet: basestation status/wakeup")
            from_id = response.get("from", None)
            props = response.get("properties", {})
            if isinstance(props, dict) and "devices" in props and isinstance(props["devices"], list):
                for dev_id in props["devices"]:
                    responses.append((dev_id, resource, response))
                if from_id and from_id not in props["devices"]:
                    responses.append((from_id, resource, response))
            elif isinstance(props, list):
                for prop in props:
                    dev_id = prop.get("serialNumber", from_id)
                    responses.append((dev_id, resource, prop))
            else:
                if from_id is not None:
                    responses.append((from_id, resource, response))

        # These are base station responses. Which can be about the base station
        # or devices on it... Check if property is list.
        # XXX these might be deprecated
        elif resource in self._resource_types:
            prop_or_props = response.get("properties", [])
            if isinstance(prop_or_props, list):
                for prop in prop_or_props:
                    device_id = prop.get("serialNumber", None)
                    if device_id is None:
                        device_id = response.get("from", None)
                    responses.append((device_id, resource, prop))
            else:
                device_id = response.get("from", None)
                responses.append((device_id, resource, response))

        # ArloBabyCam packets.
        elif resource.startswith("audioPlayback"):
            device_id = response.get("from")
            properties = response.get("properties")
            if resource == "audioPlayback/status":
                # Wrap the status event to match the 'audioPlayback' event
                properties = {"status": response.get("properties")}

            self._log.info(
                "audio playback response {} - {}".format(resource, response)
            )
            if device_id is not None and properties is not None:
                responses.append((device_id, resource, properties))

        # This a list ditch effort to funnel the answer the correct place...
        #  Check for device_id
        #  Check for unique_id
        #  Check for locationId
        # If none of those then is unhandled
        else:
            device_id = response.get(
                "deviceId",
                response.get(
                    "uniqueId",
                    response.get("locationId", response.get("from", None))
                )
            )
            if device_id is not None:
                responses.append((device_id, resource, response))
            else:
                self._debug(f"unhandled response {resource} - {response}")

        # Now find something waiting for this/these.
        for device_id, resource, response in responses:
            cbs = []
            self._debug("sending {} to {}".format(resource, device_id))
            # Thread-safe read of callbacks
            if device_id and device_id in self._callbacks:
                cbs.extend(self._callbacks[device_id])
            if "all" in self._callbacks:
                cbs.extend(self._callbacks["all"])
            for cb in cbs:
                self._tasks.run_now(cb, resource=resource, event=response)

    async def _event_response_handler(self, response):

        # Debugging.
        if self._dump_file is not None:
            with open(self._dump_file, "a") as dump:
                time_stamp = now_strftime("%Y-%m-%d %H:%M:%S.%f")
                dump.write(
                    "{}: {}\n".format(
                        time_stamp, pprint.pformat(response, indent=2)
                    )
                )
        self._vdebug(
            "packet-in=\n{}".format(pprint.pformat(response, indent=2))
        )

        # Run the dispatcher to set internal state and run callbacks.
        self._event_run_callbacks(response)

        # Notify any waiting post/notify transactions.
        self._req.signal_transaction_completed(response)

    async def _event_connected_handler(self):
        self._event.stream_connected = True
        self._debug("event connected")
        devices = await self.devices()
        return {"devices": devices}

    async def _event_reconnected_handler(self):
        self._debug("event re-connected")

    async def _event_reconnect(self):
        await self._event.stream.stop()

    async def _scheduled_token_renewal(self):
        self._debug("scheduled token renewal: starting graceful session rotation")
        async with self._login_lock:
            self._req._is_logging_in = True
            try:
                # 1. Drain pending HTTP calls on the wire and expected transactions
                await self._req.drain(in_flight_timeout=2.0, transactions_timeout=5.0)
                # 2. Stop stream now that transactions are drained
                await self._event_reconnect()
                # 3. Force fresh re-auth and login right now under the lock
                self._auth.force_reauth = True
                await self._login_locked()
            finally:
                self._req._is_logging_in = False

    async def _event_loop_stop(self):
        self._event.loop_exiting = True

    async def _event_loop(self):
        """The event stream loop.
        """
        self._debug("starting event loop")

        while not self._event.loop_exiting:

            # say we're starting
            if self._dump_file is not None:
                with open(self._dump_file, "a") as dump:
                    time_stamp = now_strftime("%Y-%m-%d %H:%M:%S.%f")
                    dump.write("{}: {}\n".format(time_stamp, "event_thread start"))

            # login again if not first iteration, this will also create a new session
            login_count = 0
            wait_time = 5
            while not self._logged_in and not self._event.loop_exiting:
                # While testing; hold off for an hour if too many failures.
                if login_count > 3:
                    wait_time = 360
                
                self._debug(f"re-logging in with time={wait_time}")

                # We have to run the async login in the loop
                self._logged_in = await self._login() and await self._session_finalize()

                if not self._logged_in and not self._event.loop_exiting:
                    # Sleep in small chunks to be interruptible
                    for _ in range(wait_time):
                        if self._event.loop_exiting:
                            break
                        await asyncio.sleep(1)
                    login_count += 1

            if self._event.loop_exiting:
                break

            # schedule next token renewal before starting event device
            self._schedule_token_renewal()

            self._debug("starting event device")
            await self._event.stream.run()
            self._debug("exited event device")

            # clear down and signal out
            self._req.cancel_transactions()

            # restart login...
            self._logged_in = False

    async def _auth_post(self, path, params=None, headers=None, raw=False, timeout=None, cookies=None):
        return await self._req.request_tuple(
            path, "POST", params, headers, False, raw, timeout, self._cfg.auth_host, authpost=True, cookies=cookies
        )

    async def _auth_get(
            self, path, params=None, headers=None, stream=False, raw=False, timeout=None, cookies=None
    ):
        return await self._req.request_tuple(
            path, "GET", params, headers, stream, raw, timeout, self._cfg.auth_host, authpost=True, cookies=cookies
        )

    async def _auth_options(
            self, path, headers=None, timeout=None
    ):
        return await self._req.request(
            path, "OPTIONS", None, headers, False, False, timeout, self._cfg.auth_host, authpost=True
        )

    @staticmethod
    def _describe_factor(factor: dict[str, Any]) -> str:
        """One line description of a 2fa factor, for logs."""
        return "{}/{} ({})".format(
            factor.get("factorType", "?"),
            factor.get("displayName") or factor.get("factorNickname") or "?",
            factor.get("factorId", "?"),
        )

    @staticmethod
    def _is_push_factor(factor: dict[str, Any]) -> bool:
        return str(factor.get("factorType", "")).upper() == TFA_PUSH_TYPE

    async def _auth_get_factors(self, headers: dict[str, Any] | None = None) -> list[dict[str, Any]] | None:
        """Return the 2fa factors Arlo has on file, or `None` if we can't read them.

        Needs a token in `headers`; either the partial one handed out in the
        middle of a login or a full one once we are in.
        """
        if headers is None:
            headers = self._auth.headers
        code, factors = await self._auth_get(
            f"{AUTH_GET_FACTORS}?data={int(time.time())}", {
            },
            headers
        )
        if not isinstance(factors, dict) or "items" not in factors:
            self._log.error(f"2fa: unable to read the factor list: {code} - {factors}")
            return None
        return list(factors["items"])

    def _auth_select_factor(self, factors: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Pick the 2fa factor to use.

        `tfa_factor_id` wins outright. It names one exact factor, which is the
        only reliable way to choose when an account has several of the same
        type; two phones, or a work and a home email. Without it we match on
        `tfa_type` and then `tfa_nickname`, falling back to the first factor
        of the right type.
        """
        known = ", ".join(self._describe_factor(f) for f in factors) or "nothing"

        wanted_id = self._cfg.tfa_factor_id
        if wanted_id is not None:
            for factor in factors:
                if factor.get("factorId") == wanted_id:
                    return factor
            self._log.error(f"login failed: 2fa: no factor with id {wanted_id}, this account has: {known}")
            return None

        wanted_type = self._cfg.tfa_type
        of_type = [f for f in factors if str(f.get("factorType", "")).lower() == wanted_type]
        if not of_type:
            self._log.error(f"login failed: 2fa: no {wanted_type} factor, this account has: {known}")
            return None

        nickname = self._cfg.tfa_nickname
        for factor in of_type:
            if factor.get("factorNickname") == nickname:
                return factor

        if len(of_type) > 1:
            self._log.warning(
                f"2fa: no {wanted_type} factor nicknamed '{nickname}', falling back to "
                f"{self._describe_factor(of_type[0])}; set tfa_factor_id to choose"
            )
        return of_type[0]

    async def _auth_trust_browser(self) -> _AuthState:
        """Trust the device.

        If this is a new authentication we tell Arlo to trust this browser. Arlo
        then sets a cookie we can provide with startAuth later to skip the 2fa
        stage.
        """
        self._debug("auth: trusting")

        # If we have already paired we don't do it again.
        if not self._auth.needs_pairing:
            self._debug("auth: no pairing required")
            return _AuthState.SUCCESS

        # If we have no browser code there is nothing to pair.
        if self._auth.browser_code is None:
            self._debug("auth: pairing postponed")
            return _AuthState.SUCCESS

        # Start the pairing.
        code, body = await self._auth_post(
            AUTH_START_PAIRING, {
                "factorAuthCode": self._auth.browser_code,
                "factorData": "",
                "factorType": "BROWSER"
            },
            self._auth.headers,
            cookies=self._req.details.cookies
        )
        if code != 200:
            self._log.error(f"login: auth pairing failed: {code} - {body}")
            return _AuthState.SUCCESS

        # We did it.
        self._debug("auth: pairing succeeded")
        self._auth_remember_user_agent()
        return _AuthState.SUCCESS

    async def _auth_validate(self) -> _AuthState:
        """Validate the token we have.

        Make sure the token we have is still good.
        """
        self._debug("auth: validating")

        # Update the token in the header to the new token.
        self._auth.headers["Authorization"] = str(self._req.details.token64 or "")

        code, validated = await self._auth_get(
            f"{AUTH_VALIDATE_PATH}?data={int(time.time())}", {
            },
            self._auth.headers
        )
        if validated is None:
            self._log.error("token validation failed")
            return _AuthState.FAILED

        return _AuthState.TRUST_BROWSER

    @staticmethod
    def _tfa_finish_is_final(body: Any) -> bool:
        """Is this finishAuth answer one that more polling cannot change?

        While a push approval is pending Arlo answers 'Authentication is not
        finished yet' (error 9233) and polling should continue. 'Too many
        requests' means Arlo is rate limiting the account: it keeps refusing
        every check, even after the user approves, and each further request
        extends the lock (about 24 hours). 'Maximum permitted time for
        authentication exceeded' (error 9238) means the request expired.
        """
        message = str(body or "").lower()
        return "too many requests" in message or "maximum permitted time" in message

    @staticmethod
    def _tfa_finish_error(code: int, body: Any) -> str:
        if "too many requests" in str(body or "").lower():
            return (
                f"login failed: finish failed: {code} - {body}: Arlo is rate limiting sign-ins for this account; "
                "stop retrying and wait (about 24 hours) before logging in again, every attempt extends the wait"
            )
        return f"login failed: finish failed: {code} - {body}"

    async def _auth_start_factor(self, factor: dict[str, Any]) -> str | None:
        """Ask Arlo to start authentication against one factor.

        For EMAIL and SMS factors this sends the code out. For a PUSH factor it
        sends the prompt to the phone; the Arlo apps send an empty
        `factorType` for those rather than `BROWSER`.

        Returns the `factorAuthCode` finishAuth needs, or `None` on failure.
        """
        factor_type = "" if self._is_push_factor(factor) else "BROWSER"
        await self._auth_options(AUTH_START_PATH, self._auth.headers)
        code, body = await self._auth_post(
            AUTH_START_PATH, {
                "factorId": factor["factorId"],
                "factorType": factor_type,
                "userId": self._req.details.user_id
            },
            self._auth.headers
        )
        if code != 200 or not isinstance(body, dict) or "factorAuthCode" not in body:
            self._log.error(f"login failed: start failed: {code} - {body}")
            return None
        return cast(str, body["factorAuthCode"])

    async def _auth_finish(self, factor_auth_code: str, otp: str | None = None) -> tuple[_FinishResult, int, Any]:
        """One finishAuth call.

        Asks for the raw answer so the error number under `meta` can tell a
        push that is still pending from one the user denied. On success the
        new token is saved and the browser code kept for pairing.
        """
        payload: dict[str, Any] = {
            "factorAuthCode": factor_auth_code,
            "isBrowserTrusted": True
        }
        if otp:
            payload["otp"] = otp

        code, body = await self._auth_post(AUTH_FINISH_PATH, payload, self._auth.headers, raw=True)
        meta = body.get("meta", {}) if isinstance(body, dict) else {}
        if code == 200 and meta.get("code") == 200 and isinstance(body.get("data"), dict):
            data = body["data"]
            self._auth.browser_code = data.get("browserAuthCode", None)
            self._req.update(data)
            return _FinishResult.SUCCESS, 200, data

        if meta:
            code = int(meta.get("code", code))
        message = meta.get("message", body) if meta else body
        if meta.get("error") == TFA_PUSH_DENIED_ERROR:
            return _FinishResult.DENIED, code, message
        if self._tfa_finish_is_final(message):
            return _FinishResult.FINAL, code, message
        return _FinishResult.PENDING, code, message

    async def _auth_wait_for_push(self, factor: dict[str, Any], factor_auth_code: str) -> _AuthState:
        """Poll finishAuth until the push is approved, denied or times out."""
        timeout = self._cfg.tfa_push_timeout
        poll = self._cfg.tfa_push_poll
        name = factor.get("displayName") or factor.get("factorNickname") or "your phone"
        self._log.info(f"2fa: approve the login on {name}, waiting up to {timeout:.0f}s")

        deadline = time.monotonic() + timeout
        tries = 1
        while True:
            self._debug(f"finishing push auth attempt #{tries}")
            result, code, body = await self._auth_finish(factor_auth_code)
            if result == _FinishResult.SUCCESS:
                return _AuthState.VALIDATE_TOKEN
            if result == _FinishResult.DENIED:
                self._log.error("login failed: 2fa: the push was denied")
                return _AuthState.FAILED
            if result == _FinishResult.FINAL:
                self._log.error(self._tfa_finish_error(code, body))
                return _AuthState.FAILED

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._log.error(f"login failed: 2fa: the push was not approved within {timeout:.0f}s")
                return _AuthState.FAILED
            await asyncio.sleep(min(poll, remaining))
            tries += 1

    async def _auth_new_auth(self) -> _AuthState:
        """We have to authenticate again.

        There are several steps to this:
         - get a suitable 2fa option
         - start the 2fa option we pick
         - start the authentication process with arlo
         - get the 2fa token, or wait for the push to be approved
         - finish authentication with arlo

         finishAuth will give us a new token.

        Which of the two flows runs is decided by the factor, not by
        `tfa_source`. A PUSH factor has no code to read so asking a code source
        for one would just hang until it gave up.
        """
        self._debug("auth: start new auth")

        # Find a factor to use.
        factors = await self._auth_get_factors()
        if not factors:
            self._log.error("login failed: 2fa: no secondary choices available")
            return _AuthState.FAILED
        factor = self._auth_select_factor(factors)
        if factor is None:
            return _AuthState.FAILED
        self._auth.factor_id = factor["factorId"]
        self._debug(f"using factor {self._describe_factor(factor)}")

        if self._is_push_factor(factor):
            factor_auth_code = await self._auth_start_factor(factor)
            if factor_auth_code is None:
                return _AuthState.FAILED
            return await self._auth_wait_for_push(factor, factor_auth_code)

        # Set up tfa. Call it now so it can capture state before we start
        # the authentication proper. For example, capture the current state
        # of an inbox before emails are sent.
        tfa_handler = ArloTFA(self._cfg, self._log)
        if tfa_handler.is_push:
            self._log.error(
                f"login failed: 2fa: tfa_source is push but {self._describe_factor(factor)} "
                "can't be approved from the phone app; pick a PUSH factor or another tfa_source"
            )
            await tfa_handler.stop()
            return _AuthState.FAILED
        self._auth.tfa_handler = tfa_handler
        if not await tfa_handler.start():
            await tfa_handler.stop()
            self._log.error("login failed: 2fa: startup failed")
            return _AuthState.FAILED

        # Start authentication to send out code. Stop if this fails.
        factor_auth_code = await self._auth_start_factor(factor)
        if factor_auth_code is None:
            await tfa_handler.stop()
            return _AuthState.FAILED

        # Get otp.
        otp = await tfa_handler.code()
        await tfa_handler.stop()
        if not otp:
            self._log.error("login failed: 2fa: code retrieval failed")
            return _AuthState.FAILED

        # Now finish the auth. We have one attempt with a code.
        self._debug("finishing auth")
        result, code, body = await self._auth_finish(factor_auth_code, otp)
        if result == _FinishResult.SUCCESS:
            return _AuthState.VALIDATE_TOKEN
        self._log.error(self._tfa_finish_error(code, body))
        return _AuthState.FAILED

    async def _auth_trusted_auth(self) -> _AuthState:
        """Arlo still trusts us.

        Send back the factor id that was passed. We have a cookie - browser_trust_* -
        that binds us to the id. If this works we move on to token validation.
        """
        self._debug("auth: start trusted auth")

        await self._auth_options(AUTH_START_PATH, self._auth.headers)
        code, body = await self._auth_post(
            AUTH_START_PATH, {
                "factorId": self._auth.factor_id,
                "factorType": "BROWSER",
                "userId": self._req.details.user_id
            },
            self._auth.headers
        )

        # We failed at this stage. Stop trying for now.
        if code != 200:
            self._log.error(f"login failed: trusted start failed1: {code} - {body}")
            return _AuthState.FAILED

        # Save auth info.
        self._req.update(body)

        # Check if we are done.
        if not body["authCompleted"]:
            self._log.error(f"login failed: trusted start failed2: {code} - {body}")
            return _AuthState.FAILED
        else:
            # Arlo accepted this identity as trusted, so keep using it.
            self._auth_remember_user_agent()
            return _AuthState.VALIDATE_TOKEN

    async def _auth_current_factor_id(self) -> _AuthState:
        """Get the current factor id

        If we have paired this "device" with Arlo before it will return an ID
        indicating we can skip the 2fa to get our session token. Otherwise
        it returns untrusted and we have to perform some 2fa operations.

        If we are already trusted we can skip pairing.
        """
        self._debug("auth: current factor id")

        # Retrieve current factor ID. If we have previously trusted this
        # "browser" we will be able to skip the 2fa section.
        await self._auth_options(AUTH_GET_FACTORID, self._auth.headers)
        code, body = await self._auth_post(
            AUTH_GET_FACTORID, {
                "factorType": "BROWSER",
                "factorData": "",
                "userId": self._req.details.user_id
            },
            self._auth.headers,
            cookies=self._req.details.cookies
        )

        # This means we are trusted. Save factor ID and move on to validation.
        if code == 200:
            self._auth.needs_pairing = False
            self._auth.factor_id = body["factorId"]
            return _AuthState.TRUSTED_AUTH

        # Check if MFA is disabled by service
        if (isinstance(body, str) and "disabled" in body.lower()) or (
            isinstance(body, dict) and (body.get("error") == 9306 or "disabled" in str(body.get("message", "")).lower())
        ):
            self._debug("auth: MFA disabled by service, skipping 2FA")
            return _AuthState.VALIDATE_TOKEN

        # Look for a way to authenticate.
        return _AuthState.NEW_AUTH

    def _auth_get_connection(self) -> bool:
        """Keep track of connection attempts and curve tries.

        We make 3 attempts to log in.
        - For curl_cffi: 3 attempts with modern browser TLS fingerprint.
        - For requests: 3 attempts with plain requests.Session (for testing).
        - For cloudscraper: cycles through CloudFlare ECDH curves per attempt.
        """
        # 1. curl_cffi backend (default)
        if self._cfg.http_backend == "curl_cffi":
            if self._auth.attempt <= 3:
                self._debug(f"auth: login attempt #{self._auth.attempt} (curl_cffi)")
                self._auth.attempt += 1
                try:
                    from curl_cffi.requests import Session as cffi_Session
                    from curl_cffi.requests import AsyncSession as cffi_AsyncSession
                    self._req.details.connection = cffi_Session(impersonate=cast(Any, self._cfg.curl_cffi_impersonate))
                    self._req.details.async_connection = cffi_AsyncSession(impersonate=cast(Any, self._cfg.curl_cffi_impersonate))
                    if self._req.details.cookies is not None:
                        self._req.details.connection.cookies.jar = self._req.details.cookies
                        self._req.details.async_connection.cookies.jar = self._req.details.cookies
                    return True
                except Exception as e:
                    self._log.warning(f"auth: failed to use curl_cffi: {e}")
            self._req.details.connection = None
            self._req.details.async_connection = None
            return False

        # 2. requests backend (for mocks/testing)
        if self._cfg.http_backend == "requests":
            if self._auth.attempt <= 3:
                self._debug(f"auth: login attempt #{self._auth.attempt} (requests)")
                self._auth.attempt += 1
                import requests
                self._req.details.connection = requests.Session()
                self._req.details.async_connection = None
                if self._req.details.cookies is not None:
                    self._req.details.connection.cookies = self._req.details.cookies
                return True
            self._req.details.connection = None
            self._req.details.async_connection = None
            return False

        # 3. cloudscraper backend (cycles curves across attempts)
        while True:
            if self._auth.curves:
                curve = self._auth.curves.pop(0)
                self._debug(f"auth: attempt #{self._auth.attempt}, CloudFlare curve set to: {curve}")
                import cloudscraper
                self._req.details.connection = cloudscraper.create_scraper(
                    disableCloudflareV1=True,
                    ecdhCurve=curve,
                    debug=False,
                )
                self._req.details.async_connection = None
                if self._req.details.cookies is not None:
                    self._req.details.connection.cookies = self._req.details.cookies
                return True

            # If all curves in this attempt failed, advance attempt and reload curves
            if self._auth.attempt < 3:
                self._auth.attempt += 1
                self._auth.curves = self._cfg.ecdh_curves.copy()
                self._debug(f"auth: starting attempt #{self._auth.attempt} with curves={self._auth.curves}")
                continue

            # All attempts and curves exhausted
            self._debug("auth: all connection attempts failed")
            self._req.details.connection = None
            self._req.details.async_connection = None
            return False

    async def _auth_revalidate_token(self) -> _AuthState:
        """See if we can skip auth by re-using the old token.
        """
        self._debug("auth: checking saved token")

        # If a re-login was explicitly triggered or renewal is due, the old token should not be reused.
        if self._auth.force_reauth:
            self._debug("auth: force_reauth is set, requesting fresh token")
            return _AuthState.LOGIN

        # We haven't logged in at all yet.
        if self._req.details.token64 is None:
            self._debug("auth: nothing to test")
            return _AuthState.LOGIN

        # The current token has expired.
        if self._req.details.token_expires_in is None:
            self._debug("auth: no expiry time")
            return _AuthState.LOGIN

        self._debug(f"now={int(time.time())}, expires={int(self._req.details.token_expires_in - 300)}")
        if self._req.details.token_expires_in - 300 < time.time():
            self._debug("auth: login expired")
            return _AuthState.LOGIN

        # Token is unexpired. Optimistically reuse without validateAccessToken network round-trip.
        self._debug("auth: token is unexpired, reusing without pre-validation")
        self._auth.was_reused_from_disk = True
        self._auth.attempt = 1
        self._auth.curves = self._cfg.ecdh_curves.copy()
        if self._auth_get_connection():
            self._auth.headers = self._req.auth_headers()
            self._auth.headers["Authorization"] = str(self._req.details.token64 or "")
            return _AuthState.SUCCESS

        return _AuthState.LOGIN

    async def _auth_login(self) -> _AuthState:
        """Perform the actual login.

        This is when username and password get used. In an attempt to bypass
        cloudlfare issues it will try several different curve options.
        """
        self._debug("auth: logging in")

        # Reset attempts and curves for login
        self._auth.attempt = 1
        self._auth.curves = self._cfg.ecdh_curves.copy()

        while self._auth_get_connection():
            self._auth.headers = self._req.auth_headers()

            # Attempt the auth.
            await self._auth_options(AUTH_PATH, self._auth.headers)
            code, body = await self._auth_post(
                AUTH_PATH, {
                    "email": self._cfg.username,
                    "password": to_b64(self._cfg.password),
                    "language": "en",
                    "EnvSource": "prod",
                },
                self._auth.headers,
            )

            # Username/password mismatch.
            if code == 401:
                self._log.error(f"login failed: {code} - {body}")
                return _AuthState.FAILED

            # We've succeeded.
            if code == 200:
                # Update our user info and add the Authorization field to the
                # auth headers.
                self._req.update(body)
                self._auth.headers["Authorization"] = str(self._req.details.token64 or "")

                # See what state to move to next.
                if not body["authCompleted"]:
                    return _AuthState.CURRENT_FACTOR_ID
                else:
                    return _AuthState.VALIDATE_TOKEN

            # Flag the failure.
            self._log.error(f"login failed: {code} - possible cloudflare issue")

            # Don't try too hard.
            await asyncio.sleep(3)

        # Here means we're out of retries so stop now.
        self._log.error(f"login failed: all connection attempts failed - possible cloudflare issue")
        return _AuthState.FAILED

    async def _auth_starting(self) -> _AuthState:
        """Clear auth state to a known starting point.
        """
        self._debug("auth: starting")

        await self._req.load_cookies()
        self._req.details.user_agent = self._auth_user_agent()
        self._req.details.connection = None
        self._auth.factor_id = None
        self._auth.needs_pairing = True
        self._auth.was_reused_from_disk = False

        return _AuthState.REVALIDATE_TOKEN

    def _auth_user_agent(self) -> str:
        """The user agent to log in with.

        Arlo ties a trusted browser to the identity it was paired with. If we
        paired under the current `user_agent` setting reuse exactly that
        string, so `random`, or an updated table of user agents, doesn't throw
        away the trust and force a full 2fa on the next login.
        """
        details = self._req.details
        if details.paired_user_agent and details.paired_user_agent_cfg == self._cfg.user_agent:
            self._debug("auth: reusing the paired user agent")
            return details.paired_user_agent
        return self._cfg.user_agent_string()

    def _auth_remember_user_agent(self) -> None:
        self._req.details.paired_user_agent = self._req.details.user_agent
        self._req.details.paired_user_agent_cfg = self._cfg.user_agent

    async def _auth_run(self, stop_at: tuple[_AuthState, ...] = ()) -> _AuthState:
        """Step the auth state machine until it succeeds, fails or reaches
        one of `stop_at`.
        """
        steps = {
            _AuthState.STARTING: self._auth_starting,
            _AuthState.REVALIDATE_TOKEN: self._auth_revalidate_token,
            _AuthState.LOGIN: self._auth_login,
            _AuthState.CURRENT_FACTOR_ID: self._auth_current_factor_id,
            _AuthState.TRUSTED_AUTH: self._auth_trusted_auth,
            _AuthState.NEW_AUTH: self._auth_new_auth,
            _AuthState.VALIDATE_TOKEN: self._auth_validate,
            _AuthState.TRUST_BROWSER: self._auth_trust_browser,
        }
        while self._auth.state not in (_AuthState.SUCCESS, _AuthState.FAILED) + stop_at:
            step = steps.get(self._auth.state)
            if step is None:
                self._log.error(f"login failed: unexpected auth state {self._auth.state}")
                self._auth.state = _AuthState.FAILED
                break
            self._auth.state = await step()
        return self._auth.state

    async def _auth_succeeded(self) -> None:
        if not self._auth.was_reused_from_disk:
            self._last_login_time = time.monotonic()
            # We are in a successful state so:
            #  - save the session for reloading
            #  - save the cookies for reloading
            await self._req.save()
            await self._req.save_cookies()
        self._auth.force_reauth = False

    async def _login_locked(self) -> bool:
        """Perform all the steps to authenticate against the Arlo servers.
        Assumes self._login_lock is held.
        """

        # Restart. We might be able to miss out the login stage and just try
        # for a factor-id.
        if self._auth.state != _AuthState.STARTING:
            self._auth.state = _AuthState.STARTING
            self._debug("auth: restarting")

        await self._auth_run()

        self._debug(f"auth: login exit state: {self._auth.state}")
        if self._auth.state != _AuthState.SUCCESS:
            return False

        await self._auth_succeeded()
        return True

    # Interactive login. These let a caller - typically a setup UI - show the
    # user the account's real 2fa factors and let them pick one, instead of
    # committing to a `tfa_source`/`tfa_type` up front.

    @property
    def login_factors(self) -> list[dict[str, Any]]:
        """The factors offered after `login_start()` returns `NEEDS_FACTOR`."""
        return self._interactive.factors

    async def _login_finish(self) -> LoginStep:
        """Validate the new token, pair the browser and save everything."""
        self._auth.state = _AuthState.VALIDATE_TOKEN
        if await self._auth_run() != _AuthState.SUCCESS:
            return LoginStep.FAILED
        await self._auth_succeeded()
        self._logged_in = True
        return LoginStep.SUCCESS

    async def login_start(self) -> LoginStep:
        """Sign in with the password and see whether 2fa is needed.

        Always checks the password, even if a saved token is still good, so a
        setup flow finds out about a typo now. A browser Arlo already trusts
        still skips 2fa.
        """
        async with self._login_lock:
            await self._req.load()
            if self._req.details.device_id is None:
                self._req.details.device_id = str(uuid.uuid4())
            self._interactive = _InteractiveDetails()
            self._auth.force_reauth = True
            self._auth.state = _AuthState.STARTING

            state = await self._auth_run(stop_at=(_AuthState.NEW_AUTH,))
            if state == _AuthState.SUCCESS:
                await self._auth_succeeded()
                self._logged_in = True
                return LoginStep.SUCCESS
            if state != _AuthState.NEW_AUTH:
                return LoginStep.FAILED

            factors = await self._auth_get_factors()
            if not factors:
                self._log.error("login failed: 2fa: no secondary choices available")
                return LoginStep.FAILED
            self._interactive.factors = factors
            return LoginStep.NEEDS_FACTOR

    async def login_choose_factor(self, factor_id: str) -> LoginStep:
        """Start 2fa with one of the factors from `login_factors`."""
        async with self._login_lock:
            factor = next((f for f in self._interactive.factors if f.get("factorId") == factor_id), None)
            if factor is None:
                self._log.error(f"login failed: 2fa: unknown factor id {factor_id}")
                return LoginStep.FAILED

            self._debug(f"auth: interactive login with {self._describe_factor(factor)}")
            factor_auth_code = await self._auth_start_factor(factor)
            if factor_auth_code is None:
                return LoginStep.FAILED

            self._auth.factor_id = factor_id
            self._interactive.factor = factor
            self._interactive.factor_auth_code = factor_auth_code
            if self._is_push_factor(factor):
                self._interactive.push_deadline = time.monotonic() + self._cfg.tfa_push_timeout
                return LoginStep.AWAITING_PUSH
            return LoginStep.AWAITING_CODE

    async def login_poll_push(self) -> LoginStep:
        """One check of a push login started by `login_choose_factor()`."""
        async with self._login_lock:
            if self._interactive.factor_auth_code is None:
                self._log.error("login failed: 2fa: no push login in progress")
                return LoginStep.FAILED

            result, code, body = await self._auth_finish(self._interactive.factor_auth_code)
            if result == _FinishResult.SUCCESS:
                return await self._login_finish()
            if result == _FinishResult.DENIED:
                self._log.error("login failed: 2fa: the push was denied")
                return LoginStep.FAILED
            if result == _FinishResult.FINAL:
                self._log.error(self._tfa_finish_error(code, body))
                return LoginStep.FAILED
            if time.monotonic() >= self._interactive.push_deadline:
                self._log.error("login failed: 2fa: the push was not approved in time")
                return LoginStep.FAILED
            return LoginStep.AWAITING_PUSH

    async def login_submit_code(self, otp: str) -> LoginStep:
        """Finish an EMAIL or SMS login with the code the user typed in.

        A rejected code leaves the login where it was, so the caller can let
        the user try again.
        """
        async with self._login_lock:
            if self._interactive.factor_auth_code is None:
                self._log.error("login failed: 2fa: no code login in progress")
                return LoginStep.FAILED

            result, code, body = await self._auth_finish(self._interactive.factor_auth_code, otp.strip())
            if result == _FinishResult.SUCCESS:
                return await self._login_finish()
            self._log.error(self._tfa_finish_error(code, body))
            if result == _FinishResult.FINAL:
                return LoginStep.FAILED
            return LoginStep.AWAITING_CODE

    async def login_close(self) -> None:
        """Drop the HTTP connections an interactive login opened."""
        details = self._req.details
        for conn in (details.connection, details.async_connection):
            close = getattr(conn, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                self._debug(f"login: close failed: {e}")
        details.connection = None
        details.async_connection = None

    async def tfa_factors(self) -> list[dict[str, Any]] | None:
        """Return the 2fa factors configured on the account, once logged in."""
        headers = self._req.auth_headers()
        headers["Authorization"] = str(self._req.details.token64 or "")
        return await self._auth_get_factors(headers)


    async def _login(self) -> bool:
        """Serialized wrapper around _login_locked to prevent concurrent auth attempts."""
        async with self._login_lock:
            if not self._auth.force_reauth and (time.monotonic() - self._last_login_time < 10):
                self._debug("login skipped: already logged in within last 10s")
                return True
            self._req._is_logging_in = True
            await self._req.drain_in_flight(timeout=2.0)
            try:
                return await self._login_locked()
            finally:
                self._req._is_logging_in = False

    async def _relogin(self) -> bool:
        async with self._login_lock:
            if not self._auth.force_reauth and (time.monotonic() - self._last_login_time < 10):
                self._debug("relogin skipped: already logged in within last 10s")
                return True
            self._debug("re-logging in after 401 or token expiration")
            self._req._is_logging_in = True
            self._auth.force_reauth = True
            await self._req.drain(in_flight_timeout=2.0, transactions_timeout=5.0)
            try:
                if await self._login_locked():
                    await self._event_reconnect()
                    return True
                return False
            finally:
                self._req._is_logging_in = False

    def _session_connection(self) -> bool:
        """Make sure the headers are set up for the non-auth phase.
        """
        self._debug("session: fixing connection")

        headers = self._req.headers()
        self._req.details.connection.headers.update(headers)
        if self._req.details.async_connection:
            self._req.details.async_connection.headers.update(headers)
        return True

    async def _session_v3_details(self) -> bool:
        """Read in the v3 session details.

        This provides us with the following information:
         - is multilocation on
         - the backend we are using
        """
        self._debug("session: getting v3 details")

        v3_session = await self.get(SESSION_PATH)
        if v3_session is None:
            self._log.error("v3 session failed")
            return False

        # Multi-location is on?
        self._multi_location = v3_session.get('supportsMultiLocation', False)
        self._debug(f"multilocation is {self._multi_location}")

        # If Arlo provides an MQTT URL key use it to set the backend.
        if MQTT_URL_KEY in v3_session:
            self._cfg.update_mqtt_from_url(v3_session[MQTT_URL_KEY])
            self._debug(f"back={self._cfg.event_backend};url={self._cfg.mqtt_host}:{self._cfg.mqtt_port}")

        # Always good if the v3 read works.
        return True

    async def _session_finalize(self) -> bool:
        """Set up for the post authentication phase.

        Update the connection headers to include the latest auth token and
        work out some important pieces of the user setup.
        """
        return self._session_connection() and await self._session_v3_details()

    async def _notify(self, device_id, xcloud_id, body, trans_id=None):
        if trans_id is None:
            trans_id = self.gen_trans_id()

        body["to"] = device_id
        if "from" not in body:
            body["from"] = self._req.details.web_id
        body["transId"] = trans_id

        response = await self.post(
            NOTIFY_PATH + device_id,
            body,
            headers={
                "xcloudId": xcloud_id
            }
        )

        if response is None:
            return None
        else:
            return trans_id

    def gen_trans_id(self, trans_type=TRANSID_PREFIX):
        return trans_type + "!" + str(uuid.uuid4())

    async def connect(self):
        # Restore the persistent session information.
        await self._req.load()
        await self._req.load_cookies()
        if self._req.details.device_id is None:
            self._debug("created new user ID")
            self._req.details.device_id = str(uuid.uuid4())

        # Start the login
        self._logged_in = await self._login() and await self._session_finalize()
        if not self._logged_in:
            self._debug("failed to log in")
        return

    async def start(self):
        # Build event details...
        self._event.stream = ArloEvent(self._cfg, self._log, self._req.details,
                                       self._event_response_handler,
                                       self._event_connected_handler,
                                       self._event_reconnected_handler)
        self._event.stream.setup()
        self._event.stream_connected = False
        self._event.loop_task = asyncio.create_task(self._event_loop())

        count = 0
        while not self._event.stream_connected and count < 30:
            self._debug("waiting for stream up")
            await asyncio.sleep(1)
            count += 1
        # XXX: check count and fail?

        self._debug("stream up")
        return True

    def _schedule_token_renewal(self):
        if self._reconnect_job is not None:
            self._tasks.cancel(self._reconnect_job)
            self._reconnect_job = None

        token_expires_in = getattr(self._req.details, "token_expires_in", None)
        if token_expires_in:
            try:
                delta = int(float(token_expires_in) - time.time())
            except (ValueError, TypeError):
                delta = 0
            if delta > 360:
                reconnect_interval = delta - 300
            elif delta > 60:
                reconnect_interval = delta - 60
            else:
                reconnect_interval = 60
        else:
            reconnect_interval = 90 * 60

        if reconnect_interval > 0:
            self._debug(f"automatically scheduling token renewal in {reconnect_interval}s")
            self._reconnect_job = self._tasks.run_in(self._scheduled_token_renewal, reconnect_interval)

    @property
    def is_connected(self):
        return self._logged_in

    async def stop(self, logout: bool=True):
        self._debug("trying to stop")

        if self._reconnect_job is not None:
            self._tasks.cancel(self._reconnect_job)
            self._reconnect_job = None

        await self._event_loop_stop()
        if self._event.stream is not None:
            await self._event.stream.stop()
        if self._event.loop_task:
            try:
                await asyncio.wait_for(self._event.loop_task, timeout=2.0)
            except (asyncio.TimeoutError, TimeoutError, asyncio.CancelledError):
                self._debug("event loop did not stop in time, cancelling")
                self._event.loop_task.cancel()
                try:
                    await self._event.loop_task
                except asyncio.CancelledError:
                    pass

        self._req.cancel_transactions()

        if logout:
            await self.put(LOGOUT_PATH)

    async def notify(self, device_id, xcloud_id, body, timeout=None, wait_for=None):
        """Send in a notification.

        Notifications are Arlo's way of getting stuff done - turn on a light, change base station mode,
        start recording. Pyaarlo will post a notification and Arlo will post a reply on the event
        stream indicating if it worked or not or of a state change.

        How Pyaarlo treats notifications depends on the mode it's being run in. For asynchronous mode - the
        default - it sends the notification and returns immediately. For synchronous mode it sends the
        notification and waits for the event related to the notification to come back. To use the default
        settings leave `wait_for` as `None`, to force asynchronous set `wait_for` to `nothing` and to force
        synchronous set `wait_for` to `event`.

        There is a third way to send a notification where the code waits for the initial response to come back
        but that must be specified by setting `wait_for` to `response`.

        :param device_id: device_id to use
        :param xcloud_id: xcloud_id to use
        :param body: notification message
        :param timeout: how long to wait for response before failing, only applied if `wait_for` is `event`.
        :param wait_for: what to wait for, either `None`, `event`, `response` or `nothing`.
        :return: either a response packet or an event packet
        """
        if wait_for is None:
            if self._cfg.inline_mode:
                wait_for = "event" if self._cfg.start_background else "response"
            else:
                wait_for = "response" if not self._cfg.start_background else "nothing"

        if wait_for == "event":
            self._vdebug("notify+event running")
            tid = self._req.start_transaction()
            await self._notify(device_id, xcloud_id, body=body, trans_id=tid)
            return await self._req.wait_for_transaction(tid, timeout)
        elif wait_for == "response":
            self._vdebug("notify+response running")
            return await self._notify(device_id, xcloud_id, body=body)
        else:
            self._vdebug("notify+sent")
            self._tasks.run_now(self._notify, device_id=device_id, xcloud_id=xcloud_id, body=body)

    async def get(
            self,
            path,
            params=None,
            headers=None,
            stream=False,
            raw=False,
            timeout=None,
            host=None,
            wait_for="response",
            cookies=None,
    ):
        if wait_for == "response":
            self._vdebug("get+response running")
            return await self._req.request(
                path, "GET", params, headers, stream, raw, timeout, host, cookies
            )
        else:
            self._vdebug("get sent")
            self._tasks.run_now(
                self._req.request, path=path, method="GET", params=params, headers=headers, stream=stream, raw=raw, timeout=timeout, host=host
            )

    async def put(
            self,
            path,
            params=None,
            headers=None,
            raw=False,
            timeout=None,
            wait_for="response",
            cookies=None,
    ):
        if wait_for == "response":
            self._vdebug("put+response running")
            return await self._req.request(path, "PUT", params, headers, False, raw, timeout, cookies)
        else:
            self._vdebug("put sent")
            self._tasks.run_now(
                self._req.request, path=path, method="PUT", params=params, headers=headers, stream=False, raw=raw, timeout=timeout
            )

    async def post(
            self,
            path,
            params=None,
            headers=None,
            raw=False,
            timeout=None,
            tid=None,
            wait_for="response"
    ):
        if wait_for is None:
            if self._cfg.inline_mode and self._cfg.start_background:
                wait_for = "resource"
            else:
                wait_for = "response"

        if wait_for == "resource":
            self._vdebug("post+resource running")
            if tid is None:
                tid = list(params.keys())[0]
            tid = self._req.start_transaction(tid)
            await self._req.request(path, "POST", params, headers, False, raw, timeout)
            return await self._req.wait_for_transaction(tid, timeout)
        if wait_for == "response":
            self._vdebug("post+response running")
            return await self._req.request(path, "POST", params, headers, False, raw, timeout)
        else:
            self._vdebug("post sent")
            self._tasks.run_now(
                self._req.request, path=path, method="POST", params=params, headers=headers, stream=False, raw=raw, timeout=timeout
            )

    @property
    def session(self):
        return self._req.details.connection

    @property
    def sub_id(self):
        return self._req.details.sub_id

    @property
    def user_id(self):
        return self._req.details.user_id

    @property
    def multi_location(self):
        return self._multi_location

    def add_listener(self, device_id, unique_id, callback):
        if device_id not in self._callbacks:
            self._callbacks[device_id] = []
        self._callbacks[device_id].append(callback)
        if unique_id not in self._callbacks:
            self._callbacks[unique_id] = []
        self._callbacks[unique_id].append(callback)

    def add_any_listener(self, callback):
        if "all" not in self._callbacks:
            self._callbacks["all"] = []
        self._callbacks["all"].append(callback)

    def del_listener(self, device, callback):
        pass

    async def post_with_status(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        raw: bool = False,
        timeout: int | float | None = None,
        host: str | None = None,
    ) -> tuple[int, Any]:
        """Post and return (http_status, body) without event wait handling."""
        return await self._req.request_tuple(
            path=path,
            method="POST",
            params=params,
            headers=headers,
            stream=False,
            raw=raw,
            timeout=timeout,
            host=host,
        )

    async def get_intelligence_events(
        self,
        from_date: Any,
        limit: int = 100,
        location_id: str | None = None,
        max_pages: int = 50,
    ) -> list[dict[str, Any]]:
        """Return flattened Arlo Intelligence events from the feed metadata API.

        ``from_date`` must be a ``YYYYMMDD`` string or a ``datetime.date``. The
        feed is location-scoped, so all locations are queried by default. Event
        dictionaries retain the original payload and receive ``eventId``,
        ``locationId``, and ``deviceId`` fields when those values are available.
        """
        if hasattr(from_date, "strftime"):
            from_date = from_date.strftime("%Y%m%d")
        from_date = str(from_date)
        if len(from_date) != 8 or not from_date.isdigit():
            raise ValueError("from_date must be a YYYYMMDD string or date")
        try:
            limit = max(1, min(int(limit), 100))
            max_pages = max(1, int(max_pages))
        except (TypeError, ValueError) as exc:
            raise ValueError("limit and max_pages must be positive integers") from exc

        web_id = getattr(self, "_web_id", None) or (
            self._req.details.web_id if hasattr(self, "_req") and hasattr(self._req, "details") else None
        )
        user_id = getattr(self, "_user_id", None) or (
            self._req.details.user_id if hasattr(self, "_req") and hasattr(self._req, "details") else None
        )
        owner_id = web_id or user_id
        if location_id is not None:
            location_ids = [str(location_id)]
        else:
            arlo_obj = getattr(self, "_arlo", None)
            locations = getattr(arlo_obj, "locations", []) if arlo_obj else []
            location_ids = [
                str(getattr(location, "id", None) or getattr(location, "_id", ""))
                for location in locations
            ]
            location_ids = [value for value in location_ids if value]
        if not owner_id or not location_ids:
            raise RuntimeError("authenticated owner and location metadata are required")

        cfg = getattr(self, "_cfg", None) or getattr(getattr(self, "_arlo", None), "cfg", None)
        base_host = str(getattr(cfg, "host", "")).rstrip("/")
        if base_host.endswith("/hmsweb"):
            host = base_host[:-len("/hmsweb")] + "/hmsfeeds"
        elif base_host.endswith("/hmsfeeds"):
            host = base_host
        else:
            host = base_host + "/hmsfeeds"

        events: list[dict[str, Any]] = []
        for current_location_id in location_ids:
            path = f"/users/{owner_id}/{current_location_id}/metadata"
            next_page = None
            for _ in range(max_pages):
                req_fn = getattr(self, "_request", None)
                if req_fn is not None:
                    res = req_fn(
                        path,
                        method="POST",
                        params={
                            "asc": False,
                            "fromDate": from_date,
                            "limit": limit,
                            "groupBy": "events",
                            "nextPage": next_page,
                        },
                        host=host,
                        raw=True,
                    )
                    response = await res if inspect.isawaitable(res) else res
                else:
                    response = await self._req.request(
                        path,
                        method="POST",
                        params={
                            "asc": False,
                            "fromDate": from_date,
                            "limit": limit,
                            "groupBy": "events",
                            "nextPage": next_page,
                        },
                        host=host,
                        raw=True,
                    )

                data = response.get("data", response) if isinstance(response, dict) else {}
                grouped = data.get("groupByEvents", {}) if isinstance(data, dict) else {}
                events.extend(_flatten_intelligence_events(grouped, current_location_id))
                candidate = data.get("nextPage") if isinstance(data, dict) else None
                if not candidate or candidate == next_page:
                    break
                next_page = candidate
        return events

    async def devices(self):
        return await self.get(f"{DEVICES_PATH}?t={time_to_arlotime()}")

    def ev_inject(self, response):
        self._event_run_callbacks(response)





