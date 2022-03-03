from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

import os
import textwrap

from .constant import CERT_BEGIN, CERT_END

class SecurityUtils(object):
  def __init__(self, storage_dir: str) -> None:
    self.__storage_dir = storage_dir
    self.__private_key: str = None
    self.__public_key: str = None
    if not self.__load_keys():
      self.__generate_keypair()

  @property
  def public_key(self) -> str:
    if self.__public_key is None:
      self.__generate_keypair()
    return self.__public_key

  @property
  def private_key(self) -> str:
    if self.__private_key is None:
      self.__generate_keypair()
    return self.__private_key

  @property
  def public_key_path(self) -> str:
    return os.path.join(self.__storage_dir, "certs", "public.pem")

  @property
  def private_key_path(self) -> str:
    return os.path.join(self.__storage_dir, "certs", "private.pem")

  def __load_keys(self) -> bool:
    if os.path.exists(self.private_key_path) and os.path.exists(self.public_key_path):
      self.__private_key = open(self.private_key_path).read()
      self.__public_key = open(self.public_key_path).read()
      return True
    return False


  def __generate_keypair(self):
    # generate private/public key pair
    key = rsa.generate_private_key(backend=default_backend(), public_exponent=65537, \
        key_size=2048)

    # get private key in PEM container format
    pem = key.private_bytes(encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption())

    pub_pem = key.public_key().public_bytes(encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo)

    # decode to printable strings
    self.__private_key = pem.decode('utf-8')
    self.__public_key = pub_pem.decode('utf-8')

    os.makedirs(os.path.join(self.__storage_dir, "certs"), exist_ok=True)

    with open(self.public_key_path, "w") as public_key_file:
      public_key_file.write(self.__public_key)
    with open(self.private_key_path, "w") as private_key_file:
      private_key_file.write(self.__private_key)

  @property
  def certs_path(self) -> str:
    return os.path.join(self.__storage_dir, "certs")

  def device_certs_path(self, base_station_id: str) -> str:
    return os.path.join(self.__storage_dir, "certs", base_station_id)

  def has_device_certs(self, base_station_id: str) -> bool:
    return os.path.exists(os.path.join(self.device_certs_path(base_station_id), "peer.crt"))

  def save_device_certs(self, base_station_id: str, certs):
    device_cert = certs['certsData'][0]["deviceCert"]
    peer_cert = certs["certsData"][0]["peerCert"]
    ica_cert = certs["icaCert"]

    device_cert = textwrap.fill(device_cert, width=64) + '\n'
    peer_cert = textwrap.fill(peer_cert, width=64) + '\n'
    ica_cert = textwrap.fill(ica_cert, width=64) + '\n'

    os.makedirs(os.path.join(self.device_certs_path(base_station_id)), exist_ok=True)

    with open(os.path.join(self.device_certs_path(base_station_id), "device.crt"), 'w') as device_file:
      device_file.writelines([CERT_BEGIN, device_cert, CERT_END])

    with open(os.path.join(self.device_certs_path(base_station_id), "peer.crt"), 'w') as peer_file:
      peer_file.writelines([CERT_BEGIN, peer_cert, CERT_END])

    with open(os.path.join(self.__storage_dir, "certs", "ica.crt"), 'w') as ica_file:
      ica_file.writelines([CERT_BEGIN, ica_cert, CERT_END])

    with open(os.path.join(self.device_certs_path(base_station_id), "combined.crt"), 'w') as combined_file:
      combined_file.writelines([CERT_BEGIN, peer_cert, CERT_END, CERT_BEGIN, ica_cert, CERT_END])
