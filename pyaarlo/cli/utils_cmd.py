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
    run_async_cli,
    setup_logging,
)
from ..utils import to_b64

from .diagnostics import (
    BEGIN_PYAARLO_DUMP,
    END_PYAARLO_DUMP,
    PUBLIC_KEY,
    anonymize_text,
    decrypt_from_string,
    encrypt_to_string,
)


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
    backend: str | None,
    inline: bool | None,
    ignore_cache: bool,
    debug_report: str | None,
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
        backend=backend,
        inline=inline,
        debug_report=debug_report,
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

    run_async_cli(cli_ctx, _run())


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
    backend: str | None,
    inline: bool | None,
    ignore_cache: bool,
    debug_report: str | None,
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
        backend=backend,
        inline=inline,
        debug_report=debug_report,
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

    run_async_cli(cli_ctx, _run())


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
