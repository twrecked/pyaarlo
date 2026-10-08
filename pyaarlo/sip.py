"""SIP-over-WebSocket signaling for Arlo's live-streaming path.

Arlo's official apps - including my.arlo.com in a browser - negotiate live
video over WebRTC, signaled through a small, fixed set of SIP messages sent
over a WebSocket. This module reimplements just that signaling leg: it takes
a caller-supplied WebRTC offer SDP and returns Arlo's answer SDP. It never
touches media - on the streaming path, Arlo's own SIP proxy doesn't either
(see the module docstring on `ArloSip` for why that's true and where it
comes from).

This is intentionally not a general SIP stack. The message set Arlo's proxy
needs is exactly INVITE / ACK / MESSAGE / BYE, so those are hand-built and
hand-parsed rather than pulled in via a third-party SIP library.
"""

import hashlib
import random
import re
import string
import threading
import time
import uuid
from enum import Enum
from queue import Empty, Queue

import websocket

from .constant import ORIGIN_HOST, SIP_INFO_V2_PATH, USER_AGENTS
from .sdp import clean_answer, filter_offer_candidates

WS_PORT = 7443
DEFAULT_TIMEOUT = 5
DEFAULT_KEEPALIVE_INTERVAL = 30
SIP_USER_AGENT = "SIP.js/0.21.1"

_RAND_ALPHABET = string.ascii_lowercase + string.digits


class ArloSipError(Exception):
    """Base class for all SIP signaling errors."""


class ArloSipAuthError(ArloSipError):
    """Raised when SIP digest authentication fails or is unsupported."""


class ArloSipTimeout(ArloSipError):
    """Raised when a SIP transaction gets no final response in time."""


class ArloSipProtocolError(ArloSipError):
    """Raised when Arlo's SIP proxy returns something unparsable or unexpected."""


class SipState(Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    AUTHENTICATING = "authenticating"
    ESTABLISHED = "established"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"
    RECONNECTING = "reconnecting"


# ---------------------------------------------------------------------------
# Pure helpers - no I/O, no shared state, fully unit-testable.
# ---------------------------------------------------------------------------


def _rand_string(length):
    return "".join(random.choice(_RAND_ALPHABET) for _ in range(length))


def _rand_digits(length):
    return "".join(random.choice(string.digits) for _ in range(length))


def gen_branch():
    return "z9hG4bK" + _rand_digits(7)


def gen_tag():
    return _rand_string(8)


def gen_call_id():
    return uuid.uuid4().hex


def gen_contact_host():
    return _rand_string(12) + ".invalid"


def _md5(*parts):
    return hashlib.md5(":".join(parts).encode("utf-8")).hexdigest()


class SipMessage(object):
    """A single SIP request or response.

    Headers are kept as an ordered list of (name, value) pairs rather than a
    dict, since SIP allows repeated headers (`Via`, `Record-Route`) and
    order matters on the wire.
    """

    def __init__(self, start_line, headers=None, body=""):
        self.start_line = start_line
        self.headers = list(headers) if headers else []
        self.body = body

    def add_header(self, name, value):
        self.headers.append((name, value))

    def get_header(self, name):
        name = name.lower()
        for hname, hvalue in self.headers:
            if hname.lower() == name:
                return hvalue
        return None

    def get_headers(self, name):
        name = name.lower()
        return [hvalue for hname, hvalue in self.headers if hname.lower() == name]

    @property
    def is_response(self):
        return self.start_line.startswith("SIP/2.0")

    @property
    def status_code(self):
        if not self.is_response:
            return None
        return int(self.start_line.split(" ", 2)[1])

    @property
    def method(self):
        if self.is_response:
            cseq = self.get_header("CSeq")
            if not cseq:
                return None
            parts = cseq.split()
            return parts[1] if len(parts) > 1 else None
        return self.start_line.split(" ", 1)[0]

    @property
    def cseq_number(self):
        cseq = self.get_header("CSeq")
        if not cseq:
            return None
        return int(cseq.split()[0])

    def to_wire(self):
        lines = [self.start_line]
        body_bytes = self.body.encode("utf-8")
        for name, value in self.headers:
            lines.append(f"{name}: {value}")
        lines.append(f"Content-Length: {len(body_bytes)}")
        return "\r\n".join(lines) + "\r\n\r\n" + self.body

    @classmethod
    def parse(cls, raw):
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        head, _, body = raw.partition("\r\n\r\n")
        lines = head.split("\r\n")
        if not lines or not lines[0]:
            raise ArloSipProtocolError("empty SIP message")
        start_line = lines[0]
        headers = []
        for line in lines[1:]:
            if not line:
                continue
            name, sep, value = line.partition(":")
            if not sep:
                continue
            headers.append((name.strip(), value.strip()))
        message = cls(start_line, headers, body)
        content_length = message.get_header("Content-Length")
        if content_length is not None:
            try:
                message.body = body[: int(content_length)]
            except ValueError:
                pass
        return message


class AuthHeader(object):
    """A SIP `Proxy-Authenticate` / `Proxy-Authorization` header.

    Only MD5 digest with `qop=auth` is supported - the only scheme Arlo's
    SIP proxy has been observed to request.
    """

    UNQUOTED_PARAMS = ("algorithm", "qop", "nc")

    def __init__(self, mode="Digest", params=None):
        self.mode = mode
        self.params = dict(params) if params else {}

    @classmethod
    def parse(cls, value):
        if value is None:
            raise ArloSipProtocolError("missing Proxy-Authenticate header")
        mode, _, rest = value.partition(" ")
        params = {}
        for name, raw_value in re.findall(r'(\w+)=("[^"]*"|[^,]+)', rest):
            params[name] = raw_value.strip().strip('"')
        return cls(mode, params)

    def __str__(self):
        rendered = []
        for key, value in self.params.items():
            if key in self.UNQUOTED_PARAMS:
                rendered.append(f"{key}={value}")
            else:
                rendered.append(f'{key}="{value}"')
        return f"{self.mode} {', '.join(rendered)}"

    def compute_response(self, method, uri, username, password):
        """Fills in `username`, `uri`, `cnonce`, `nc` and `response` for a
        qop=auth MD5 digest, given the challenge parameters already parsed
        into `self.params` (`realm`, `nonce`, and optionally `algorithm`).
        """
        algorithm = self.params.get("algorithm", "MD5")
        if algorithm != "MD5":
            raise ArloSipAuthError(f"unsupported digest algorithm: {algorithm}")
        if self.params.get("qop") != "auth":
            raise ArloSipAuthError(f"unsupported qop: {self.params.get('qop')}")
        if "realm" not in self.params or "nonce" not in self.params:
            raise ArloSipAuthError("challenge is missing realm or nonce")

        self.params["username"] = username
        self.params["uri"] = uri
        self.params.setdefault("cnonce", _rand_string(12))
        self.params.setdefault("nc", "00000001")

        ha1 = _md5(username, self.params["realm"], password)
        ha2 = _md5(method, uri)
        self.params["response"] = _md5(
            ha1,
            self.params["nonce"],
            self.params["nc"],
            self.params["cnonce"],
            self.params["qop"],
            ha2,
        )
        return self.params["response"]


# ---------------------------------------------------------------------------
# Message builders - pure functions of their arguments, no randomness unless
# the caller omits an id (in which case the module-level generators above
# are used, keeping tests able to pin every value explicitly).
# ---------------------------------------------------------------------------

ALLOW_HEADER = "ACK,CANCEL,INVITE,MESSAGE,BYE,OPTIONS,INFO,NOTIFY,REFER"


def build_invite(
    caller_uri,
    callee_uri,
    contact_host,
    device_id,
    sdp,
    user_agent,
    call_id,
    tag,
    contact_user,
    cseq=1,
    branch=None,
    proxy_authorization=None,
):
    branch = branch or gen_branch()
    message = SipMessage(f"INVITE {callee_uri} SIP/2.0")
    message.add_header("Via", f"SIP/2.0/WSS {contact_host};branch={branch}")
    message.add_header("Max-Forwards", "70")
    message.add_header("From", f'"WebRTC-UDP" <{caller_uri}>;tag={tag}')
    message.add_header("To", f"<{callee_uri}>")
    message.add_header("Call-ID", call_id)
    message.add_header("CSeq", f"{cseq} INVITE")
    message.add_header("Contact", f"<sip:{contact_user}@{contact_host};transport=ws;ob>")
    message.add_header("Allow", ALLOW_HEADER)
    message.add_header("Supported", "outbound")
    message.add_header("User-Agent", user_agent)
    # This is what routes the call to the specific camera - the proxy has no
    # other way to tell which device on the account should pick up.
    message.add_header("X-extension", f"{device_id}; User-Agent: webrtc")
    if proxy_authorization is not None:
        message.add_header("Proxy-Authorization", proxy_authorization)
    message.add_header("Content-Type", "application/sdp")
    message.body = sdp
    return message


def build_ack_from_response(response, callee_uri, contact_host, user_agent):
    """Builds the ACK for a response to INVITE.

    Reuses the response's Call-ID, CSeq number, and its From/To headers
    verbatim (they already carry the tags both sides agreed on), and turns
    any Record-Route headers into a reversed Route set, per RFC 3261.
    """
    message = SipMessage(f"ACK {callee_uri} SIP/2.0")
    message.add_header("Via", f"SIP/2.0/WSS {contact_host};branch={gen_branch()}")
    message.add_header("Max-Forwards", "70")
    message.add_header("From", response.get_header("From"))
    message.add_header("To", response.get_header("To"))
    for route in reversed(response.get_headers("Record-Route")):
        message.add_header("Route", route)
    message.add_header("Call-ID", response.get_header("Call-ID"))
    message.add_header("CSeq", f"{response.cseq_number} ACK")
    message.add_header("Supported", "outbound")
    message.add_header("User-Agent", user_agent)
    return message


def build_bye_from_response(response, callee_uri, contact_host, user_agent):
    """Builds a BYE that closes the dialog established by `response`.

    Same shape as the matching ACK (same dialog identifiers, reversed
    Route set) but with its own CSeq, one past the response's.
    """
    message = build_ack_from_response(response, callee_uri, contact_host, user_agent)
    message.start_line = f"BYE {callee_uri} SIP/2.0"
    message.headers = [(name, value) for name, value in message.headers if name.lower() != "cseq"]
    message.add_header("CSeq", f"{response.cseq_number + 1} BYE")
    return message


def build_message(caller_uri, callee_uri, contact_host, payload, user_agent):
    """Builds a SIP MESSAGE request - each one is its own fresh dialog."""
    message = SipMessage(f"MESSAGE {callee_uri} SIP/2.0")
    message.add_header("Via", f"SIP/2.0/WSS {contact_host};branch={gen_branch()}")
    message.add_header("Max-Forwards", "70")
    message.add_header("From", f"<{caller_uri}>;tag={gen_tag()}")
    message.add_header("To", f"<{callee_uri}>")
    message.add_header("Call-ID", gen_call_id())
    message.add_header("CSeq", "1 MESSAGE")
    message.add_header("Supported", "outbound")
    message.add_header("User-Agent", user_agent)
    message.add_header("Content-Type", "text/plain")
    message.body = payload
    return message


# ---------------------------------------------------------------------------
# The stateful client.
# ---------------------------------------------------------------------------


class ArloSip(object):
    """SIP-over-WebSocket signaling client for Arlo's live-streaming path.

    On this path Arlo's own SIP helper is documented (in the third-party Go
    client this was reverse-engineered against) as pure signaling: "if an
    SDP is provided, it is assumed that the caller will manage the media
    traffic, and this SIP client is only used to manage signaling." This
    class does exactly that - it takes an offer SDP the caller already built
    against `ice_servers`, and returns Arlo's answer SDP. It never creates a
    peer connection and never sees a media packet.

    One instance is one call attempt - it is not reused across streams.
    Not thread-safe for concurrent callers; internally it runs a dedicated
    reader thread and (once established) a keepalive thread, both daemon
    threads distinct from pyaarlo's shared background worker.

    Usage::

        sip = ArloSip(arlo, camera)
        sip.connect()                    # fetches sipCallInfo + iceServers, opens the websocket
        offer = build_offer(sip.ice_servers)   # caller's own WebRTC stack
        answer = sip.start(offer)        # INVITE / digest auth / ACK -> Arlo's answer SDP
        ...
        sip.close()
    """

    def __init__(
        self,
        arlo,
        camera,
        timeout=None,
        keepalive_interval=None,
        sip_user_agent=None,
        ws_user_agent=None,
        ws_port=None,
    ):
        self._arlo = arlo
        self._camera = camera
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._keepalive_interval = keepalive_interval or DEFAULT_KEEPALIVE_INTERVAL
        self._sip_user_agent = sip_user_agent or SIP_USER_AGENT
        self._ws_user_agent = ws_user_agent or USER_AGENTS["firefox"]
        self._ws_port = ws_port or WS_PORT

        self._state = SipState.IDLE
        self._state_lock = threading.RLock()

        self._ws = None
        self._send_lock = threading.Lock()
        self._reader_thread = None
        self._keepalive_thread = None
        self._stop_event = threading.Event()

        self._pending = {}
        self._pending_lock = threading.Lock()

        self._sip_info = None
        self._caller_uri = None
        self._callee_uri = None
        self._username = None
        self._password = None
        self._contact_host = gen_contact_host()
        self._contact_user = _rand_string(8)
        self._call_id = None
        self._tag = None
        self._cseq = 1
        self._last_response = None

    # -- state -------------------------------------------------------------

    @property
    def state(self):
        with self._state_lock:
            return self._state

    def _set_state(self, state):
        with self._state_lock:
            self._arlo.debug(f"sip: {self._camera.device_id}: {self._state.value} -> {state.value}")
            self._state = state

    # -- bootstrap -----------------------------------------------------------

    def _fetch_sip_info(self):
        params = {
            "cameraId": self._camera.device_id,
            "modelId": (self._camera.model_id or "").upper(),
            "uniqueId": self._camera.unique_id,
        }
        headers = {
            "xcloudId": self._camera.xcloud_id,
            "cameraId": self._camera.device_id,
        }
        # No raw=True here: unlike the capabilities document (a static file,
        # no envelope), sipInfo/v2 is a normal /hmsweb/ endpoint wrapped in
        # Arlo's {"success": ..., "data": {...}} envelope, which pyaarlo's
        # backend already unwraps for us by default.
        response = self._arlo.be.get(SIP_INFO_V2_PATH, params=params, headers=headers)
        if not isinstance(response, dict) or "sipCallInfo" not in response:
            raise ArloSipProtocolError(
                f"no sipInfo for camera {self._camera.device_id}: got {response!r}"
            )
        return response

    @property
    def ice_servers(self):
        """Returns Arlo's published ICE servers, shaped for an RTCConfiguration.

        `[]` until `fetch_info()` (or `connect()`, which calls it) has run.
        """
        if self._sip_info is None:
            return []
        servers = []
        for entry in self._sip_info.get("iceServers", {}).get("data", []):
            servers.append(
                {
                    "urls": [f"{entry['type']}:{entry['domain']}:{entry['port']}"],
                    "username": entry.get("username"),
                    "credential": entry.get("credential"),
                }
            )
        return servers

    def fetch_info(self):
        """Fetches the SIP credentials and ICE servers over REST only.

        Split out from `connect()` because a caller needs `ice_servers`
        *before* it can build the offer SDP, and the gap between the two can
        be seconds long - a browser gathering ICE candidates, say. Opening
        the websocket that early would just leave it idle for that whole
        window. Idempotent; the result is cached on the instance.
        """
        if self._sip_info is not None:
            return self._sip_info

        sip_info = self._fetch_sip_info()
        call_info = sip_info["sipCallInfo"]
        domain = call_info["domain"]

        self._username = call_info["id"]
        self._password = call_info["password"]
        self._caller_uri = f"sip:{call_info['id']}@{domain}:{self._ws_port}"
        self._callee_uri = call_info["calleeUri"]
        self._sip_info = sip_info
        return sip_info

    def ensure_connected(self):
        """Opens the signaling websocket unless it's already open."""
        if self.state == SipState.IDLE:
            self.connect()

    def connect(self):
        """Fetches SIP credentials if needed, then opens the signaling websocket."""
        if self.state != SipState.IDLE:
            raise ArloSipError(f"cannot connect from state {self.state.value}")
        try:
            self._set_state(SipState.CONNECTING)
            self.fetch_info()
            domain = self._sip_info["sipCallInfo"]["domain"]

            url = f"wss://{domain}:{self._ws_port}"
            self._arlo.debug(f"sip: connecting to {url}")
            self._ws = websocket.create_connection(
                url,
                subprotocols=["sip"],
                origin=ORIGIN_HOST,
                header=[f"User-Agent: {self._ws_user_agent}"],
                timeout=self._timeout,
            )
            self._stop_event.clear()
            self._reader_thread = threading.Thread(
                target=self._reader_loop, name=f"ArloSipReader-{self._camera.device_id}", daemon=True
            )
            self._reader_thread.start()
        except ArloSipError:
            self._set_state(SipState.FAILED)
            self.close()
            raise
        except Exception as e:
            self._set_state(SipState.FAILED)
            self.close()
            raise ArloSipError(f"connect failed: {type(e).__name__}: {e}") from e

    # -- reader thread -------------------------------------------------------

    def _reader_loop(self):
        while not self._stop_event.is_set():
            try:
                raw = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                self._arlo.debug(f"sip: {self._camera.device_id}: reader stopped: {type(e).__name__}")
                break
            if not raw:
                continue
            try:
                message = SipMessage.parse(raw)
            except ArloSipProtocolError as e:
                self._arlo.debug(f"sip: {self._camera.device_id}: unparsable message: {e}")
                continue
            self._dispatch(message)

    def _dispatch(self, message):
        if not message.is_response:
            self._arlo.debug(f"sip: {self._camera.device_id}: dropping unexpected request {message.start_line}")
            return
        key = (message.get_header("Call-ID"), message.cseq_number, message.method)
        with self._pending_lock:
            queue = self._pending.get(key)
        if queue is None:
            self._arlo.vdebug(f"sip: {self._camera.device_id}: dropping unmatched response {message.start_line}")
            return
        queue.put(message)

    # -- transactions --------------------------------------------------------

    def _send(self, message):
        with self._send_lock:
            if self._ws is None:
                raise ArloSipError("not connected")
            self._ws.send(message.to_wire())

    def _send_and_wait(self, message, timeout=None):
        """Sends a request and waits for its final (non-1xx) response.

        Registration happens before the send so a fast reply can never
        race ahead of us starting to listen for it.
        """
        timeout = timeout or self._timeout
        key = (message.get_header("Call-ID"), message.cseq_number, message.method)
        queue = Queue()
        with self._pending_lock:
            self._pending[key] = queue
        try:
            self._send(message)
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ArloSipTimeout(f"no response to {message.method} within {timeout}s")
                try:
                    response = queue.get(timeout=remaining)
                except Empty:
                    raise ArloSipTimeout(f"no response to {message.method} within {timeout}s")
                if response.status_code < 200:
                    continue
                return response
        finally:
            with self._pending_lock:
                self._pending.pop(key, None)

    # -- call setup -----------------------------------------------------------

    def start(self, offer_sdp):
        """Negotiates the call and returns Arlo's (repaired) answer SDP.

        `offer_sdp` must already be a complete WebRTC offer built by the
        caller's own peer connection against `ice_servers` - this class
        does not create one.
        """
        if self.state != SipState.CONNECTING:
            raise ArloSipError(f"cannot start from state {self.state.value}; call connect() first")
        try:
            self._set_state(SipState.AUTHENTICATING)

            offer_sdp = filter_offer_candidates(offer_sdp)
            self._call_id = gen_call_id()
            self._tag = gen_tag()

            invite = build_invite(
                self._caller_uri,
                self._callee_uri,
                self._contact_host,
                self._camera.device_id,
                offer_sdp,
                self._sip_user_agent,
                call_id=self._call_id,
                tag=self._tag,
                contact_user=self._contact_user,
                cseq=self._cseq,
            )
            response = self._send_and_wait(invite)

            if response.status_code == 407:
                self._send(build_ack_from_response(response, self._callee_uri, self._contact_host, self._sip_user_agent))

                challenge = AuthHeader.parse(response.get_header("Proxy-Authenticate"))
                challenge.compute_response("INVITE", self._callee_uri, self._username, self._password)

                self._cseq += 1
                invite = build_invite(
                    self._caller_uri,
                    self._callee_uri,
                    self._contact_host,
                    self._camera.device_id,
                    offer_sdp,
                    self._sip_user_agent,
                    call_id=self._call_id,
                    tag=self._tag,
                    contact_user=self._contact_user,
                    cseq=self._cseq,
                    proxy_authorization=str(challenge),
                )
                response = self._send_and_wait(invite)

            if response.status_code != 200:
                raise ArloSipProtocolError(f"INVITE rejected: {response.start_line}")
            if "application/sdp" not in (response.get_header("Content-Type") or ""):
                raise ArloSipProtocolError("200 OK did not carry an SDP answer")

            self._last_response = response
            self._send(build_ack_from_response(response, self._callee_uri, self._contact_host, self._sip_user_agent))

            answer_sdp = clean_answer(response.body)

            self._start_keepalive()
            self._set_state(SipState.ESTABLISHED)
            return answer_sdp
        except ArloSipError:
            self._set_state(SipState.FAILED)
            self.close()
            raise

    # -- keepalive -------------------------------------------------------------

    def _start_keepalive(self):
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, name=f"ArloSipKeepalive-{self._camera.device_id}", daemon=True
        )
        self._keepalive_thread.start()

    def _keepalive_loop(self):
        while not self._stop_event.wait(self._keepalive_interval):
            if self.state != SipState.ESTABLISHED:
                return
            try:
                message = build_message(
                    self._caller_uri, self._callee_uri, self._contact_host, "keepAlive", self._sip_user_agent
                )
                response = self._send_and_wait(message)
                if response.status_code != 202:
                    raise ArloSipProtocolError(f"keepAlive rejected: {response.start_line}")
            except ArloSipError as e:
                self._arlo.debug(f"sip: {self._camera.device_id}: keepalive failed, closing: {e}")
                self._set_state(SipState.FAILED)
                self.close()
                return

    # -- teardown ---------------------------------------------------------------

    def close(self):
        """Idempotent teardown: BYE if a dialog was established, close the
        websocket, stop and join both threads. Safe to call from any state,
        including after a failed `connect()`/`start()`.
        """
        with self._state_lock:
            if self._state in (SipState.CLOSED, SipState.CLOSING):
                return
            established = self._state == SipState.ESTABLISHED
            self._state = SipState.CLOSING

        self._stop_event.set()

        if established and self._last_response is not None:
            try:
                bye = build_bye_from_response(
                    self._last_response, self._callee_uri, self._contact_host, self._sip_user_agent
                )
                self._send(bye)
            except ArloSipError as e:
                self._arlo.debug(f"sip: {self._camera.device_id}: could not send BYE: {e}")

        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

        current = threading.current_thread()
        if self._keepalive_thread is not None and self._keepalive_thread is not current and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=self._timeout)
        if self._reader_thread is not None and self._reader_thread is not current and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=self._timeout)

        self._set_state(SipState.CLOSED)
