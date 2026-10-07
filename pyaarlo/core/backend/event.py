from __future__ import annotations

import asyncio
import json 

import paho.mqtt.client as mqtt
import pprint
import random
import requests
import ssl
import traceback
from enum import IntEnum
from typing import Any, Callable, TypeAlias

from ...constant import (
    MQTT_HOST,
    ORIGIN_HOST,
    MQTT_PATH,
    SUBSCRIBE_PATH,
)
from ...utils.sseclient import SSEClient, AsyncSSEClient
from ..cfg import ArloCfg
from ..logger import ArloLogger
from .session import ArloSessionDetails

EventHandler: TypeAlias = Callable[[dict[str, Any]], Any]
ConnectHandler: TypeAlias = Callable[[], dict[str, Any]]
ReconnectHandler: TypeAlias = Callable[[], Any]


class _EventState(IntEnum):
    STARTING = 0
    RUNNING = 1
    READY = 2


class _EventSession:

    def __init__(self, cfg: ArloCfg, log: ArloLogger, details: ArloSessionDetails,
                 event_handler: EventHandler,
                 connect_handler: ConnectHandler,
                 reconnect_handler: ReconnectHandler) -> None:
        self.cfg: ArloCfg = cfg
        self.log: ArloLogger = log

        self.details: ArloSessionDetails = details
        self.event_handler: EventHandler = event_handler
        self.connect_handler: ConnectHandler = connect_handler
        self.reconnect_handler: ReconnectHandler = reconnect_handler

        # Capture the loop we are running in
        self.loop: asyncio.AbstractEventLoop | None = None
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    def _is_running_in_loop(self) -> bool:
        try:
            return self.loop is not None and asyncio.get_running_loop() is self.loop
        except RuntimeError:
            return False

    def dispatch_event(self, response: dict[str, Any]) -> None:
        """Dispatch event back to the async loop."""
        if self._is_running_in_loop():
            if asyncio.iscoroutinefunction(self.event_handler):
                asyncio.create_task(self.event_handler(response))
            else:
                self.event_handler(response)
        elif self.loop:
            _ = asyncio.run_coroutine_threadsafe(self._async_event_handler(response), self.loop)
        else:
            self.event_handler(response)

    async def _async_event_handler(self, response: dict[str, Any]) -> None:
        if asyncio.iscoroutinefunction(self.event_handler):
            await self.event_handler(response)
        else:
            self.event_handler(response)

    def dispatch_connect(self) -> dict[str, Any]:
        """Dispatch connect signal and wait for result (needed by MQTT)."""
        if self._is_running_in_loop():
            if asyncio.iscoroutinefunction(self.connect_handler):
                asyncio.create_task(self.connect_handler())
                return {"devices": []}
            else:
                res = self.connect_handler()
                return res if isinstance(res, dict) else {"devices": []}
        elif self.loop:
            future = asyncio.run_coroutine_threadsafe(self._async_connect_handler(), self.loop)
            try:
                return future.result(timeout=30)
            except Exception as e:
                self.log.error(f"event: connect handler failed: {str(e)}")
                return {"devices": []}
        else:
            return self.connect_handler()

    async def _async_connect_handler(self) -> dict[str, Any]:
        if asyncio.iscoroutinefunction(self.connect_handler):
            return await self.connect_handler()
        else:
            return self.connect_handler()

    def dispatch_reconnect(self) -> None:
        """Dispatch reconnect signal."""
        if self._is_running_in_loop():
            if asyncio.iscoroutinefunction(self.reconnect_handler):
                asyncio.create_task(self.reconnect_handler())
            else:
                self.reconnect_handler()
        elif self.loop:
            _ = asyncio.run_coroutine_threadsafe(self._async_reconnect_handler(), self.loop)
        else:
            self.reconnect_handler()

    async def _async_reconnect_handler(self) -> None:
        if asyncio.iscoroutinefunction(self.reconnect_handler):
            await self.reconnect_handler()
        else:
            self.reconnect_handler()


class _MQTT:

    def __init__(self, session: _EventSession) -> None:
        self._session: _EventSession = session
        self._client: mqtt.Client | None = None
        self._client_id: str | None = None
        self._stop_event: asyncio.Event | None = None

    def _debug(self, msg: str) -> None:
        self._session.log.debug(f"{msg}")

    def _vdebug(self, msg: str) -> None:
        self._session.log.vdebug(f"{msg}")

    def _subscribe_devices(self, devices: list[dict[str, Any]]) -> None:
        topics: list[tuple[str, int]] = []
        for device in devices:
            for topic in device.get("allowedMqttTopics", []):
                topics.append((topic, 0))

        self._debug("topics=\n{}".format(pprint.pformat(topics)))
        if self._client:
            _ = self._client.subscribe(topics)

    def _subscribe_basic(self) -> None:
        # Make sure we are listening to library events and individual base
        # station events. This seems sufficient for now.
        if self._client:
            _ = self._client.subscribe([
                (f"u/{self._session.details.user_id}/in/userSession/connect", 0),
                (f"u/{self._session.details.user_id}/in/userSession/disconnect", 0),
                (f"u/{self._session.details.user_id}/in/library/add", 0),
                (f"u/{self._session.details.user_id}/in/library/update", 0),
                (f"u/{self._session.details.user_id}/in/library/remove", 0)
            ])

    def _on_connect(self, _client: mqtt.Client, _userdata: Any, _flags: dict[str, Any], rc: int) -> None:
        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        self._debug(f"connected={str(rc)}")
        connect_result = self._session.dispatch_connect()
        self._subscribe_basic()
        if "devices" in connect_result:
            self._subscribe_devices(connect_result["devices"])

    def _on_log(self, _client: mqtt.Client, _userdata: Any, _level: int, msg: str) -> None:
        self._vdebug(f"log={str(msg)}")

    def _on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        self._debug(f"topic={msg.topic}")
        try:
            response = json.loads(msg.payload.decode("utf-8"))

            # deal with mqtt specific pieces
            if response.get("action", "") == "logout":
                self._session.log.warning("logged out? did you log in from elsewhere?")
                return

            # pass on to general handler
            self._session.dispatch_event(response)

        except json.decoder.JSONDecodeError as e:
            self._debug("reopening: json error " + str(e))

    async def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._client:
            _ = self._client.disconnect()

    async def run(self) -> None:

        try:
            self._debug("(re)starting mqtt event loop")
            headers = {
                "Host": MQTT_HOST,
                "Origin": ORIGIN_HOST,
            }

            # Build a new _client_id per login. The last 10 numbers seem to need to be random.
            self._client_id = f"user_{self._session.details.user_id}_" + "".join(
                str(random.randint(0, 9)) for _ in range(10)
            )
            self._debug(f"_client_id={self._client_id}")

            # Create and set up the MQTT client.
            self._client = mqtt.Client(
                client_id=self._client_id, transport=self._session.cfg.mqtt_transport
            )
            self._client.on_log = self._on_log
            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = self._session.cfg.mqtt_hostname_check
            self._client.tls_set_context(ssl_context)
            self._client.username_pw_set(f"{self._session.details.user_id}", self._session.details.token)
            self._client.ws_set_options(path=MQTT_PATH, headers=headers)
            self._debug(
                f"host={self._session.cfg.mqtt_host}, "
                f"check={self._session.cfg.mqtt_hostname_check}, "
                f"transport={self._session.cfg.mqtt_transport}"
            )

            # Connect.
            _ = self._client.connect(self._session.cfg.mqtt_host, port=self._session.cfg.mqtt_port, keepalive=60)
            
            # Start loop in a background thread as paho-mqtt is sync
            self._client.loop_start()
            
            self._stop_event = asyncio.Event()
            await self._stop_event.wait()
            
            self._client.loop_stop()

        except Exception as e:
            # self._log.warning('general exception ' + str(e))
            self._session.log.error(
                "mqtt-error={}\n{}".format(
                    type(e).__name__, traceback.format_exc()
                )
            )

    async def update(self, **_kwargs: Any) -> None:
        pass


class _SSE:

    def __init__(self, session: _EventSession) -> None:
        self._session: _EventSession = session
        self._stream: AsyncSSEClient | None = None

    def _debug(self, msg: str) -> None:
        self._session.log.debug(f"sse: {msg}")

    async def stop(self) -> None:
        self._debug("stopping")
        if self._stream:
            await self._stream.stop()

    async def run(self) -> None:
        """Open and connect an SSE stream.

        It will wait for certain signals before moving into a connected
        state.
        """

        # get stream, restart after requested seconds of inactivity or forced close
        try:
            # Fudge timeout for requests library.
            timeout: int | None = self._session.cfg.stream_timeout
            self._debug(f"starting stream with {timeout} timeout")
            if timeout == 0:
                timeout = None
            self._stream = AsyncSSEClient(
                self._session.log,
                self._session.cfg.host + SUBSCRIBE_PATH,
                session=self._session.details.async_connection or self._session.details.connection,
                headers=self._session.details.headers,
                reconnect_cb=self._session.reconnect_handler,
                timeout=timeout,
            )

            async for event in self._stream:

                # stopped?
                if event is None:
                    self._debug("exiting: no event")
                    break

                # dig out response
                try:
                    response = json.loads(event.data)
                except json.decoder.JSONDecodeError as e:
                    self._debug("exiting: json error " + str(e))
                    break

                # deal with SSE specific pieces
                # logged out? signal exited
                if response.get("action", "") == "logout":
                    self._session.log.warning("logged out? did you log in from elsewhere?")
                    break

                # connected - yay!
                if response.get("status", "") == "connected":
                    _ = self._session.dispatch_connect()
                    continue

                # pass on to general handler
                self._debug("passing on packet")
                self._session.dispatch_event(response)

        except Exception as e:
            # self._session.log.warning('general exception ' + str(e))
            self._session.log.error(
                "sse-error={}\n{}".format(
                    type(e).__name__, traceback.format_exc()
                )
            )

    def update(self, **_kwargs: Any) -> None:
        pass


class ArloEvent:
    """Wrapper around the event stream providers.

    Currently this can be either SSE or MQTT. Which to use is chosen by the
    user or (preferred) chosen by the Arlo servers.
    """

    def __init__(self, cfg: ArloCfg, log: ArloLogger, details: ArloSessionDetails,
                 event_handler: EventHandler,
                 connect_handler: ConnectHandler,
                 reconnect_handler: ReconnectHandler) -> None:
        self._session: _EventSession = _EventSession(cfg, log, details, event_handler, connect_handler, reconnect_handler)
        self._state: _EventState = _EventState.STARTING
        self._device: _MQTT | _SSE | None = None

    def _debug(self, msg: str) -> None:
        self._session.log.debug(f"event: {msg}")

    def setup(self) -> None:
        """Move the instance into ready state.

        Pick the back end to use.
        """
        if self._state != _EventState.STARTING:
            self._session.log.warning(f"event is not starting in {self._state}")
            return

        # Pick stream type to use.
        if self._session.cfg.event_backend == 'mqtt':
            self._device = _MQTT(self._session)
        else:
            self._device = _SSE(self._session)

        # Ready to run.
        self._state = _EventState.READY

    async def run(self) -> None:
        """Call the back end run function.
        """
        if self._state == _EventState.STARTING:
            self.setup()
        elif self._state != _EventState.READY:
            self._session.log.warning(f"event is not ready in {self._state}")
            return

        if self._device:
            self._state = _EventState.RUNNING
            try:
                await self._device.run()
            finally:
                self._state = _EventState.STARTING

    async def stop(self) -> None:
        """Ask the event stream to stop.
        """
        if self._state != _EventState.RUNNING:
            self._session.log.warning(f"event is not running in {self._state}")
            return

        self._state = _EventState.STARTING
        if self._device:
            await self._device.stop()

    async def update(self, **kwargs: Any) -> None:
        """Update the event stream.
        """
        if self._state != _EventState.RUNNING:
            self._session.log.warning(f"event is not running in {self._state}")
            return

        if self._device:
            self._device.update(**kwargs)

