"""Helpers for recording to the Arlo cloud from the CLI."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click

from ..camera import ArloCamera
from .config import read_config_file


def recording_timezone(timezone: str | None, hass_dir: str | None) -> str | None:
    """Validate the fallback zone or read it from Home Assistant's core settings."""
    if timezone is None and hass_dir:
        base = Path(hass_dir).resolve()
        if base.is_file():
            base = base.parent.parent if base.parent.name == ".storage" else base.parent
        data = read_config_file(base / ".storage" / "core.config").get("data")
        value = data.get("time_zone") if isinstance(data, dict) else None
        timezone = value if isinstance(value, str) else None
    if timezone is not None:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise click.BadParameter("expected an IANA zone such as America/New_York", param_hint="--timezone") from None
    return timezone


async def open_consumer(ffmpeg: str, source: str) -> asyncio.subprocess.Process:
    """Consume the stream without creating a temporary recording."""
    try:
        url = urlsplit(source)
        if not url.hostname or url.scheme not in {"rtsp", "rtsps", "http", "https"}:
            raise ValueError
    except ValueError:
        raise click.ClickException("Arlo returned an unsupported recording stream URL") from None

    options = ["-protocol_whitelist", "http,https,tcp,tls"]
    if url.scheme in {"rtsp", "rtsps"}:
        options = ["-protocol_whitelist", "rtsp,rtsps,rtp,tcp,tls", "-rtsp_transport", "tcp"]
    try:
        return await asyncio.create_subprocess_exec(
            ffmpeg, "-nostdin", "-loglevel", "error", *options, "-i", source,
            "-map", "0:v:0", "-c:v", "copy", "-f", "null", "-",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            # Diagnostics from FFmpeg can include the signed stream URL.
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        raise click.ClickException("Could not launch FFmpeg") from None


async def record_camera(camera: ArloCamera, ffmpeg: str, duration: int, timezone: str | None) -> None:
    """Keep a consumer connected while Arlo records, and clean up on every exit."""
    if not camera.timezone and timezone is None:
        raise click.ClickException("No camera time zone is available; pass --timezone with an IANA zone")
    source = await camera.start_recording_stream(user_agent="arlo")
    if not source:
        raise click.ClickException("Arlo did not return a recording stream")

    try:
        process = await open_consumer(ffmpeg, source)
        exited = asyncio.create_task(process.wait())
        try:
            ready = asyncio.create_task(camera.wait_for_user_stream())
            try:
                await asyncio.wait((ready, exited), timeout=20, return_when=asyncio.FIRST_COMPLETED)
                if exited.done():
                    raise click.ClickException(f"FFmpeg exited before stream readiness (status {exited.result()})")
                if not ready.done() or not ready.result():
                    raise click.ClickException("Arlo recording stream did not become active")
            finally:
                ready.cancel()
                await asyncio.gather(ready, return_exceptions=True)

            if not await camera.start_recording(fallback_timezone=timezone):
                raise click.ClickException("Arlo did not accept the start recording request")
            click.echo(f"[{camera.name}] Arlo accepted start; recording for {duration}s...")
            try:
                done, _ = await asyncio.wait((exited,), timeout=duration)
            finally:
                if not await camera.stop_recording(release_stream=False):
                    raise click.ClickException("Arlo did not accept the stop recording request")
                click.echo(f"[{camera.name}] Arlo accepted stop. Check `pyaarlo media list` for the clip.")
            if done:
                raise click.ClickException(f"FFmpeg exited before the requested duration (status {exited.result()})")
        finally:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            await exited
    finally:
        await camera.stop_recording_stream()
