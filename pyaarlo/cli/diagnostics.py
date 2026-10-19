from __future__ import annotations

import base64
import datetime
import io
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
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1oYXnbQPxREiVPUIRkgk
h+ehjxHnwz34NsjhjgN1oSKmHpf4cL4L/V4tMnj5NELEmLyTrzAZbeewUMwyiwXO
3l+cSjjoDKcPBSj4uxjWsq74Q5TLHGjOtkFwaqqxtvsVn3fGFWBO405xpvp7jPUc
BOvBQaUBUaR9Tbw5anMOzeavUwUTRp2rjtbWyj2P7PEp49Ixzw0w+RjIVrzzevAo
AD7SVb6U8P77fht4k9krbIFckC/ByY48HhmF+edh1GZAgLCHuf43tGg2upuH5wf+
AGv/Xlc+9ScTjEp37uPiCpHcB1ur83AFTjcceDIm+VDKF4zQrj88zmL7JqZy+Upx
UQIDAQAB
-----END PUBLIC KEY-----"""


def encrypt_to_string(obj: Any, public_key_file: str | None = None) -> str:
    """Encrypt object using RSA + AES."""
    from Crypto.Cipher import AES, PKCS1_OAEP
    from Crypto.PublicKey import RSA
    from Crypto.Random import get_random_bytes

    pickled = pickle.dumps(obj)
    pickled += b" " * (16 - len(pickled) % 16)

    key = get_random_bytes(16)
    aes_cipher = AES.new(key, AES.MODE_EAX)
    encrypted_bytes, tag = aes_cipher.encrypt_and_digest(pickled)
    nonce = aes_cipher.nonce

    if public_key_file is None:
        rsa_cipher = RSA.importKey(PUBLIC_KEY)
    else:
        with open(public_key_file, "r") as f:
            rsa_cipher = RSA.importKey(f.read())

    rsa_envelope = PKCS1_OAEP.new(rsa_cipher)
    enc_key = rsa_envelope.encrypt(key)

    envelope = pickle.dumps({"k": enc_key, "n": nonce, "o": encrypted_bytes, "t": tag})
    return base64.encodebytes(envelope).decode().rstrip()


def decrypt_from_string(
    key_obj_str: str,
    private_key_file: str = "./rsa.private",
    passphrase: str | None = None,
) -> Any:
    """Decrypt object using RSA + AES."""
    from Crypto.Cipher import AES, PKCS1_OAEP
    from Crypto.PublicKey import RSA

    envelope = base64.b64decode(key_obj_str)
    data = pickle.loads(envelope)

    with open(private_key_file, "r") as f:
        rsa_cipher = RSA.importKey(f.read(), passphrase=passphrase)

    rsa_envelope = PKCS1_OAEP.new(rsa_cipher)
    aes_key = rsa_envelope.decrypt(data["k"])

    aes_cipher = AES.new(aes_key, AES.MODE_EAX, nonce=data["n"])
    decrypted_bytes = aes_cipher.decrypt_and_verify(data["o"], data["t"])
    return pickle.loads(decrypted_bytes)


def anonymize_text(
    text: str,
    devices: list[dict[str, Any]] | None = None,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """Replace sensitive IDs, usernames, and passwords with masked strings."""
    keys = ["deviceId", "uniqueId", "userId", "xCloudId", "id", "xcloud_id", "serial_number", "serialNumber"]
    valuables: dict[str, str] = {}

    if devices:
        for device in devices:
            for k in keys:
                val = device.get(k)
                if val and isinstance(val, str) and len(val) >= 4 and val not in valuables:
                    valuables[val] = "X" * len(val)
            owner_id = device.get("owner", {}).get("ownerId") if isinstance(device.get("owner"), dict) else None
            if owner_id and isinstance(owner_id, str):
                valuables[owner_id] = "X" * len(owner_id)

    if username:
        valuables[username] = "USERNAME"
    if password:
        valuables[to_b64(password)] = "PASSWORD"
        valuables[password] = "PASSWORD"

    anon = text
    for valuable, replacement in valuables.items():
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
