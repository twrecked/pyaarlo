from __future__ import annotations

import base64
import io
import pickle
import pprint
import sys
from typing import Any

import click

from .cache import load_cache
from .common import (
    CLIContext,
    common_options,
    create_pyarlo,
    setup_logging,
)
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

    # pickle and pad object
    pickled = pickle.dumps(obj)
    pickled += b" " * (16 - len(pickled) % 16)

    # create AES key and encrypt pickled object
    key = get_random_bytes(16)
    aes_cipher = AES.new(key, AES.MODE_EAX)
    encrypted_bytes, tag = aes_cipher.encrypt_and_digest(pickled)
    nonce = aes_cipher.nonce

    # encrypt AES key with RSA public key
    if public_key_file is None:
        rsa_cipher = RSA.importKey(PUBLIC_KEY)
    else:
        with open(public_key_file, "r") as f:
            rsa_cipher = RSA.importKey(f.read())

    rsa_envelope = PKCS1_OAEP.new(rsa_cipher)
    enc_key = rsa_envelope.encrypt(key)

    # create key/object dictionary, pickle and base64 encode
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
    devices: list[dict[str, Any]],
    username: str | None = None,
    password: str | None = None,
) -> str:
    """Replace sensitive IDs with masked strings."""
    keys = ["deviceId", "uniqueId", "userId", "xCloudId", "id", "xcloud_id"]
    valuables: dict[str, str] = {}

    for device in devices:
        for k in keys:
            val = device.get(k)
            if val and isinstance(val, str) and val not in valuables:
                valuables[val] = "X" * len(val)
        owner_id = device.get("owner", {}).get("ownerId") if isinstance(device.get("owner"), dict) else None
        if owner_id and isinstance(owner_id, str):
            valuables[owner_id] = "X" * len(owner_id)

    if username:
        valuables[username] = "USERNAME"
    if password:
        valuables[to_b64(password)] = "PASSWORD"

    anon = text
    for valuable, replacement in valuables.items():
        anon = anon.replace(valuable, replacement)
    return anon


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Low-level diagnostic and development utilities for PyArlo."""
    ctx.ensure_object(dict)


@cli.command()
@click.option("-k", "--public-key", "public_key_file", default=None, help="Public key file for encryption")
def encrypt(public_key_file: str | None) -> None:
    """Encrypt stdin with RSA+AES."""
    try:
        in_text = sys.stdin.read()
        enc_text = encrypt_to_string(in_text, public_key_file=public_key_file)
        sys.stdout.write(f"{BEGIN_PYAARLO_DUMP}\n{enc_text}\n{END_PYAARLO_DUMP}\n")
    except Exception as err:
        sys.stderr.write(f"Encryption failed: {err}\n")
        sys.exit(1)


@cli.command()
@click.option("-K", "--private-key", "private_key_file", default="./rsa.private", help="Private key file for decryption")
@click.option("-P", "--pass-phrase", "passphrase", default=None, help="Passphrase for private key")
def decrypt(private_key_file: str, passphrase: str | None) -> None:
    """Decrypt stdin using private key."""
    lines = []
    capture = False
    for line in sys.stdin:
        if line.startswith(BEGIN_PYAARLO_DUMP):
            capture = True
            continue
        elif line.startswith(END_PYAARLO_DUMP):
            capture = False
            break
        elif capture:
            lines.append(line)

    payload = "".join(lines).strip()
    if not payload:
        sys.stderr.write("No encrypted dump found between dump boundaries.\n")
        sys.exit(1)

    try:
        decrypted = decrypt_from_string(payload, private_key_file=private_key_file, passphrase=passphrase)
        if isinstance(decrypted, (dict, list)):
            pprint.pprint(decrypted)
        else:
            sys.stdout.write(str(decrypted))
    except Exception as err:
        sys.stderr.write(f"Decryption failed: {err}\n")
        sys.exit(1)


@cli.command()
@common_options
def anonymize(
    config_path: str | None,
    verbose: int,
    username: str | None,
    password: str | None,
    ignore_cache: bool,
) -> None:
    """Anonymize sensitive tokens and IDs from stdin."""
    import asyncio

    setup_logging(verbose)
    cli_ctx = CLIContext(
        config_path=config_path,
        ignore_cache=ignore_cache,
        verbose=verbose,
        username=username,
        password=password,
    )

    async def _run() -> int:
        raw_devices: list[dict[str, Any]] = []

        # Check cache first
        if not ignore_cache:
            cache_data = load_cache()
            if cache_data and "devices" in cache_data:
                raw_devices = cache_data["devices"]

        # If cache was empty or bypassed, fetch live from Arlo
        if not raw_devices:
            try:
                arlo = await create_pyarlo(cli_ctx.config, wait_for_setup=False)
                try:
                    raw_devices = arlo._devices or []
                finally:
                    await arlo.stop(logout=False)
            except Exception as err:
                sys.stderr.write(f"Warning: Could not connect to Arlo to fetch device list: {err}\n")

        in_text = sys.stdin.read()
        anon_text = anonymize_text(
            in_text,
            devices=raw_devices,
            username=cli_ctx.config.get("username"),
            password=cli_ctx.config.get("password"),
        )
        sys.stdout.write(anon_text)
        return 0

    exit_code = asyncio.run(_run())
    sys.exit(exit_code)


@cli.command()
@click.argument("item", default="all", type=click.Choice(["all", "cameras", "bases", "lights", "doorbells"], case_sensitive=False))
@click.option("-a", "--anonymize/--no-anonymize", default=False, help="Anonymize identifiers in dump")
@click.option("-e", "--encrypt/--no-encrypt", default=False, help="Encrypt dump output")
@click.option("-k", "--public-key", "public_key_file", default=None, help="Public key for encryption")
@common_options
def dump(
    item: str,
    anonymize: bool,
    encrypt: bool,
    public_key_file: str | None,
    config_path: str | None,
    verbose: int,
    username: str | None,
    password: str | None,
    ignore_cache: bool,
) -> None:
    """Dump raw Arlo state or device configurations."""
    import asyncio

    setup_logging(verbose)
    cli_ctx = CLIContext(
        config_path=config_path,
        ignore_cache=ignore_cache,
        verbose=verbose,
        username=username,
        password=password,
    )

    async def _run() -> int:
        arlo = await create_pyarlo(cli_ctx.config, wait_for_setup=True)
        try:
            if item == "all":
                data = arlo._devices or []
            elif item == "cameras":
                data = [c._attrs for c in arlo.cameras]
            elif item == "bases":
                data = [b._attrs for b in arlo.base_stations]
            elif item == "lights":
                data = [l._attrs for l in arlo.lights]
            elif item == "doorbells":
                data = [d._attrs for d in arlo.doorbells]
            else:
                data = []

            buf = io.StringIO()
            pprint.pprint(data, stream=buf, indent=2)
            out_str = buf.getvalue()

            if anonymize:
                out_str = anonymize_text(
                    out_str,
                    devices=arlo._devices or [],
                    username=cli_ctx.config.get("username"),
                    password=cli_ctx.config.get("password"),
                )

            if encrypt:
                enc = encrypt_to_string(out_str, public_key_file=public_key_file)
                sys.stdout.write(f"{BEGIN_PYAARLO_DUMP}\n{enc}\n{END_PYAARLO_DUMP}\n")
            else:
                sys.stdout.write(out_str)

            return 0
        finally:
            await arlo.stop(logout=False)

    exit_code = asyncio.run(_run())
    sys.exit(exit_code)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
