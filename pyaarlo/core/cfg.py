import platform
import tempfile
import os
import re
import random

from typing import Any, cast, Literal
from urllib.parse import urlparse, ParseResult

from ..constant import (
    DEFAULT_AUTH_HOST,
    DEFAULT_HOST,
    DEFAULT_MQTT_PORT,
    ECDH_CURVES,
    MQTT_HOST,
    PRELOAD_DAYS,
    TFA_CONSOLE_SOURCE,
    TFA_DEFAULT_HOST,
    TFA_DELAY,
    TFA_EMAIL_TYPE,
    TFA_RETRIES,
    USER_AGENTS,
)
from .logger import ArloLogger


class ArloCfg:
    """Helper class to get at Arlo configuration options.

    I got sick of adding in variables each time the config changed so I moved it all here. Config
    is passed in a kwarg and parsed out by the property methods.
    """


    def __init__(self, log: ArloLogger, **kwargs: Any):
        """The constructor.

        Args:
            kwargs (kwargs): Configuration options.
        """
        self._log: ArloLogger = log

        self._kw: dict[str, Any] = kwargs
        self._update_backend: bool = False
        self._storage_dir: str

        # Determine storage location, this is platform specific.
        strplatform = platform.system()
        termux_dir = "/data/data/com.termux/files/home"
        if strplatform == "Windows":
            self._storage_dir = os.path.join(tempfile.gettempdir(), ".aarlo")
        elif os.path.exists(termux_dir):
            self._storage_dir = cast(str, self._kw.get("storage_dir", os.path.join(termux_dir, ".aarlo")))
        else:
            self._storage_dir = cast(str, self._kw.get("storage_dir", "/tmp/.aarlo"))

        self._debug("loaded")


    def _remove_scheme(self, host: str) -> str:
        bits = host.split("://")
        if len(bits) > 1:
            return bits[1]
        return host

    def _add_scheme(self, host: str, scheme: str = 'https') -> str:
        if "://" in host:
            return host
        return f"{scheme}://{host}"

    def _email_to_dir(self, email: str) -> str:
        return re.sub(r'[^0-9a-zA-Z]+', '_', email)

    def _user_storage_file(self, suffix: str) -> str:
        return f"{self.storage_dir}/{self._email_to_dir(self.username)}.{suffix}"

    def _debug(self, msg: str):
        self._log.debug(f"cfg: {msg}")

    @property
    def storage_dir(self) -> str:
        return self._storage_dir

    @property
    def name(self) -> str:
        return cast(str, self._kw.get("name", "aarlo"))

    @property
    def username(self) -> str:
        return cast(str, self._kw.get("username", "unknown"))

    @property
    def password(self) -> str:
        return cast(str, self._kw.get("password", "unknown"))

    @property
    def host(self) -> str:
        return self._add_scheme(cast(str, self._kw.get("host", DEFAULT_HOST)), "https")

    @property
    def auth_host(self) -> str:
        return self._add_scheme(cast(str, self._kw.get("auth_host", DEFAULT_AUTH_HOST)), "https")

    @property
    def mqtt_host(self) -> str:
        return self._remove_scheme(cast(str, self._kw.get("mqtt_host", MQTT_HOST)))

    @property
    def mqtt_port(self) -> int:
        return cast(int, self._kw.get("mqtt_port", DEFAULT_MQTT_PORT))

    def update_mqtt_from_url(self, url: str | ParseResult):
        if self._update_backend or self.event_backend == "auto":
            self._update_backend = True
            url = urlparse(cast(str, url))
            if url.scheme == "wss":
                self._kw["backend"] = 'sse'
            else:
                self._kw["backend"] = 'mqtt'
                self._kw["mqtt_host"] = cast(str, url.hostname)
                self._kw["mqtt_port"] = cast(int, url.port)

    @property
    def mqtt_hostname_check(self) -> bool:
        return bool(self._kw.get("mqtt_hostname_check", True))

    @property
    def mqtt_transport(self) -> Literal["tcp", "websockets"]:
        return cast(Literal["tcp", "websockets"], self._kw.get("mqtt_transport", "tcp"))

    @property
    def dump(self) -> bool:
        return cast(bool, self._kw.get("dump", False))

    @property
    def max_days(self) -> int:
        return cast(int, self._kw.get("max_days", 365))

    @property
    def db_motion_time(self) -> int:
        return cast(int, self._kw.get("db_motion_time", 30))

    @property
    def db_ding_time(self) -> int:
        return cast(int, self._kw.get("db_ding_time", 10))

    @property
    def request_timeout(self) -> int:
        return cast(int, self._kw.get("request_timeout", 60))

    @property
    def stream_timeout(self) -> int:
        return cast(int, self._kw.get("stream_timeout", 0))

    @property
    def recent_time(self) -> int:
        return cast(int, self._kw.get("recent_time", 600))

    @property
    def last_format(self) -> str:
        return cast(str, self._kw.get("last_format", "%m-%d %H:%M"))

    @property
    def no_media_upload(self) -> bool:
        return cast(bool, self._kw.get("no_media_upload", False))

    @property
    def media_retry(self) -> list[int]:
        retries = cast(list[int], self._kw.get("media_retry", []))
        if not retries and self.no_media_upload:
            retries = [0, 5, 10]
        return retries

    @property
    def snapshot_checks(self) -> list[int]:
        return cast(list[int], self._kw.get("snapshot_checks", []))

    @property
    def user_agent(self) -> str:
        return cast(str, self._kw.get("user_agent", "arlo"))

    def user_agent_string(self, agent: str | None = None) -> str:
        """Map `agent` to a user agent string.

        `!real-string` will use the provided string as-is, used when passing user agent
        from a browser.

        `random` will provide a different user agent for each log in attempt.

        Passing in no agent will return the configured one.
        """
        if agent is None:
            agent = self.user_agent
        if agent.startswith("!"):
            self._debug(f"using user supplied user_agent {agent[:70]}")
            return agent[1:]
        agent = agent.lower()
        self._debug(f"looking for user_agent {agent}")
        if agent == "random":
            return self.user_agent_string(random.choice(list(USER_AGENTS.keys())))
        return USER_AGENTS.get(agent, USER_AGENTS["linux"])

    @property
    def http_backend(self) -> str:
        return cast(str, self._kw.get("http_backend", "curl_cffi"))

    @property
    def curl_cffi_impersonate(self) -> str:
        return cast(str, self._kw.get("curl_cffi_impersonate", "chrome131"))

    @property
    def mode_api(self) -> str:
        return cast(str, self._kw.get("mode_api", "auto"))

    @property
    def refresh_devices_every(self) -> int:
        return cast(int, self._kw.get("refresh_devices_every", 0)) * 60 * 60

    @property
    def refresh_modes_every(self) -> int:
        return cast(int, self._kw.get("refresh_modes_every", 0)) * 60

    @property
    def reconnect_every(self) -> int:
        return cast(int, self._kw.get("reconnect_every", 0)) * 60

    @property
    def snapshot_timeout(self) -> int:
        return cast(int, self._kw.get("snapshot_timeout", 60))

    @property
    def verbose(self) -> bool:
        return cast(bool, self._kw.get("verbose_debug", False))

    @property
    def tfa_source(self) -> str:
        return cast(str, self._kw.get("tfa_source", TFA_CONSOLE_SOURCE))

    @property
    def tfa_type(self) -> str:
        return cast(str, self._kw.get("tfa_type", TFA_EMAIL_TYPE)).lower()

    @property
    def tfa_delay(self) -> int:
        return cast(int, self._kw.get("tfa_delay", TFA_DELAY))

    @property
    def tfa_retries(self) -> int:
        return cast(int, self._kw.get("tfa_retries", TFA_RETRIES))

    @property
    def tfa_timeout(self) -> int:
        return cast(int, self._kw.get("tfa_timeout", 3))

    @property
    def tfa_total_timeout(self) -> int:
        return cast(int, self._kw.get("tfa_total_timeout", 60))

    @property
    def tfa_host(self) -> str:
        host: str = self._remove_scheme(cast(str, self._kw.get("tfa_host", TFA_DEFAULT_HOST)))
        return host.split(":")[0]

    def tfa_host_with_scheme(self, scheme: str = "https") -> str:
        host: str = self._add_scheme(cast(str, self._kw.get("tfa_host", TFA_DEFAULT_HOST)), scheme)
        return ":".join(host.split(":")[:2])

    @property
    def tfa_port(self) -> int:
        host = self._remove_scheme(cast(str, self._kw.get("tfa_host", TFA_DEFAULT_HOST)))
        bits = host.split(":")
        if len(bits) == 1:
            return 993
        return int(bits[1])

    @property
    def tfa_username(self) -> str:
        u = self._kw.get("tfa_username", None)
        if u is None:
            u = self.username
        return cast(str, u)

    @property
    def tfa_password(self) -> str:
        p = self._kw.get("tfa_password", None)
        if p is None:
            p = self.password
        return cast(str, p)

    @property
    def tfa_nickname(self) -> str:
        return cast(str, self._kw.get("tfa_nickname", self.tfa_username))

    @property
    def wait_for_initial_setup(self) -> bool:
        return cast(bool, self._kw.get("wait_for_initial_setup", True))

    @property
    def save_state(self) -> bool:
        return cast(bool, self._kw.get("save_state", True))

    @property
    def state_file(self) -> str | None:
        if self.save_state:
            return self.storage_dir + "/" + self.name + ".pickle"
        return None

    @property
    def session_file(self) -> str:
        return self._user_storage_file('session')

    @property
    def save_session(self) -> bool:
        return cast(bool, self._kw.get("save_session", True))

    @property
    def cookies_file(self) -> str:
        return self._user_storage_file('cookies')

    @property
    def dump_file(self) -> str | None:
        if self.dump:
            return self.storage_dir + "/" + "packets.dump"
        return None

    @property
    def library_days(self) -> int:
        return cast(int, self._kw.get("library_days", PRELOAD_DAYS))

    @property
    def synchronous_mode(self) -> bool:
        return cast(bool, self._kw.get("synchronous_mode", False))

    @property
    def user_stream_delay(self) -> int:
        return cast(int, self._kw.get("user_stream_delay", 1))

    @property
    def serial_ids(self) -> bool:
        return cast(bool, self._kw.get("serial_ids", False))

    @property
    def stream_snapshot(self) -> bool:
        return cast(bool, self._kw.get("stream_snapshot", False))

    @property
    def stream_snapshot_stop(self) -> int:
        return cast(int, self._kw.get("stream_snapshot_stop", 10))

    @property
    def save_media_to(self) -> str:
        return cast(str, self._kw.get("save_media_to", ""))

    @property
    def no_unicode_squash(self) -> bool:
        return cast(bool, self._kw.get("no_unicode_squash", True))

    @property
    def event_backend(self) -> str:
        return cast(str, self._kw.get("backend", "auto"))

    @property
    def cipher_list(self) -> str:
        if self._kw.get("default_ciphers", False):
            return 'DEFAULT'
        return cast(str, self._kw.get("cipher_list", ""))

    @property
    def ecdh_curves(self) -> list[str]:
        curve = self._kw.get("ecdh_curve", None)
        curves = list(ECDH_CURVES)
        if curve in curves:
            # Moves user-selected curve to front of list
            curves.insert(0, curves.pop(curves.index(cast(str, curve))))
        return curves

    @property
    def send_source(self) -> bool:
        return cast(bool, self._kw.get("send_source", False))

