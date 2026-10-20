from __future__ import annotations

import base64
import datetime
import io
import json
import logging
import os
import pickle
import platform
import sys
import traceback
from pathlib import Path
from typing import Any

from .. import __version__
from ..utils import to_b64

BEGIN_PYAARLO_DUMP = "-----BEGIN PYAARLO DUMP-----"
END_PYAARLO_DUMP = "-----END PYAARLO DUMP-----"

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxzl3k6V+70R3znooqXtr
pN54HrzirF0ogaioOUvL8tK0uE/FLDoeYBJdAGhe9iHYx6wMFUGX9Lp3yduWFr+y
e9azVZTCApLs+DXsofnWN7KoFhb852BeXEHx7qsOqyz7DtahXpJ9HdjW7R50rO48
ZMbKlVjTiQU98ZsbW2E9EKj2Fn3RONjZkO5AaIC2P+9/4dMPn1hKrADH/pNlDQIa
2BKh4BzbDV4wE6o+ZyLozuMEH2Wo/AjTN7mr3xoX+u8/AiGMKel/NdFdp+XayJEZ
x9Q+WOLpRng74qG1lhGFf2l8RQqxVykX0JXxkNiuTckXpfP4ITkYZgaJ5NLZuEns
LwIDAQAB
-----END PUBLIC KEY-----"""


def encrypt_to_string(obj: Any, public_key_file: str | None = None) -> str:
    """Encrypt object using RSA + AES."""
    from Crypto.Cipher import AES, PKCS1_OAEP
    from Crypto.PublicKey import RSA
    from Crypto.Random import get_random_bytes

    if isinstance(obj, str):
        obj_bytes = obj.encode("utf-8")
    elif isinstance(obj, bytes):
        obj_bytes = obj
    else:
        try:
            obj_bytes = json.dumps(obj).encode("utf-8")
        except (TypeError, ValueError):
            obj_bytes = str(obj).encode("utf-8")

    key = get_random_bytes(16)
    aes_cipher = AES.new(key, AES.MODE_EAX)
    encrypted_bytes, tag = aes_cipher.encrypt_and_digest(obj_bytes)
    nonce = aes_cipher.nonce

    if public_key_file is None:
        rsa_cipher = RSA.importKey(PUBLIC_KEY)
    else:
        with open(public_key_file, "r") as f:
            rsa_cipher = RSA.importKey(f.read())

    rsa_envelope = PKCS1_OAEP.new(rsa_cipher)
    enc_key = rsa_envelope.encrypt(key)

    envelope = {
        "v": 2,
        "k": base64.b64encode(enc_key).decode("ascii"),
        "n": base64.b64encode(nonce).decode("ascii"),
        "o": base64.b64encode(encrypted_bytes).decode("ascii"),
        "t": base64.b64encode(tag).decode("ascii"),
    }
    envelope_json = json.dumps(envelope).encode("utf-8")
    return base64.encodebytes(envelope_json).decode("ascii").rstrip()


def decrypt_from_string(
    key_obj_str: str,
    private_key_file: str = "./rsa.private",
    passphrase: str | None = None,
) -> Any:
    """Decrypt object using RSA + AES."""
    from Crypto.Cipher import AES, PKCS1_OAEP
    from Crypto.PublicKey import RSA

    envelope_bytes = base64.b64decode(key_obj_str)

    is_legacy = False
    try:
        data = json.loads(envelope_bytes.decode("utf-8"))
        enc_key = base64.b64decode(data["k"])
        nonce = base64.b64decode(data["n"])
        ciphertext = base64.b64decode(data["o"])
        tag = base64.b64decode(data["t"])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        is_legacy = True
        data = pickle.loads(envelope_bytes)
        enc_key = data["k"]
        nonce = data["n"]
        ciphertext = data["o"]
        tag = data["t"]

    with open(private_key_file, "r") as f:
        rsa_cipher = RSA.importKey(f.read(), passphrase=passphrase)

    rsa_envelope = PKCS1_OAEP.new(rsa_cipher)
    aes_key = rsa_envelope.decrypt(enc_key)

    aes_cipher = AES.new(aes_key, AES.MODE_EAX, nonce=nonce)
    decrypted_bytes = aes_cipher.decrypt_and_verify(ciphertext, tag)

    if is_legacy:
        return pickle.loads(decrypted_bytes)

    dec_text = decrypted_bytes.decode("utf-8")
    try:
        return json.loads(dec_text)
    except (json.JSONDecodeError, ValueError):
        return dec_text


def anonymize_text(
    text: str,
    devices: list[dict[str, Any]] | None = None,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """Replace sensitive IDs, usernames, and passwords with consistent, readable pseudonyms."""
    valuables: dict[str, str] = {}

    type_prefixes = {
        "base_station": "BASE",
        "basestation": "BASE",
        "camera": "CAM",
        "cameras": "CAM",
        "light": "LIGHT",
        "lights": "LIGHT",
        "doorbell": "DOORBELL",
        "doorbells": "DOORBELL",
        "sensor": "SENSOR",
        "sensors": "SENSOR",
        "siren": "SIREN",
        "chime": "CHIME",
    }

    type_counts: dict[str, int] = {}
    user_counts: dict[str, str] = {}
    owner_counts: dict[str, str] = {}
    xcloud_counts: dict[str, str] = {}
    user_idx = 1
    owner_idx = 1
    xcloud_idx = 1

    if devices:
        for device in devices:
            raw_type = str(device.get("type") or device.get("deviceType") or "dev").lower()
            prefix = type_prefixes.get(raw_type, "DEV")

            count = type_counts.setdefault(prefix, 1)
            type_counts[prefix] += 1
            tag = f"{prefix}_{count:02d}"

            # 1. Device ID
            dev_id = device.get("deviceId") or device.get("id")
            if dev_id and isinstance(dev_id, str) and len(dev_id) >= 4:
                valuables.setdefault(dev_id, f"{tag}_ID")

            # 2. Unique ID
            unique_id = device.get("uniqueId")
            if unique_id and isinstance(unique_id, str) and len(unique_id) >= 4:
                valuables.setdefault(unique_id, f"{tag}_UID")

            # 3. Serial Number
            serial = device.get("serial_number") or device.get("serialNumber")
            if serial and isinstance(serial, str) and len(serial) >= 4:
                valuables.setdefault(serial, f"{tag}_SN")

            # 4. xCloud ID
            xcloud = device.get("xCloudId") or device.get("xcloud_id")
            if xcloud and isinstance(xcloud, str) and len(xcloud) >= 4:
                if xcloud not in xcloud_counts:
                    xcloud_counts[xcloud] = f"XCLOUD_{xcloud_idx:02d}_ID"
                    xcloud_idx += 1
                valuables.setdefault(xcloud, xcloud_counts[xcloud])

            # 5. User ID
            uid = device.get("userId")
            if uid and isinstance(uid, str) and len(uid) >= 4:
                if uid not in user_counts:
                    user_counts[uid] = f"USER_{user_idx:02d}_ID"
                    user_idx += 1
                valuables.setdefault(uid, user_counts[uid])

            # 6. Owner ID
            owner_dict = device.get("owner")
            owner_id = owner_dict.get("ownerId") if isinstance(owner_dict, dict) else None
            if owner_id and isinstance(owner_id, str) and len(owner_id) >= 4:
                if owner_id not in owner_counts:
                    owner_counts[owner_id] = f"OWNER_{owner_idx:02d}_ID"
                    owner_idx += 1
                valuables.setdefault(owner_id, owner_counts[owner_id])

    # Username and password
    if username:
        valuables[username] = "USERNAME"
    if password:
        valuables[to_b64(password)] = "PASSWORD"
        valuables[password] = "PASSWORD"

    # Replace in order of decreasing length to prevent partial substring matches
    anon = text
    for valuable in sorted(valuables.keys(), key=len, reverse=True):
        replacement = valuables[valuable]
        anon = anon.replace(valuable, replacement)

    return anon


class DebugReportCapture:
    """In-memory capture of full debug logs, system metadata, and exceptions for issue reports."""

    def __init__(self, filename: str = "pyaarlo-debug-report.enc") -> None:
        self.filename = filename
        self.log_stream = io.StringIO()
        self.handler: logging.Handler | None = None
        self.start_time = datetime.datetime.now()
        self._started = False
        self._finished = False
        self._captured_exception: BaseException | None = None
        self._devices: list[dict[str, Any]] | None = None
        self._username: str | None = None
        self._password: str | None = None

    def start(
        self,
        username: str | None = None,
        password: str | None = None,
        devices: list[dict[str, Any]] | None = None,
    ) -> None:
        """Attach in-memory handler to capture all debug logs."""
        if self._started:
            return
        self._started = True
        self._username = username
        self._password = password
        self._devices = devices

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        self.handler = logging.StreamHandler(self.log_stream)
        self.handler.setLevel(logging.DEBUG)
        self.handler.setFormatter(formatter)

        pyaarlo_logger = logging.getLogger("pyaarlo")
        pyaarlo_logger.setLevel(logging.DEBUG)
        pyaarlo_logger.addHandler(self.handler)

        root_logger = logging.getLogger()
        root_logger.addHandler(self.handler)

        def _hook(t: Any, v: BaseException, tb: Any) -> None:
            self._captured_exception = v
            sys.__excepthook__(t, v, tb)

        sys.excepthook = _hook

        import atexit
        atexit.register(self.finish)

    def finish(
        self,
        output_filename: str | None = None,
        devices: list[dict[str, Any]] | None = None,
        username: str | None = None,
        password: str | None = None,
        exception: BaseException | None = None,
    ) -> Path | None:
        """Compile, anonymize, and encrypt diagnostic report to disk."""
        if self._finished:
            return None
        self._finished = True

        target_file = Path(output_filename or self.filename)
        actual_exception = exception or self._captured_exception
        actual_username = username or self._username
        actual_password = password or self._password
        actual_devices = devices or self._devices

        if self.handler is not None:
            logging.getLogger("pyaarlo").removeHandler(self.handler)
            logging.getLogger().removeHandler(self.handler)
            self.handler.close()
            self.handler = None

        report_lines = [
            "=" * 70,
            "PYAARLO DIAGNOSTIC DEBUG REPORT",
            "=" * 70,
            f"PyArlo Version:    {__version__}",
            f"Python Version:    {sys.version.split()[0]} ({platform.python_implementation()})",
            f"Platform:          {platform.platform()}",
            f"Timestamp:         {datetime.datetime.now().isoformat()}",
            f"Command Line:      {' '.join(sys.argv)}",
            "-" * 70,
        ]

        if actual_exception is not None:
            report_lines.extend([
                "EXCEPTION DETECTED:",
                "".join(traceback.format_exception(type(actual_exception), actual_exception, actual_exception.__traceback__)).strip(),
                "-" * 70,
            ])

        report_lines.extend([
            "CAPTURED LOG STREAM:",
            self.log_stream.getvalue(),
            "=" * 70,
        ])

        raw_report = "\n".join(report_lines)

        # 1. Anonymize personal identifiers
        anonymized_report = anonymize_text(
            raw_report,
            devices=actual_devices,
            username=actual_username,
            password=actual_password,
        )

        # 2. Encrypt using public key
        encrypted_text = encrypt_to_string(anonymized_report)
        full_dump = f"{BEGIN_PYAARLO_DUMP}\n{encrypted_text}\n{END_PYAARLO_DUMP}\n"

        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(full_dump, encoding="utf-8")

        sys.stderr.write("\n" + "=" * 70 + "\n")
        sys.stderr.write(f"PyArlo Debug Report Generated: {target_file.resolve()}\n\n")
        sys.stderr.write("This file contains an anonymized, encrypted diagnostic log.\n")
        sys.stderr.write("You can safely attach this file to a GitHub issue:\n")
        sys.stderr.write("  https://github.com/twrecked/pyaarlo/issues\n")
        sys.stderr.write("=" * 70 + "\n\n")

        return target_file
