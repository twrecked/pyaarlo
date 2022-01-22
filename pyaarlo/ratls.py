import ssl
import json
import os
from urllib.request import Request, build_opener, HTTPSHandler
import requests
from .security_utils import SecurityUtils

from .constant import (
    RATLS_CONNECTIVITY_PATH,
    RATLS_TOKEN_GENERATE_PATH,
    CREATE_DEVICE_CERTS_PATH
)

class ArloRatls(object):
    def __init__(self, arlo, base, public=False):
        self._arlo = arlo
        self._base = base
        self._public = public
        self._unique_id = base.unique_id
        self._device_id = base.device_id
        self._security = SecurityUtils(arlo.cfg.storage_dir)

        self._check_device_certs()
        self.open_port()

    def open_port(self):
        """ RATLS port will automatically close after 10 minutes """
        self._base_station_token = self._get_station_token()

        self._arlo.debug(f"Opening port for {self._unique_id}")

        response = self._arlo.be.notify(
            self._base,
            {
                "action": "open",
                "resource": "storage/ratls",
                "from": self._base.user_id,
                "publishResponse": True
            },
            wait_for="event"
        )

        if response is None or not response['success']:
            raise Exception(f"Failed to open ratls port: {response}")

        self._base_connection_details = response['properties']
        self._setup_base_client()

        response = self.get(RATLS_CONNECTIVITY_PATH)
        if response is None or not response['success']:
            raise Exception(f"Failed to gain connectivity to ratls!")

        return self._base_connection_details

    def get(self, path, raw=False):
        request = Request(f"{self.url}{path}")
        request.get_method = lambda: 'GET'

        for (k, v) in self._ratls_req_headers().items():
            request.add_header(k, v)

        try:
            response = self._base_client.open(request)
            if raw:
                return response
            return json.loads(response.read())
        except Exception as e:
            self._arlo.warning("request-error={}".format(type(e).__name__))
            return None

    def _ratls_req_headers(self):
      return {
          "Authorization": f"Bearer {self._base_station_token}",
          "Accept": "application/json; charset=utf-8;",
          "Accept-Language": "en-US,en;q=0.9",
          "Origin": "https://my.arlo.com",
          "SchemaVersion": "1",
          "User-Agent": self._arlo.be.user_agent(self._arlo.cfg.user_agent)
      }

    def _get_station_token(self):
        """ Tokens expire after 10 minutes """
        self._arlo.debug(f"Fetching token for {self._device_id}")

        response = self._arlo.be.get(
            RATLS_TOKEN_GENERATE_PATH + f"/{self._device_id}"
        )

        if response is None or not 'ratlsToken' in response:
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

    def _check_device_certs(self):
        self._arlo.debug(f"Checking for existing certificates for {self._unique_id}")

        if not self._security.has_device_certs(self._unique_id):
            response = self._arlo.be.post(
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

            self._arlo.debug(f"Saving certificates for {self._unique_id}")

            self._security.save_device_certs(self._unique_id, response["data"])

    @property
    def security(self):
        return self._security

    @property
    def url(self):
        if self._public:
            return self.publicUrl
        else:
            return self.privateUrl

    @property
    def privateIp(self):
        return self._base_connection_details['privateIP']

    @property
    def publicIp(self):
        return self._base_connection_details['publicIP']

    @property
    def port(self):
        return self._base_connection_details['port']

    @property
    def privateUrl(self):
        return f"https://{self.privateIp}:{self.port}"

    @property
    def publicUrl(self):
        return f"https://{self.publicIp}:{self.port}"
