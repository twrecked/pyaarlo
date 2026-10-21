import asyncio
import inspect
import pprint
import re
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

        # The event stream.
        self._event: _EventDetails = _EventDetails()

        # Remaining state variables.
        self._dump_file = self._cfg.dump_file
        self._requests: dict[str, Any] = {}
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

    def _event_notify_waiting(self, response):
        """Check if this event satifies a waiting post() call.

        We match a respone to a request and copy the response to it. When done
        signal the post to continue.
        """

        tid = response.get("transId", None)
        resource = response.get("resource", None)
        device_id = response.get("from", None)

        # Transaction ID
        # Simple. We have a transaction ID, look for that. These are
        # usually returned by notify requests.
        if tid and tid in self._requests:
            req = self._requests[tid]
            req["response"] = response
            req["event"].set()

        # Resource
        # These are usually returned after POST requests. We trap these
        # to make async calls sync.
        if resource:
            # Historical. We are looking for a straight matching resource.
            if resource in self._requests:
                self._vdebug("{} found by text!".format(resource))
                req = self._requests[resource]
                req["response"] = response
                req["event"].set()

            else:
                # Complex. We are looking for a resource and-or
                # deviceid matching a regex.
                if device_id:
                    bounded_resource = "{}:{}".format(resource, device_id)
                    self._vdebug("{} bounded device!".format(bounded_resource))
                else:
                    bounded_resource = resource

                for request_pattern, req in self._requests.items():
                    if re.match(request_pattern, bounded_resource):
                        self._vdebug(
                            "{} found by regex {}!".format(bounded_resource, request_pattern)
                        )
                        req["response"] = response
                        req["event"].set()

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
        
        # Notify any waiting post() calls.
        self._event_notify_waiting(response)

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
        self._debug("scheduled token renewal: forcing fresh login before expiry")
        self._auth.force_reauth = True
        await self._event_reconnect()

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
            self._requests = {}

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

    async def _auth_find_factor_id(self) -> str | None:
        """Get list of suitable 2fa options.

        Then look at the user config and figure out which one is best
        suited for the operation.
        """
        self._debug("auth: finding factor id")

        # Get a list of factors to use.
        code, factors = await self._auth_get(
            f"{AUTH_GET_FACTORS}?data={int(time.time())}", {
            },
            self._auth.headers
        )
        if not isinstance(factors, dict) or "items" not in factors:
            self._log.error("login failed: 2fa: no secondary choices available")
            return None

        # Get the right types.
        factors_of_type = []
        for factor in factors["items"]:
            if factor["factorType"].lower() == self._cfg.tfa_type:
                factors_of_type.append(factor)

        # Match up the nickname.
        if len(factors_of_type) > 0:
            # Try to match the factorNickname with the tfa_nickname
            for factor in factors_of_type:
                if self._cfg.tfa_nickname == factor["factorNickname"]:
                    return factor["factorId"]
            # Otherwise fallback to using the first option
            else:
                return factors_of_type[0]["factorId"]

        self._log.error("login failed: 2fa: no secondary choices available")
        return None

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

    async def _auth_new_auth(self) -> _AuthState:
        """We have to authenticate again.

        There are several steps to this:
         - get a suitable 2fa option
         - start the 2fa option we pick
         - start the authentication process with arlo
         - get the 2fa token
         - finish authentication with arlo

         finishAuth will give us a new token.
        """
        self._debug("auth: start new auth")

        # Find a factor ID to use
        self._auth.factor_id = await self._auth_find_factor_id()
        if self._auth.factor_id is None:
            return _AuthState.FAILED
        self._debug(f"using factor id {self._auth.factor_id}")

        # Set up tfa. Call it now so it can capture state before we start
        # the authentication proper. For example, capture the current state
        # of an inbox before emails are sent.
        self._auth.tfa_handler = ArloTFA(self._cfg, self._log)
        await self._auth.tfa_handler.start()

        # Start authentication to send out code. Stop if this fails.
        await self._auth_options(AUTH_START_PATH, self._auth.headers)
        code, body = await self._auth_post(
            AUTH_START_PATH, {
                "factorId": self._auth.factor_id,
                "factorType": self._auth.tfa_handler.factor_type,
                "userId": self._req.details.user_id
            },
            self._auth.headers
        )
        if code != 200:
            await self._auth.tfa_handler.stop()
            self._log.error(f"login failed: new start failed1: {code} - {body}")
            return _AuthState.FAILED

        # We need this for the next step.
        factor_auth_code = body["factorAuthCode"]

        # Get otp.
        otp = await self._auth.tfa_handler.code()
        await self._auth.tfa_handler.stop()

        if otp is None:
            self._log.error(f"login failed: 2fa: code retrieval failed")
            return _AuthState.FAILED

        # Build the payload. If we returned a one-time-passcode then enter it.
        payload = {
            "factorAuthCode": factor_auth_code,
            "isBrowserTrusted": True
        }
        if otp:
            payload["otp"] = otp

        # Now finish the auth
        tries = 1
        while True:
            # finish authentication
            self._debug(f"finishing auth attempt #{tries}")
            code, body = await self._auth_post(
                AUTH_FINISH_PATH,
                payload,
                self._auth.headers
            )

            # We're authenticated. Do two things then validate:
            #  - save the browser auth code
            #  - update the user info
            if code == 200:
                self._auth.browser_code = body.get("browserAuthCode", None)
                self._req.update(body)
                return _AuthState.VALIDATE_TOKEN

            # We have a code and we only have one attempt, so fail.
            if otp:
                break

            # If we've tried too many time, fail.
            if tries >= self._cfg.tfa_retries:
                break

            # Loop again.
            self._log.warning(f"2fa finishAuth - tries {tries}")
            await asyncio.sleep(self._cfg.tfa_delay)
            tries += 1

        self._log.error(f"login failed: finish failed: {code} - {body}")
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
        self._req.details.user_agent = self._cfg.user_agent_string()
        self._req.details.connection = None
        self._auth.factor_id = None
        self._auth.needs_pairing = True

        return _AuthState.REVALIDATE_TOKEN

    async def _login_locked(self) -> bool:
        """Perform all the steps to authenticate against the Arlo servers.
        Assumes self._login_lock is held.
        """

        # Restart. We might be able to miss out the login stage and just try
        # for a factor-id.
        if self._auth.state != _AuthState.STARTING:
            self._auth.state = _AuthState.STARTING
            self._debug("auth: restarting")

        while self._auth.state != _AuthState.SUCCESS and self._auth.state != _AuthState.FAILED:
            if self._auth.state == _AuthState.STARTING:
                self._auth.state = await self._auth_starting()
            if self._auth.state == _AuthState.REVALIDATE_TOKEN:
                self._auth.state = await self._auth_revalidate_token()
            if self._auth.state == _AuthState.LOGIN:
                self._auth.state = await self._auth_login()
            if self._auth.state == _AuthState.CURRENT_FACTOR_ID:
                self._auth.state = await self._auth_current_factor_id()
            if self._auth.state == _AuthState.TRUSTED_AUTH:
                self._auth.state = await self._auth_trusted_auth()
            if self._auth.state == _AuthState.NEW_AUTH:
                self._auth.state = await self._auth_new_auth()
            if self._auth.state == _AuthState.VALIDATE_TOKEN:
                self._auth.state = await self._auth_validate()
            if self._auth.state == _AuthState.TRUST_BROWSER:
                self._auth.state = await self._auth_trust_browser()

        self._debug(f"auth: login exit state: {self._auth.state}")
        if self._auth.state != _AuthState.SUCCESS:
            return False

        self._last_login_time = time.monotonic()
        self._auth.force_reauth = False
        # We are in a successful state so:
        #  - save the session for reloading
        #  - save the cookies for reloading
        await self._req.save()
        await self._req.save_cookies()
        return True

    async def _login(self) -> bool:
        """Serialized wrapper around _login_locked to prevent concurrent auth attempts."""
        async with self._login_lock:
            self._req._is_logging_in = True
            try:
                return await self._login_locked()
            finally:
                self._req._is_logging_in = False

    async def _relogin(self) -> bool:
        async with self._login_lock:
            if time.monotonic() - self._last_login_time < 10:
                self._debug("relogin skipped: already logged in within last 10s")
                return True
            self._debug("re-logging in after 401 or token expiration")
            self._req._is_logging_in = True
            self._auth.force_reauth = True
            try:
                if await self._login_locked():
                    await self._event_reconnect()
                    return True
                return False
            finally:
                self._auth.force_reauth = False
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

    def _start_transaction(self, tid=None):
        if tid is None:
            tid = self.gen_trans_id()
        self._vdebug("starting transaction-->{}".format(tid))
        self._requests[tid] = {"event": asyncio.Event(), "response": None}
        return tid

    async def _wait_for_transaction(self, tid, timeout):
        if timeout is None:
            timeout = self._cfg.request_timeout

        self._vdebug("finishing transaction-->{}".format(tid))
        try:
            req = self._requests[tid]
            await asyncio.wait_for(req["event"].wait(), timeout)
            response = self._requests.pop(tid)["response"]
        except (KeyError, asyncio.TimeoutError):
            self._debug("got a key error or timeout")
            self._requests.pop(tid, None)
            response = None
        self._vdebug("finished transaction-->{}".format(tid))
        return response

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
            await self._event.loop_task

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
            tid = self._start_transaction()
            await self._notify(device_id, xcloud_id, body=body, trans_id=tid)
            return await self._wait_for_transaction(tid, timeout)
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
            tid = self._start_transaction(tid)
            await self._req.request(path, "POST", params, headers, False, raw, timeout)
            return await self._wait_for_transaction(tid, timeout)
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





