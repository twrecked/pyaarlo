"""SIP-over-WebSocket signaling for Arlo's live-streaming path.

Arlo's official apps - including my.arlo.com in a browser - negotiate live
video over WebRTC, signaled through a small, fixed set of SIP messages sent
over a WebSocket. This module reimplements just that signaling leg: it takes
a caller-supplied WebRTC offer SDP and returns Arlo's answer SDP. It never
touches media - on the streaming path, Arlo's own SIP proxy doesn't either.

This is intentionally not a general SIP stack. The message set Arlo's proxy
needs is exactly INVITE / ACK / MESSAGE / BYE, so those are hand-built and
hand-parsed rather than pulled in via a third-party SIP library.

Credit: Edwin Anne (https://github.com/twrecked/pyaarlo/pull/210)
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import re
import string
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from .constant import ORIGIN_HOST, SIP_INFO_V2_PATH, USER_AGENTS
from .sdp import clean_answer, filter_offer_candidates

if TYPE_CHECKING:
    from .camera import ArloCamera
    from .core import ArloCore

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


def _rand_string(length: int) -> str:
    return "".join(random.choice(_RAND_ALPHABET) for _ in range(length))


def _rand_digits(length: int) -> str:
    return "".join(random.choice(string.digits) for _ in range(length))


def gen_branch() -> str:
    return "z9hG4bK" + _rand_digits(7)


def gen_tag() -> str:
    return _rand_string(8)


def gen_call_id() -> str:
    return uuid.uuid4().hex


def gen_contact_host() -> str:
    return _rand_string(12) + ".invalid"


def _md5(*parts: str) -> str:
    return hashlib.md5(":".join(parts).encode("utf-8")).hexdigest()


class SipMessage:
    """A single SIP request or response.

    Headers are kept as an ordered list of (name, value) pairs rather than a
    dict, since SIP allows repeated headers (`Via`, `Record-Route`) and
    order matters on the wire.
    """

    def __init__(
        self,
        start_line: str,
        headers: list[tuple[str, str]] | None = None,
        body: str = "",
    ):
        self.start_line = start_line
        self.headers = list(headers) if headers else []
        self.body = body

    def add_header(self, name: str, value: str) -> None:
        self.headers.append((name, value))

    def get_header(self, name: str) -> str | None:
        name_lower = name.lower()
        for hname, hvalue in self.headers:
            if hname.lower() == name_lower:
                return hvalue
        return None

    def get_headers(self, name: str) -> list[str]:
        name_lower = name.lower()
        return [hvalue for hname, hvalue in self.headers if hname.lower() == name_lower]

    @property
    def is_response(self) -> bool:
        return self.start_line.startswith("SIP/2.0")

    @property
    def status_code(self) -> int | None:
        if not self.is_response:
            return None
        return int(self.start_line.split(" ", 2)[1])

    @property
    def method(self) -> str | None:
        if self.is_response:
            cseq = self.get_header("CSeq")
            if not cseq:
                return None
            parts = cseq.split()
            return parts[1] if len(parts) > 1 else None
        return self.start_line.split(" ", 1)[0]

    @property
    def cseq_number(self) -> int | None:
        cseq = self.get_header("CSeq")
        if not cseq:
            return None
        return int(cseq.split()[0])

    def to_wire(self) -> str:
        lines = [self.start_line]
        body_bytes = self.body.encode("utf-8")
        for name, value in self.headers:
            lines.append(f"{name}: {value}")
        lines.append(f"Content-Length: {len(body_bytes)}")
        return "\r\n".join(lines) + "\r\n\r\n" + self.body

    @classmethod
    def parse(cls, raw: str | bytes) -> SipMessage:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        head, _, body = raw.partition("\r\n\r\n")
        lines = head.split("\r\n")
        if not lines or not lines[0]:
            raise ArloSipProtocolError("empty SIP message")
        start_line = lines[0]
        headers: list[tuple[str, str]] = []
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


class AuthHeader:
    """A SIP `Proxy-Authenticate` / `Proxy-Authorization` header.

    Only MD5 digest with `qop=auth` is supported - the only scheme Arlo's
    SIP proxy has been observed to request.
    """

    UNQUOTED_PARAMS = ("algorithm", "qop", "nc")

    def __init__(self, mode: str = "Digest", params: dict[str, str] | None = None):
        self.mode = mode
        self.params: dict[str, str] = dict(params) if params else {}

    @classmethod
    def parse(cls, value: str | None) -> AuthHeader:
        if value is None:
            raise ArloSipProtocolError("missing Proxy-Authenticate header")
        mode, _, rest = value.partition(" ")
        params: dict[str, str] = {}
        for name, raw_value in re.findall(r'(\w+)=("[^"]*"|[^,]+)', rest):
            params[name] = raw_value.strip().strip('"')
        return cls(mode, params)

    def __str__(self) -> str:
        rendered: list[str] = []
        for key, value in self.params.items():
            if key in self.UNQUOTED_PARAMS:
                rendered.append(f"{key}={value}")
            else:
                rendered.append(f'{key}="{value}"')
        return f"{self.mode} {', '.join(rendered)}"

    def compute_response(self, method: str, uri: str, username: str, password: str) -> str:
        """Fills in challenge parameters for a qop=auth MD5 digest."""
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
# Message builders
# ---------------------------------------------------------------------------

ALLOW_HEADER = "ACK,CANCEL,INVITE,MESSAGE,BYE,OPTIONS,INFO,NOTIFY,REFER"


def build_invite(
    caller_uri: str,
    callee_uri: str,
    contact_host: str,
    device_id: str,
    sdp: str,
    user_agent: str,
    call_id: str,
    tag: str,
    contact_user: str,
    cseq: int = 1,
    branch: str | None = None,
    proxy_authorization: str | None = None,
) -> SipMessage:
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
    message.add_header("X-extension", f"{device_id}; User-Agent: webrtc")
    if proxy_authorization is not None:
        message.add_header("Proxy-Authorization", proxy_authorization)
    message.add_header("Content-Type", "application/sdp")
    message.body = sdp
    return message


def build_ack_from_response(
    response: SipMessage, callee_uri: str, contact_host: str, user_agent: str
) -> SipMessage:
    """Builds the ACK for a response to INVITE."""
    message = SipMessage(f"ACK {callee_uri} SIP/2.0")
    message.add_header("Via", f"SIP/2.0/WSS {contact_host};branch={gen_branch()}")
    message.add_header("Max-Forwards", "70")
    from_header = response.get_header("From")
    if from_header:
        message.add_header("From", from_header)
    to_header = response.get_header("To")
    if to_header:
        message.add_header("To", to_header)
    for route in reversed(response.get_headers("Record-Route")):
        message.add_header("Route", route)
    call_id = response.get_header("Call-ID")
    if call_id:
        message.add_header("Call-ID", call_id)
    message.add_header("CSeq", f"{response.cseq_number} ACK")
    message.add_header("Supported", "outbound")
    message.add_header("User-Agent", user_agent)
    return message


def build_bye_from_response(
    response: SipMessage, callee_uri: str, contact_host: str, user_agent: str
) -> SipMessage:
    """Builds a BYE that closes the dialog established by `response`."""
    message = build_ack_from_response(response, callee_uri, contact_host, user_agent)
    message.start_line = f"BYE {callee_uri} SIP/2.0"
    message.headers = [(name, value) for name, value in message.headers if name.lower() != "cseq"]
    message.add_header("CSeq", f"{(response.cseq_number or 0) + 1} BYE")
    return message


def build_message(
    caller_uri: str, callee_uri: str, contact_host: str, payload: str, user_agent: str
) -> SipMessage:
    """Builds a SIP MESSAGE request."""
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
# The async stateful client.
# ---------------------------------------------------------------------------


class ArloSip:
    """Async SIP-over-WebSocket signaling client for Arlo's live-streaming path.

    Handles SIP signaling over WebSocket to establish live WebRTC streaming:
    takes an offer SDP and negotiates Arlo's answer SDP. Never touches media.
    """

    def __init__(
        self,
        core_or_arlo: Any,
        camera: Any,
        timeout: int | None = None,
        keepalive_interval: int | None = None,
        sip_user_agent: str | None = None,
        ws_user_agent: str | None = None,
        ws_port: int | None = None,
    ):
        self._core: Any = getattr(core_or_arlo, "_core", core_or_arlo)
        self._camera = camera

        cfg = getattr(self._core, "cfg", None)
        cfg_timeout = getattr(cfg, "sip_timeout", DEFAULT_TIMEOUT) if cfg else DEFAULT_TIMEOUT
        cfg_keepalive = getattr(cfg, "sip_keepalive", DEFAULT_KEEPALIVE_INTERVAL) if cfg else DEFAULT_KEEPALIVE_INTERVAL
        cfg_sip_ua = getattr(cfg, "sip_user_agent", SIP_USER_AGENT) if cfg else SIP_USER_AGENT
        cfg_ws_port = getattr(cfg, "sip_ws_port", WS_PORT) if cfg else WS_PORT

        self._timeout: int = timeout or cfg_timeout
        self._keepalive_interval: int = keepalive_interval or cfg_keepalive
        self._sip_user_agent: str = sip_user_agent or cfg_sip_ua
        self._ws_user_agent: str = ws_user_agent or USER_AGENTS["firefox"]
        self._ws_port: int = ws_port or cfg_ws_port

        self._state = SipState.IDLE
        self._ws: aiohttp.ClientWebSocketResponse | Any = None
        self._session: aiohttp.ClientSession | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._closing: bool = False

        self._pending: dict[tuple[str | None, int | None, str | None], asyncio.Queue[SipMessage]] = {}

        self._sip_info: dict[str, Any] | None = None
        self._caller_uri: str | None = None
        self._callee_uri: str | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._contact_host = gen_contact_host()
        self._contact_user = _rand_string(8)
        self._call_id: str | None = None
        self._tag: str | None = None
        self._cseq = 1
        self._last_response: SipMessage | None = None

    @property
    def _arlo(self) -> Any:
        return self._core

    @property
    def state(self) -> SipState:
        return self._state

    def _set_state(self, state: SipState) -> None:
        device_id = getattr(self._camera, "device_id", "unknown")
        self._debug(f"sip: {device_id}: {self._state.value} -> {state.value}")
        self._state = state

    def _debug(self, msg: str) -> None:
        if hasattr(self._core, "log") and hasattr(self._core.log, "debug"):
            self._core.log.debug(msg)
        elif hasattr(self._core, "debug"):
            self._core.debug(msg)

    def _vdebug(self, msg: str) -> None:
        if hasattr(self._core, "log") and hasattr(self._core.log, "vdebug"):
            self._core.log.vdebug(msg)
        elif hasattr(self._core, "vdebug"):
            self._core.vdebug(msg)

    async def _fetch_sip_info(self) -> dict[str, Any]:
        params = {
            "cameraId": self._camera.device_id,
            "modelId": (self._camera.model_id or "").upper(),
            "uniqueId": self._camera.unique_id,
        }
        headers = {
            "xcloudId": self._camera.xcloud_id,
            "cameraId": self._camera.device_id,
        }
        be = getattr(self._core, "be", None)
        if be is None:
            raise ArloSipProtocolError("no backend available")

        response = be.get(SIP_INFO_V2_PATH, params=params, headers=headers)
        if asyncio.iscoroutine(response):
            response = await response

        if not isinstance(response, dict) or "sipCallInfo" not in response:
            raise ArloSipProtocolError(
                f"no sipInfo for camera {self._camera.device_id}: got {response!r}"
            )
        return cast(dict[str, Any], response)

    @property
    def ice_servers(self) -> list[dict[str, Any]]:
        """Returns Arlo's published ICE servers, shaped for an RTCConfiguration."""
        if self._sip_info is None:
            return []
        servers: list[dict[str, Any]] = []
        for entry in self._sip_info.get("iceServers", {}).get("data", []):
            servers.append(
                {
                    "urls": [f"{entry['type']}:{entry['domain']}:{entry['port']}"],
                    "username": entry.get("username"),
                    "credential": entry.get("credential"),
                }
            )
        return servers

    async def fetch_info(self) -> dict[str, Any]:
        """Fetches the SIP credentials and ICE servers over REST only."""
        if self._sip_info is not None:
            return self._sip_info

        sip_info = await self._fetch_sip_info()
        call_info = sip_info["sipCallInfo"]
        domain = call_info["domain"]

        self._username = call_info["id"]
        self._password = call_info["password"]
        self._caller_uri = f"sip:{call_info['id']}@{domain}:{self._ws_port}"
        self._callee_uri = call_info["calleeUri"]
        self._sip_info = sip_info
        return sip_info

    async def ensure_connected(self) -> None:
        """Opens the signaling websocket unless it's already open or connecting."""
        if self.state == SipState.IDLE:
            await self.connect()

    async def connect(self) -> None:
        """Fetches SIP credentials if needed, then opens the signaling websocket."""
        if self.state != SipState.IDLE:
            raise ArloSipError(f"cannot connect from state {self.state.value}")
        try:
            self._set_state(SipState.CONNECTING)
            await self.fetch_info()
            if self._sip_info is None:
                raise ArloSipProtocolError("missing sip info")
            domain = self._sip_info["sipCallInfo"]["domain"]

            url = f"wss://{domain}:{self._ws_port}"
            self._debug(f"sip: connecting to {url}")

            if self._session is None:
                self._session = aiohttp.ClientSession()

            self._ws = await self._session.ws_connect(
                url,
                protocols=["sip"],
                origin=ORIGIN_HOST,
                headers={"User-Agent": self._ws_user_agent},
                timeout=aiohttp.ClientWSTimeout(ws_close=float(self._timeout)),
            )
            self._closing = False
            self._reader_task = asyncio.create_task(
                self._reader_loop(),
                name=f"ArloSipReader-{self._camera.device_id}",
            )
        except ArloSipError:
            self._set_state(SipState.FAILED)
            await self.close()
            raise
        except Exception as e:
            self._set_state(SipState.FAILED)
            await self.close()
            raise ArloSipError(f"connect failed: {type(e).__name__}: {e}") from e

    async def _reader_loop(self) -> None:
        if self._ws is None:
            return
        try:
            async for msg in self._ws:
                if self._closing:
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    raw = msg.data
                    if not raw:
                        continue
                    try:
                        message = SipMessage.parse(raw)
                    except ArloSipProtocolError as e:
                        self._debug(f"sip: {self._camera.device_id}: unparsable message: {e}")
                        continue
                    self._dispatch(message)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._debug(f"sip: {self._camera.device_id}: reader stopped: {type(e).__name__}: {e}")
        finally:
            if not self._closing and self.state == SipState.ESTABLISHED:
                self._set_state(SipState.FAILED)

    def _dispatch(self, message: SipMessage) -> None:
        if not message.is_response:
            self._debug(f"sip: {self._camera.device_id}: dropping unexpected request {message.start_line}")
            return
        key = (message.get_header("Call-ID"), message.cseq_number, message.method)
        queue = self._pending.get(key)
        if queue is None:
            self._vdebug(f"sip: {self._camera.device_id}: dropping unmatched response {message.start_line}")
            return
        queue.put_nowait(message)

    async def _send(self, message: SipMessage) -> None:
        if self._ws is None:
            raise ArloSipError("not connected")
        wire_data = message.to_wire()
        if hasattr(self._ws, "send_str"):
            res = self._ws.send_str(wire_data)
            if asyncio.iscoroutine(res):
                await res
        elif hasattr(self._ws, "send"):
            res = self._ws.send(wire_data)
            if asyncio.iscoroutine(res):
                await res

    async def _send_and_wait(self, message: SipMessage, timeout: float | None = None) -> SipMessage:
        timeout = timeout or float(self._timeout)
        key = (message.get_header("Call-ID"), message.cseq_number, message.method)
        queue: asyncio.Queue[SipMessage] = asyncio.Queue()
        self._pending[key] = queue
        try:
            await self._send(message)
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise ArloSipTimeout(f"no response to {message.method} within {timeout}s")
                try:
                    response = await asyncio.wait_for(queue.get(), timeout=remaining)
                except (asyncio.TimeoutError, TimeoutError):
                    raise ArloSipTimeout(f"no response to {message.method} within {timeout}s")
                if response.status_code is not None and response.status_code < 200:
                    continue
                return response
        finally:
            self._pending.pop(key, None)

    async def start(self, offer_sdp: str) -> str:
        """Negotiates the call and returns Arlo's (repaired) answer SDP."""
        if self.state != SipState.CONNECTING:
            raise ArloSipError(f"cannot start from state {self.state.value}; call connect() first")
        try:
            self._set_state(SipState.AUTHENTICATING)

            offer_sdp = filter_offer_candidates(offer_sdp)
            self._call_id = gen_call_id()
            self._tag = gen_tag()

            invite = build_invite(
                self._caller_uri or "",
                self._callee_uri or "",
                self._contact_host,
                self._camera.device_id,
                offer_sdp,
                self._sip_user_agent,
                call_id=self._call_id,
                tag=self._tag,
                contact_user=self._contact_user,
                cseq=self._cseq,
            )
            response = await self._send_and_wait(invite)

            if response.status_code == 407:
                await self._send(
                    build_ack_from_response(
                        response, self._callee_uri or "", self._contact_host, self._sip_user_agent
                    )
                )

                challenge = AuthHeader.parse(response.get_header("Proxy-Authenticate"))
                challenge.compute_response(
                    "INVITE", self._callee_uri or "", self._username or "", self._password or ""
                )

                self._cseq += 1
                invite = build_invite(
                    self._caller_uri or "",
                    self._callee_uri or "",
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
                response = await self._send_and_wait(invite)

            if response.status_code != 200:
                raise ArloSipProtocolError(f"INVITE rejected: {response.start_line}")
            if "application/sdp" not in (response.get_header("Content-Type") or ""):
                raise ArloSipProtocolError("200 OK did not carry an SDP answer")

            self._last_response = response
            await self._send(
                build_ack_from_response(
                    response, self._callee_uri or "", self._contact_host, self._sip_user_agent
                )
            )

            answer_sdp = clean_answer(response.body)

            self._start_keepalive()
            self._set_state(SipState.ESTABLISHED)
            return answer_sdp
        except ArloSipError:
            self._set_state(SipState.FAILED)
            await self.close()
            raise

    def _start_keepalive(self) -> None:
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(),
            name=f"ArloSipKeepalive-{self._camera.device_id}",
        )

    async def _keepalive_loop(self) -> None:
        while not self._closing:
            try:
                await asyncio.sleep(self._keepalive_interval)
                if self.state != SipState.ESTABLISHED:
                    return
                message = build_message(
                    self._caller_uri or "",
                    self._callee_uri or "",
                    self._contact_host,
                    "keepAlive",
                    self._sip_user_agent,
                )
                response = await self._send_and_wait(message)
                if response.status_code != 202:
                    raise ArloSipProtocolError(f"keepAlive rejected: {response.start_line}")
            except asyncio.CancelledError:
                break
            except ArloSipError as e:
                self._debug(f"sip: {self._camera.device_id}: keepalive failed, closing: {e}")
                self._set_state(SipState.FAILED)
                await self.close()
                return

    async def close(self) -> None:
        """Idempotent teardown: BYE if established, close websocket and session."""
        if self._state in (SipState.CLOSED, SipState.CLOSING):
            return
        established = self._state == SipState.ESTABLISHED
        self._set_state(SipState.CLOSING)
        self._closing = True

        if self._keepalive_task is not None and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass

        if established and self._last_response is not None:
            try:
                bye = build_bye_from_response(
                    self._last_response,
                    self._callee_uri or "",
                    self._contact_host,
                    self._sip_user_agent,
                )
                await self._send(bye)
            except ArloSipError as e:
                self._debug(f"sip: {self._camera.device_id}: could not send BYE: {e}")

        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None

        self._set_state(SipState.CLOSED)
