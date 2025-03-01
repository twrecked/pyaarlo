from __future__ import annotations

import pprint
import re
import threading
import time
import uuid
import cloudscraper
from enum import IntEnum

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
    TFA_CONSOLE_SOURCE,
    TFA_IMAP_SOURCE,
    TFA_REST_API_SOURCE,
    TRANSID_PREFIX,
)
from ...utils import now_strftime, time_to_arlotime, to_b64
from ..background import ArloBackground
from ..cfg import ArloCfg
from ..logger import ArloLogger
from .event import ArloEvent
from .session import ArloSession
from .tfa import Arlo2FAConsole, Arlo2FAImap, Arlo2FARestAPI, Arlo2FAPush


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
    state: _AuthState = _AuthState.STARTING
    headers: dict[str, str] | None = None
    browser_code = None
    factor_id: str | None = None
    factor_type: str | None = None
    needs_pairing: bool = False
    tfa_type: str | None = None
    tfa_handler: Arlo2FAConsole | Arlo2FAPush | Arlo2FAImap | Arlo2FARestAPI | None = None
    attempt: int = 4
    curves: list[str] = []


# include token and session details
class ArloBackEnd:

    _cfg: ArloCfg
    _log: ArloLogger
    _bg: ArloBackground

    # Exclusive access.
    _lock: threading.Condition = threading.Condition()

    # These affect how we talk to the backend.
    _multi_location: bool = False

    # This holds the request state.
    _req: ArloSession | None = None
    _req_lock: threading.Lock = threading.Lock()

    # This holds the auth details and state.
    _auth: _AuthDetails = _AuthDetails()

    # How we are talking to the backend.
    _event_stream: ArloEvent | None = None
    _event_stream_connected: bool = False
    _event_loop_thread: threading.Thread | None = None
    _event_loop_exiting: bool = False

    def __init__(self, cfg: ArloCfg, log: ArloLogger, bg: ArloBackground):

        self._cfg = cfg
        self._log = log
        self._bg = bg

        self._dump_file = self._cfg.dump_file

        self._requests = {}
        self._callbacks = {}
        self._resource_types = DEFAULT_RESOURCES

        # Create state..
        self._req = ArloSession(cfg, log)

        # Restore the persistent session information.
        self._req.load()
        if self._req.details.device_id is None:
            self.debug("created new user ID")
            self._req.details.device_id = str(uuid.uuid4())

        # Start the login
        self._logged_in = self._login() and self._session_finalize()
        if not self._logged_in:
            self.debug("failed to log in")
        return

    def _event_dispatcher(self, response):

        # get message type(s) and id(s)
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

        #
        # I'm trying to keep this as generic as possible... but it needs some
        # smarts to figure out where to send responses - the packets from Arlo
        # are anything but consistent...
        # See docs/packets for and idea of what we're parsing.
        #

        # Answer for async ping. Note and finish.
        # Packet type #1
        if resource.startswith("subscriptions/"):
            self.vdebug("packet: async ping response " + resource)
            return

        # These is a base station mode response. Find base station ID and
        # forward response.
        # Packet type #2
        if resource == "activeAutomations":
            self.debug("packet: base station mode response")
            for device_id in response:
                if device_id != "resource":
                    responses.append((device_id, resource, response[device_id]))

        # Mode update response
        # XXX these might be deprecated
        elif "states" in response:
            self.debug("packet: mode update")
            device_id = response.get("from", None)
            if device_id is not None:
                responses.append((device_id, "states", response["states"]))

        # These are individual device updates, they are usually used to signal
        # things like motion detection or temperature changes.
        # Packet type #3
        elif [x for x in self._resource_types if resource.startswith(x + "/")]:
            self.debug("packet: device update")
            device_id = resource.split("/")[1]
            responses.append((device_id, resource, response))

        # Base station its child device statuses. We split this apart here
        # and pass directly to the referenced devices.
        # Packet type #4
        elif resource == 'devices':
            self.debug("packet: base and child statuses")
            for device_id in response.get('devices', {}):
                self.debug(f"DEVICES={device_id}")
                props = response['devices'][device_id]
                responses.append((device_id, resource, props))

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
            device_id = response.get("deviceId",
                                     response.get("uniqueId",
                                                  response.get("locationId", None)))
            if device_id is not None:
                responses.append((device_id, resource, response))
            else:
                self.debug(f"unhandled response {resource} - {response}")

        # Now find something waiting for this/these.
        for device_id, resource, response in responses:
            cbs = []
            self.debug("sending {} to {}".format(resource, device_id))
            with self._lock:
                if device_id and device_id in self._callbacks:
                    cbs.extend(self._callbacks[device_id])
                if "all" in self._callbacks:
                    cbs.extend(self._callbacks["all"])
            for cb in cbs:
                self._bg.run(cb, resource=resource, event=response)

    def _event_connected_handler(self):
        with self._lock:
            self._event_stream_connected = True
            self._lock.notify_all()
        self.debug("event connected")
        return {
            "devices": self.devices()
        }

    def _event_reconnected_handler(self):
        self.debug("event re-connected")
        self.devices()

    def _event_response_handler(self, response):

        # Debugging.
        if self._dump_file is not None:
            with open(self._dump_file, "a") as dump:
                time_stamp = now_strftime("%Y-%m-%d %H:%M:%S.%f")
                dump.write(
                    "{}: {}\n".format(
                        time_stamp, pprint.pformat(response, indent=2)
                    )
                )
        self.vdebug(
            "packet-in=\n{}".format(pprint.pformat(response, indent=2))
        )

        # Run the dispatcher to set internal state and run callbacks.
        self._event_dispatcher(response)

        # is there a notify/post waiting for this response? If so, signal to waiting entity.
        tid = response.get("transId", None)
        resource = response.get("resource", None)
        device_id = response.get("from", None)
        with self._lock:
            # Transaction ID
            # Simple. We have a transaction ID, look for that. These are
            # usually returned by notify requests.
            if tid and tid in self._requests:
                self._requests[tid] = response
                self._lock.notify_all()

            # Resource
            # These are usually returned after POST requests. We trap these
            # to make async calls sync.
            if resource:
                # Historical. We are looking for a straight matching resource.
                if resource in self._requests:
                    self.vdebug("{} found by text!".format(resource))
                    self._requests[resource] = response
                    self._lock.notify_all()

                else:
                    # Complex. We are looking for a resource and-or
                    # deviceid matching a regex.
                    if device_id:
                        resource = "{}:{}".format(resource, device_id)
                        self.vdebug("{} bounded device!".format(resource))
                    for request in self._requests:
                        if re.match(request, resource):
                            self.vdebug(
                                "{} found by regex {}!".format(resource, request)
                            )
                            self._requests[request] = response
                            self._lock.notify_all()

    def _event_reconnect(self):
        self._event_stream.stop()

    def _event_loop_stop(self):
        self._event_loop_exiting = True

    def _event_loop(self):
        self.debug("re-logging in")

        while not self._event_loop_exiting:

            # say we're starting
            if self._dump_file is not None:
                with open(self._dump_file, "a") as dump:
                    time_stamp = now_strftime("%Y-%m-%d %H:%M:%S.%f")
                    dump.write("{}: {}\n".format(time_stamp, "event_thread start"))

            # login again if not first iteration, this will also create a new session
            while not self._logged_in:
                with self._lock:
                    self._lock.wait(5)
                self.debug("re-logging in")
                self._logged_in = self._login() and self._session_finalize()

            self.debug("starting event device")
            self._event_stream.run()
            self.debug("exited event device")

            # clear down and signal out
            with self._lock:
                self._client_connected = False
                self._requests = {}
                self._lock.notify_all()

            # restart login...
            self._logged_in = False

    def _tfa_start(self):
        """Determine which tfa mechanism to use and set up the handlers if needed.

        We have these options:
        - CONSOLE; input is typed in, message is usually sent by SMS or EMAIL and
          user has to type it
        - IMAP; code is sent by email and automtically read by pyaarlo
        - REST_API; deprecated...
        - PUSH; user has to accept a prompt on their Arlo app

        PUSH is odd because the code doesn't retrieve an otp, we have to wait for
        finishAuth to return a 200.
        """

        # Set some sane defaults.
        self._auth.tfa_type = self._cfg.tfa_source
        self._auth.factor_type = "BROWSER"

        # Pick the correct handler.
        if self._auth.tfa_type == TFA_CONSOLE_SOURCE:
            self._auth.tfa_handler = Arlo2FAConsole(self._cfg, self._log)
        elif self._auth.tfa_type == TFA_IMAP_SOURCE:
            self._auth.tfa_handler = Arlo2FAImap(self._cfg, self._log)
        elif self._auth.tfa_type == TFA_REST_API_SOURCE:
            self._auth.tfa_handler = Arlo2FARestAPI(self._cfg, self._log)
        else:
            self._auth.tfa_handler = Arlo2FAPush(self._cfg, self._log)
            self._auth.factor_type = ""

        # Make sure it's ready.
        self._auth.tfa_handler.start()

    def _tfa_get_code(self) -> str | None:
        """Get the "otp" from the tfa source.

        This returns one of 3 things:
         - a 6 digit one-time-pin code
         - None; meaning the tfa failed
         - an empty string which indicates "finishAuth" does the waiting
        """
        return self._auth.tfa_handler.get()

    def _tfa_stop(self):
        """Call any stop functionality need by the handler.
        """
        self._auth.tfa_handler.stop()
        self._auth.tfa_handler = None

    def _new_update_user_info(self, body):
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

        self._req.details.token = body["token"]
        self._req.details.user_id = body["userId"]
        self._req.details.token_expires_in = body["expiresIn"]

        self._req.details.token64 = to_b64(self._req.details.token)
        self._req.details.web_id = self._req.details.user_id + "_web"
        self._req.details.sub_id = "subscriptions/" + self._req.details.web_id

    def _auth_post(self, path, params=None, headers=None, raw=False, timeout=None, cookies=None):
        return self._req.request_tuple(
            path, "POST", params, headers, False, raw, timeout, self._cfg.auth_host, authpost=True, cookies=cookies
        )

    def _auth_get(
            self, path, params=None, headers=None, stream=False, raw=False, timeout=None, cookies=None
    ):
        return self._req.request_tuple(
            path, "GET", params, headers, stream, raw, timeout, self._cfg.auth_host, authpost=True, cookies=cookies
        )

    def _auth_options(
            self, path, headers=None, timeout=None
    ):
        return self._req.request(
            path, "OPTIONS", None, headers, False, False, timeout, self._cfg.auth_host, authpost=True
        )

    def _auth_find_factor_id(self) -> str | None:
        """Get list of suitable 2fa options.

        Then look at the user config and figure out which one is best
        suited for the operation.
        """
        self.debug("auth: finding factor id")

        # Get a list of factors to use.
        code, factors = self._auth_get(
            f"{AUTH_GET_FACTORS}?data = {int(time.time())}", {
            },
            self._auth.headers
        )
        if factors is None:
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

    def _auth_trust_browser(self) -> _AuthState:
        """Trust the device.

        If this is a new authentication we tell Arlo to trust this browser. Arlo
        then sets a cookie we can provide with startAuth later to skip the 2fa
        stage.
        """
        self.debug("auth: trusting")

        # If we have already paired we don't do it again.
        if not self._auth.needs_pairing:
            self.debug("auth: no pairing required")
            return _AuthState.SUCCESS

        # If we have no browser code there is nothing to pair.
        if self._auth.browser_code is None:
            self.debug("auth: pairing postponed")
            return _AuthState.SUCCESS

        # Start the pairing.
        code, body = self._auth_post(
            AUTH_START_PAIRING, {
                "factorAuthCode": self._auth.browser_code,
                "factorData": "",
                "factorType": "BROWSER"
            },
            self._auth.headers
        )
        if code != 200:
            self._log.error(f"login: auth pairing failed: {code} - {body}")
            return _AuthState.SUCCESS

        # We did it.
        self.debug("auth: pairing succeeded")
        return _AuthState.SUCCESS

    def _auth_validate(self) -> _AuthState:
        """Validate the token we have.

        Make sure the token we have is still good.
        """
        self.debug("auth: validating")

        # Update the token in the header to the new token.
        self._auth.headers["Authorization"] = self._req.details.token64

        code, validated = self._auth_get(
            f"{AUTH_VALIDATE_PATH}?data = {int(time.time())}", {
            },
            self._auth.headers
        )
        if validated is None:
            self._log.error("token validation failed")
            return _AuthState.FAILED

        return _AuthState.TRUST_BROWSER

    def _auth_new_auth(self) -> _AuthState:
        """We have to authenticate again.

        There are several steps to this:
         - get a suitable 2fa option
         - start the 2fa option we pick
         - start the authentication process with arlo
         - get the 2fa token
         - finish authentication with arlo

         finishAuth will give us a new token.
        """
        self.debug("auth: start new auth")

        # Find a factor ID to use
        self._auth.factor_id = self._auth_find_factor_id()
        if self._auth.factor_id is None:
            return _AuthState.FAILED
        self.debug(f"using factor id {self._auth.factor_id}")

        # Set up tfa. Call it now so it can capture state before we start
        # the authentication proper. For example, capture the current state
        # of an inbox before emails are sent.
        self._tfa_start()

        # Start authentication to send out code. Stop if this fails.
        self._auth_options(AUTH_START_PATH, self._auth.headers)
        code, body = self._auth_post(
            AUTH_START_PATH, {
                "factorId": self._auth.factor_id,
                "factorType": self._auth.factor_type,
                "userId": self._req.details.user_id
            },
            self._auth.headers
        )
        if code != 200:
            self._tfa_stop()
            self._log.error(f"login failed: new start failed1: {code} - {body}")
            return _AuthState.FAILED

        # We need this for the next step.
        factor_auth_code = body["factorAuthCode"]

        # Get otp.
        # XXX this can be a retry?
        otp = self._tfa_get_code()
        self._tfa_stop()

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
            self.debug(f"finishing auth attempt #{tries}")
            code, body = self._auth_post(
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
            time.sleep(self._cfg.tfa_delay)
            tries += 1

        self._log.error(f"login failed: finish failed: {code} - {body}")
        return _AuthState.FAILED

    def _auth_trusted_auth(self) -> _AuthState:
        """Arlo still trusts us.

        Send back the factor id that was passed. We have a cookie - browser_trust_* -
        that binds us to the id. If this works we move on to token validation.
        """
        self.debug("auth: start trusted auth")

        self._auth_options(AUTH_START_PATH, self._auth.headers)
        code, body = self._auth_post(
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

    def _auth_current_factor_id(self) -> _AuthState:
        """Get the current factor id

        If we have paired this "device" with Arlo before it will return an ID
        indicating we can skip the 2fa to get our session token. Otherwise
        it returns untrusted and we have to perform some 2fa operations.

        If we are already trusted we can skip pairing.
        """
        self.debug("auth: current factor id")

        # Retrieve current factor ID. If we have previously trusted this
        # "browser" we will be able to skip the 2fa section.
        self._auth_options(AUTH_GET_FACTORID, self._auth.headers)
        code, body = self._auth_post(
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

        # Look for a way to authenticate.
        return _AuthState.NEW_AUTH

    def _auth_get_connection(self) -> bool:
        """Keep track of connection attempts and curve tries.

        We make 3 attempts to login. Each attempt will try a different
        CloudFlare curve. Once we login we use the working connection
        for the next stage of the login.

        Note, these loops can be flipped if needed

        Before its first use:
         - set _auth.attempt to 1
         - set _auth.curves to []
        """

        while True:
            # We still have a curve to try? Grab a connection using it.
            if self._auth.curves:
                curve = self._auth.curves.pop(0)
                self.debug(f"auth: CloudFlare curve set to: {curve}")
                self._req.details.connection = cloudscraper.create_scraper(
                    # browser={
                    #     'browser': 'chrome',
                    #     'platform': 'darwin',
                    #     'desktop': True,
                    #     'mobile': False,
                    # },
                    disableCloudflareV1=True,
                    ecdhCurve=curve,
                    debug=False,
                )
                return True

            # Do we still have attempts left? Refill the curves and try the
            # next one.
            if self._auth.attempt < 4:
                self.debug(f"auth: login attempt #{self._auth.attempt}")
                self._auth.attempt += 1
                self._auth.curves = self._cfg.ecdh_curves
                self.debug(f"auth: login attempt #{self._auth.attempt - 1}, curves={self._auth.curves}")
                continue

            # We've failed...
            self.debug("auth: failed")
            self._req.details.connection = None
            break

        return False

    def _auth_revalidate_token(self) -> _AuthState:
        """See if we can skip auth by re-using the old token.
        """
        self.debug("auth: testing trust")

        # We haven't logged in at all yet.
        if self._req.details.token64 is None:
            self.debug("auth: nothing to test")
            return _AuthState.LOGIN

        # The current token has expired.
        self.debug(f"now={int(time.time())}, expires={int(self._req.details.token_expires_in - 300)}")
        if self._req.details.token_expires_in - 300 < time.time():
            self.debug("auth: login expired")
            return _AuthState.LOGIN

        while self._auth_get_connection():

            # Fix up the connection with saved state.
            self._req.details.connection.cookies = self._req.details.cookies
            self._auth.headers = self._req.auth_headers()
            self._auth.headers["Authorization"] = self._req.details.token64

            # Try the current token.
            state = self._auth_validate()
            if state != _AuthState.FAILED:
                self.debug("auth: testing ok")
                return _AuthState.SUCCESS

            # Don't try too hard.
            time.sleep(3)

        # Login...
        # Maybe reset here...
        return _AuthState.LOGIN

    def _auth_login(self) -> _AuthState:
        """Perform the actual login.

        This is when username and password get used. In an attempt to bypass
        cloudlfare issues it will try several different curve options.
        """
        self.debug("auth: logging in")

        while self._auth_get_connection():

            # Fix up the connection with saved state.
            self._req.details.connection.cookies = self._req.details.cookies
            self._auth.headers = self._req.auth_headers()

            # Attempt the auth.
            self._auth_options(AUTH_PATH, self._auth.headers)
            code, body = self._auth_post(
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
                self._auth.headers["Authorization"] = self._req.details.token64

                # See what state to move to next.
                if not body["authCompleted"]:
                    return _AuthState.CURRENT_FACTOR_ID
                else:
                    return _AuthState.VALIDATE_TOKEN

            # Flag the failure.
            self._log.error(f"login failed: {code} - possible cloudflare issue")

            # Wait before the next attempt.
            # XXX this can be indented to wait after every curve
            time.sleep(3)

        # Here means we're out of retries so stop now.
        self._log.error(f"login failed: no more curves - possible cloudflare issue")
        return _AuthState.FAILED

    def _auth_starting(self) -> _AuthState:
        """Clear auth state to a known starting point.
        """
        self.debug("auth: starting")

        self._req.load_cookies()
        self._req.details.user_agent = self._cfg.user_agent_string()
        self._req.details.connection = None
        self._auth.factor_id = None
        self._auth.needs_pairing = True
        self._auth.attempt = 1
        self._auth.curves = []

        return _AuthState.REVALIDATE_TOKEN

    def _login(self):
        """Perform all the steps to authenticate against the Arlo servers.
        """

        # Restart. We might be able to miss out the login stage and just try
        # for a factor-id.
        if self._auth.state != _AuthState.STARTING:
            self._auth.state = _AuthState.STARTING
            self.debug("auth: restarting")

        while self._auth.state != _AuthState.SUCCESS and self._auth.state != _AuthState.FAILED:
            if self._auth.state == _AuthState.STARTING:
                self._auth.state = self._auth_starting()
            if self._auth.state == _AuthState.REVALIDATE_TOKEN:
                self._auth.state = self._auth_revalidate_token()
            if self._auth.state == _AuthState.LOGIN:
                self._auth.state = self._auth_login()
            if self._auth.state == _AuthState.CURRENT_FACTOR_ID:
                self._auth.state = self._auth_current_factor_id()
            if self._auth.state == _AuthState.TRUSTED_AUTH:
                self._auth.state = self._auth_trusted_auth()
            if self._auth.state == _AuthState.NEW_AUTH:
                self._auth.state = self._auth_new_auth()
            if self._auth.state == _AuthState.VALIDATE_TOKEN:
                self._auth.state = self._auth_validate()
            if self._auth.state == _AuthState.TRUST_BROWSER:
                self._auth.state = self._auth_trust_browser()

        self.debug(f"auth: login exit state: {self._auth.state}")
        if self._auth.state != _AuthState.SUCCESS:
            return False

        # We are in a successful state so:
        #  - save the session for reloading
        #  - save the cookies for reloading
        #  - set up the connection headers for the non-authentication phase
        self._req.save()
        self._req.save_cookies()
        return True

    def _session_connection(self) -> bool:
        """Make sure the headers are set up for the non-auth phase.
        """
        self.debug("session: fixing connection")

        self._req.details.connection.headers.update(self._req.headers())
        return True

    def _session_v3_details(self) -> bool:
        """Read in the v3 session details.

        This provides us with the following information:
         - is multilocation on
         - the backend we are using
        """
        self.debug("session: getting v3 details")

        v3_session = self.get(SESSION_PATH)
        if v3_session is None:
            self._log.error("v3 session failed")
            return False

        # Multi-location is on?
        self._multi_location = v3_session.get('supportsMultiLocation', False)
        self.debug(f"multilocation is {self._multi_location}")

        # If Arlo provides an MQTT URL key use it to set the backend.
        if MQTT_URL_KEY in v3_session:
            self._cfg.update_mqtt_from_url(v3_session[MQTT_URL_KEY])
            self.debug(f"back={self._cfg.event_backend};url={self._cfg.mqtt_host}:{self._cfg.mqtt_port}")

        # Always good if the v3 read works.
        return True

    def _session_finalize(self) -> bool:
        """Set up for the post authentication phase.

        Update the connection headers to include the latest auth token and
        work out some important pieces of the user setup.
        """
        return self._session_connection() and self._session_v3_details()

    def _notify(self, device_id, xcloud_id, body, trans_id=None):
        if trans_id is None:
            trans_id = self.gen_trans_id()

        body["to"] = device_id
        if "from" not in body:
            body["from"] = self._req.details.web_id
        body["transId"] = trans_id

        response = self.post(
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
        self.vdebug("starting transaction-->{}".format(tid))
        with self._lock:
            self._requests[tid] = None
        return tid

    def _wait_for_transaction(self, tid, timeout):
        if timeout is None:
            timeout = self._cfg.request_timeout
        mnow = time.monotonic()
        mend = mnow + timeout

        self.vdebug("finishing transaction-->{}".format(tid))
        with self._lock:
            try:
                while mnow < mend and self._requests[tid] is None:
                    self._lock.wait(mend - mnow)
                    mnow = time.monotonic()
                response = self._requests.pop(tid)
            except KeyError as _e:
                self.debug("got a key error")
                response = None
        self.vdebug("finished transaction-->{}".format(tid))
        return response

    def gen_trans_id(self, trans_type=TRANSID_PREFIX):
        return trans_type + "!" + str(uuid.uuid4())

    def start_monitoring(self):
        # Build event details...
        self._event_stream = ArloEvent(self._cfg, self._log, self._bg, self._req.details,
                                       self._event_response_handler,
                                       self._event_connected_handler,
                                       self._event_reconnected_handler)
        self._event_stream.setup()

        self._event_stream_connected = False
        self._event_loop_thread = threading.Thread(
            name="ArloEventStream", target=self._event_loop, args=()
        )
        self._event_loop_thread.daemon = True

        with self._lock:
            self._event_loop_thread.start()
            count = 0
            while not self._event_stream_connected and count < 30:
                self.debug("waiting for stream up")
                self._lock.wait(1)
                count += 1

        # start logout daemon for sse clients
        if self._cfg.reconnect_every != 0:
            self.debug("automatically reconnecting")
            self._bg.run_every(self._event_reconnect, self._cfg.reconnect_every)

        self.debug("stream up")
        return True

    @property
    def is_connected(self):
        return self._logged_in

    def logout(self):
        self.debug("trying to logout")
        self._event_loop_stop()
        if self._event_stream is not None:
            self._event_stream.stop()
        self.put(LOGOUT_PATH)

    def notify(self, device_id, xcloud_id, body, timeout=None, wait_for=None):
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
            wait_for = "event" if self._cfg.synchronous_mode else "nothing"

        if wait_for == "event":
            self.vdebug("notify+event running")
            tid = self._start_transaction()
            self._notify(device_id, xcloud_id, body=body, trans_id=tid)
            return self._wait_for_transaction(tid, timeout)
            # return self._notify_and_get_event(base, body, timeout=timeout)
        elif wait_for == "response":
            self.vdebug("notify+response running")
            return self._notify(device_id, xcloud_id, body=body)
        else:
            self.vdebug("notify+sent")
            self._bg.run(self._notify, device_id=device_id, xcloud_id=xcloud_id, body=body)

    def get(
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
            self.vdebug("get+response running")
            return self._req.request(
                path, "GET", params, headers, stream, raw, timeout, host, cookies
            )
        else:
            self.vdebug("get sent")
            self._bg.run(
                self._req.request, path=path, method="GET", params=params, headers=headers, stream=stream, raw=raw, timeout=timeout, host=host
            )

    def put(
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
            self.vdebug("put+response running")
            return self._req.request(path, "PUT", params, headers, False, raw, timeout, cookies)
        else:
            self.vdebug("put sent")
            self._bg.run(
                self._req.request, path=path, method="PUT", params=params, headers=headers, stream=False, raw=raw, timeout=timeout
            )

    def post(
            self,
            path,
            params=None,
            headers=None,
            raw=False,
            timeout=None,
            tid=None,
            wait_for="response"
    ):
        """Post a request to the Arlo servers.

        Posts are used to retrieve data from the Arlo servers. Mostly. They are also used to change
        base station modes.

        The default mode of operation is to wait for a response from the http request. The `wait_for`
        variable can change the operation. Setting it to `response` waits for a http response.
        Setting it to `resource` waits for the resource in the `params` parameter to appear in the event
        stream. Setting it to `nothing` causing the post to run in the background. Setting it to `None`
        uses `resource` in synchronous mode and `response` in asynchronous mode.
        """
        if wait_for is None:
            wait_for = "resource" if self._cfg.synchronous_mode else "response"

        if wait_for == "resource":
            self.vdebug("notify+resource running")
            if tid is None:
                tid = list(params.keys())[0]
            tid = self._start_transaction(tid)
            self._req.request(path, "POST", params, headers, False, raw, timeout)
            return self._wait_for_transaction(tid, timeout)
        if wait_for == "response":
            self.vdebug("post+response running")
            return self._req.request(path, "POST", params, headers, False, raw, timeout)
        else:
            self.vdebug("post sent")
            self._bg.run(
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
        with self._lock:
            if device_id not in self._callbacks:
                self._callbacks[device_id] = []
            self._callbacks[device_id].append(callback)
            if unique_id not in self._callbacks:
                self._callbacks[unique_id] = []
            self._callbacks[unique_id].append(callback)

    def add_any_listener(self, callback):
        with self._lock:
            if "all" not in self._callbacks:
                self._callbacks["all"] = []
            self._callbacks["all"].append(callback)

    def del_listener(self, device, callback):
        pass

    def devices(self):
        return self.get(DEVICES_PATH + "?t={}".format(time_to_arlotime()))

    def ev_inject(self, response):
        self._event_dispatcher(response)

    def debug(self, msg):
        self._log.debug(f"backend: {msg}")

    def vdebug(self, msg):
        self._log.vdebug(f"backend: {msg}")
