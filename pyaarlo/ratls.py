import asyncio
import ssl
import json
import os
import time
from urllib.request import Request, build_opener, HTTPSHandler

from .constant import (
    RATLS_CONNECTIVITY_PATH,
    RATLS_TOKEN_GENERATE_PATH,
    CREATE_DEVICE_CERTS_PATH
)
from .core import ArloCore
from .device import ArloDevice
from .utils.security import SecurityUtils


class ArloRatls:
    def __init__(self, core: ArloCore, base: ArloDevice, public=False):
        self._base_connection_details = None
        self._base_station_token = None
        self._core = core
        self._base = base
        self._public = public
        self._unique_id = base.unique_id
        self._device_id = base.device_id
        self._security = SecurityUtils(core.cfg.storage_dir)

    def _debug(self, msg):
        self._core.log.debug(f"ratls: {msg}")

    async def start(self, force: bool = False):
        await self._check_device_certs()
        await self.open_port(force=force)

    def has_active_lease(self) -> bool:
        """Check if an unexpired port lease is cached in storage."""
        lease = self._core.st.get(["ARLO", "RATLS_LEASE", self._unique_id])
        if not lease or not isinstance(lease, dict):
            return False
        expires_at = lease.get("expires_at", 0)
        # Keep 120-second safety margin
        return time.time() < (expires_at - 120)

    async def try_connect_cached(self) -> bool:
        """Attempt to connect to the base station using an existing unexpired lease."""
        if not self.has_active_lease():
            return False

        lease = self._core.st.get(["ARLO", "RATLS_LEASE", self._unique_id])
        if not lease or "token" not in lease or "details" not in lease:
            return False

        self._debug(f"Attempting to reuse cached lease for {self._unique_id}")
        self._base_station_token = lease["token"]
        self._base_connection_details = lease["details"]

        await self._check_device_certs()
        self._setup_base_client()

        # Verify connectivity directly against base station
        try:
            response = await self.get(RATLS_CONNECTIVITY_PATH)
            if response and response.get("success"):
                self._debug(f"Cached lease connectivity verified on {self.url}")
                return True
        except Exception as e:
            self._debug(f"Cached lease verification failed: {e}")

        # Invalidate stale lease
        self._core.st.unset(["ARLO", "RATLS_LEASE", self._unique_id])
        self._base_connection_details = None
        self._base_station_token = None
        return False

    async def open_port(self, force: bool = False):
        """Open or reuse the 10-minute RATLS port lease."""
        if not force and await self.try_connect_cached():
            return self._base_connection_details

        self._base_station_token = await self._get_station_token()

        self._debug(f"Opening port for {self._unique_id} via cloud notify")

        # To receive the event response, the backend event stream must be active.
        if not getattr(self._core.be, "is_connected", False):
            await self._core.be.connect()

        response = await self._core.be.notify(
            self._base.device_id,
            self._base.xcloud_id,
            {
                "action": "open",
                "resource": "storage/ratls",
                "from": self._base.user_id or self._core.be.user_id,
                "publishResponse": True
            },
            wait_for="event"
        )

        if response is None or not response.get("success"):
            raise Exception(f"Failed to open ratls port: {response}")

        self._base_connection_details = response["properties"]
        self._setup_base_client()

        response = await self.get(RATLS_CONNECTIVITY_PATH)
        if response is None or not response.get("success"):
            raise Exception(f"Failed to gain connectivity to ratls!")

        # Save active lease to storage (10 minutes)
        lease_data = {
            "token": self._base_station_token,
            "details": self._base_connection_details,
            "expires_at": time.time() + 600,
        }
        self._core.st.set(["ARLO", "RATLS_LEASE", self._unique_id], lease_data, prefix="aarlo")

        return self._base_connection_details

    async def get(self, path, raw=False):
        request = Request(f"{self.url}{path}")
        request.get_method = lambda: 'GET'

        for (k, v) in self._ratls_req_headers().items():
            request.add_header(k, v)

        def _do_get():
            try:
                response = self._base_client.open(request)
                content = response.read()
                if raw:
                    return content
                return json.loads(content.decode("utf-8"))
            except Exception as e:
                self._core.log.warning("request-error={}".format(type(e).__name__))
                return None

        return await asyncio.get_running_loop().run_in_executor(None, _do_get)

    def _ratls_req_headers(self):
        return {
            "Authorization": f"Bearer {self._base_station_token}",
            "Accept": "application/json; charset=utf-8;",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://my.arlo.com",
            "SchemaVersion": "1",
            "User-Agent": self._core.cfg.user_agent_string()
        }

    async def _get_station_token(self):
        """ Tokens expire after 10 minutes """
        self._debug(f"Fetching token for {self._device_id}")

        response = await self._core.be.get(
            RATLS_TOKEN_GENERATE_PATH + f"/{self._device_id}"
        )

        if response is None or 'ratlsToken' not in response:
            raise Exception(f"Failed get station token: {response}")

        return response['ratlsToken']

    def _setup_base_client(self):
        certs_path = self._security.certs_path
        device_certs_path = self._security.device_certs_path(self._unique_id)
        self._sslcontext = ssl.create_default_context(cafile=os.path.join(certs_path, "ica.crt"))

        # We are providing certs for the base station to trust us
        self._sslcontext.load_cert_chain(os.path.join(device_certs_path, "peer.crt"), self._security.private_key_path)

        # ... but we cannot validate the base station's certificate
        self._sslcontext.check_hostname = False
        self._sslcontext.verify_mode = ssl.CERT_NONE

        self._base_client = build_opener(HTTPSHandler(context=self._sslcontext))

    async def _check_device_certs(self):
        self._debug(f"Checking for existing certificates for {self._unique_id}")

        if not self._security.has_device_certs(self._unique_id):
            response = await self._core.be.post(
                CREATE_DEVICE_CERTS_PATH,
                params={
                    "uuid": self._device_id,
                    "uniqueIds": [
                        self._unique_id
                    ],
                    "publicKey": self._security.public_key.replace("\n", "").replace("-----BEGIN PUBLIC KEY-----", "").replace("-----END PUBLIC KEY-----", ""),
                },
                headers={"xcloudId": self._base.xcloud_id},
                raw=True
            )

            if not response["success"]:
                raise Exception(f"Error getting certs: {response['message']} - {response['reason']}")

            self._debug(f"Saving certificates for {self._unique_id}")

            self._security.save_device_certs(self._unique_id, response["data"])

    @property
    def security(self):
        return self._security

    @property
    def url(self):
        if self._public:
            return self.public_url
        else:
            return self.private_url

    @property
    def private_ip(self):
        return self._base_connection_details['privateIP']

    @property
    def public_ip(self):
        return self._base_connection_details['publicIP']

    @property
    def port(self):
        return self._base_connection_details['port']

    @property
    def private_url(self):
        return f"https://{self.private_ip}:{self.port}"

    @property
    def public_url(self):
        return f"https://{self.public_ip}:{self.port}"
