from __future__ import annotations

import json

import paho.mqtt.client as mqtt
import pprint
import random
import requests
import ssl
import traceback
from enum import IntEnum
from typing import Any

from ...constant import (
    MQTT_HOST,
    ORIGIN_HOST,
    MQTT_PATH,
    SUBSCRIBE_PATH,
)
from ...utils.sseclient import SSEClient
from ..cfg import ArloCfg
from ..logger import ArloLogger
from ..background import ArloBackground
from .session import ArloSessionDetails


class _EventState(IntEnum):
    STARTING = 0,
    RUNNING = 1,
    READY = 2,


class _EventSession:

    cfg: ArloCfg
    log: ArloLogger
    details: ArloSessionDetails
    eventhandler: Any
    connecthandler: Any
    reconnecthandler: Any

    def __init__(self, cfg: ArloCfg, log: ArloLogger, details: ArloSessionDetails,
                 event_handler: Any = None, connect_handler: Any = None, reconnect_handler: Any = None) -> None:
        self.cfg = cfg
        self.log = log
        self.details = details
        self.event_handler = event_handler
        self.connect_handler = connect_handler
        self.reconnect_handler = reconnect_handler


class _MQTT:

    _session: _EventSession

    _client: mqtt.Client | None
    _client_id: str | None

    def __init__(self, session: _EventSession):
        self._session = session

    def _debug(self, msg):
        self._session.log.debug(f"{msg}")

    def _vdebug(self, msg):
        self._session.log.vdebug(f"{msg}")

    def _subscribe_devices(self, devices):
        topics = []
        for device in devices:
            for topic in device.get("allowedMqttTopics", []):
                topics.append((topic, 0))

        self._debug("topics=\n{}".format(pprint.pformat(topics)))
        self._client.subscribe(topics)

    def _subscribe_basic(self):
        # Make sure we are listening to library events and individual base
        # station events. This seems sufficient for now.
        self._client.subscribe([
            (f"u/{self._session.details.user_id}/in/userSession/connect", 0),
            (f"u/{self._session.details.user_id}/in/userSession/disconnect", 0),
            (f"u/{self._session.details.user_id}/in/library/add", 0),
            (f"u/{self._session.details.user_id}/in/library/update", 0),
            (f"u/{self._session.details.user_id}/in/library/remove", 0)
        ])

    def _on_connect(self, _client, _userdata, _flags, rc):
        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        self._debug(f"connected={str(rc)}")
        connect_result = self._session.connect_handler()
        self._subscribe_basic()
        if "devices" in connect_result:
            self._subscribe_devices(connect_result["devices"])

    def _on_log(self, _client, _userdata, _level, msg):
        self._vdebug(f"log={str(msg)}")

    def _on_message(self, _client, _userdata, msg):
        self._debug(f"topic={msg.topic}")
        try:
            response = json.loads(msg.payload.decode("utf-8"))

            # deal with mqtt specific pieces
            if response.get("action", "") == "logout":
                # Logged out? MQTT will log back in until stopped.
                self._session.log.warning("logged out? did you log in from elsewhere?")
                return

            # pass on to general handler
            self._session.event_handler(response)

        except json.decoder.JSONDecodeError as e:
            self._debug("reopening: json error " + str(e))

    def stop(self):
        self._client.disconnect()

    def run(self):

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
            self._debug(f"host={self._session.cfg.mqtt_host}, "
                        f"check={self._session.cfg.mqtt_hostname_check}, "
                        f"transport={self._session.cfg.mqtt_transport}")

            # Connect.
            self._client.connect(self._session.cfg.mqtt_host, port=self._session.cfg.mqtt_port, keepalive=60)
            self._client.loop_forever()

        except Exception as e:
            # self._log.warning('general exception ' + str(e))
            self._session.log.error(
                "mqtt-error={}\n{}".format(
                    type(e).__name__, traceback.format_exc()
                )
            )

    def update(self, **_kwargs):
        pass


class _SSE:

    _session: _EventSession

    _stream: SSEClient

    def __init__(self, session: _EventSession):
        self._session = session

    def _debug(self, msg):
        self._session.log.debug(f"sse: {msg}")

    def stop(self):
        self._debug("stopping")
        self._stream.stop()

    def run(self):
        """Open and connect an SSE stream.

        It will wait for certain signals before moving into a connected
        state.
        """

        # get stream, restart after requested seconds of inactivity or forced close
        try:
            # Fudge timeout for requests library.
            timeout = self._session.cfg.stream_timeout
            self._debug(f"starting stream with {timeout} timeout")
            if timeout is 0:
                timeout = None
            self._stream = SSEClient(
                self._session.log,
                self._session.cfg.host + SUBSCRIBE_PATH,
                headers=self._session.details.headers,
                reconnect_cb=self._session.reconnect_handler,
                timeout=timeout,
            )

            for event in self._stream:

                # stopped?
                if event is None:
                    self._debug("reopening: no event")
                    break

                # dig out response
                try:
                    response = json.loads(event.data)
                except json.decoder.JSONDecodeError as e:
                    self._debug("reopening: json error " + str(e))
                    break

                # deal with SSE specific pieces
                # logged out? signal exited
                if response.get("action", "") == "logout":
                    self._session.log.warning("logged out? did you log in from elsewhere?")
                    break

                # connected - yay!
                if response.get("status", "") == "connected":
                    self._session.connect_handler()
                    continue

                # pass on to general handler
                self._debug("passing on packet")
                self._session.event_handler(response)

        except requests.exceptions.ConnectionError:
            self._session.log.warning("event loop timeout")
        except requests.exceptions.HTTPError:
            self._session.log.warning("event loop closed by server")
        except AttributeError as e:
            self._session.log.warning("forced close " + str(e))
        except Exception as e:
            # self._session.log.warning('general exception ' + str(e))
            self._session.log.error(
                "sse-error={}\n{}".format(
                    type(e).__name__, traceback.format_exc()
                )
            )

    def update(self, **kwargs):
        pass


class ArloEvent:
    """Wrapper around the event stream providers.

    Currently this can be either SSE or MQTT. Which to use is chosen by the
    user or (preferred) chosen by the Arlo servers.

    This class does no threading. It's just a fancy wrapper that forwards to
    a class doing the real work.
    """

    _session: _EventSession
    _bg: ArloBackground

    _state: _EventState = _EventState.STARTING
    _session: _EventSession | None = None
    _device: _MQTT | _SSE | None = None

    def __init__(self, cfg: ArloCfg, log: ArloLogger, bg: ArloBackground, details: ArloSessionDetails,
                 event_handler: Any = None, connect_handler: Any = None, reconnect_handler: Any = None):
        self._session = _EventSession(cfg, log, details, event_handler, connect_handler, reconnect_handler)
        self._bg = bg

    def _debug(self, msg):
        self._session.log.debug(f"event: {msg}")

    def setup(self):
        """Move instance into ready state.

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

    def run(self):
        """Call the back end run function.

        This function will run until the connection closes. This can be for
        several reasons:
         - we closed it
         - arlo closed it
         - network connectivity issues
        """
        if self._state != _EventState.READY:
            self._session.log.warning(f"event is not ready in {self._state}")
            return

        self._state = _EventState.RUNNING
        self._device.run()

    def stop(self):
        """Ask the event stream to stop.
        """
        if self._state != _EventState.RUNNING:
            self._session.log.warning(f"event is not running in {self._state}")
            return

        self._state = _EventState.STARTING
        self._device.stop()

    def update(self, **kwargs):
        """Update the event stream.

        This is stream specific; for MQTT it will update subscriptions, for
        SSE it will do nothing.
        """
        if self._state != _EventState.RUNNING:
            self._session.log.warning(f"event is not running in {self._state}")
            return

        self._device.update(**kwargs)
        pass
