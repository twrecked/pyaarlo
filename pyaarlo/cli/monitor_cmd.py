from __future__ import annotations

import asyncio
import datetime
import json
import signal
import sys
from typing import Any

import click

from .common import (
    CLIContext,
    common_options,
    create_pyarlo,
    setup_logging,
)
from .targets import parse_targets, match_device


@click.command()
@click.option("--filter-device", default=None, help="Comma-separated device names or IDs to monitor")
@click.option("--filter-event", default=None, help="Comma-separated event/attribute names to monitor")
@click.option("--exclude-event", default=None, help="Comma-separated event/attribute names to ignore")
@click.option("--compact", is_flag=True, default=False, help="Print events in single-line compact format")
@click.option("-l", "--length", "--max-length", "max_length", type=int, default=None, help="Maximum value length (defaults to 80 in --compact mode, 0 for unlimited)")
@click.option("--sse", is_flag=True, default=False, help="Shortcut for --backend sse")
@click.option("--json", "json_output", is_flag=True, default=False, help="Print events as JSON lines")
@click.option("--raw", is_flag=True, default=False, help="Print raw backend event stream packets")
@common_options
def cli(
    filter_device: str | None,
    filter_event: str | None,
    exclude_event: str | None,
    compact: bool,
    max_length: int | None,
    sse: bool,
    json_output: bool,
    raw: bool,
    config_path: str | None,
    verbose: int,
    username: str | None,
    password: str | None,
    backend: str | None,
    ignore_cache: bool,
) -> None:
    """Connect to Arlo and stream live device events."""
    setup_logging(verbose)
    if sse:
        backend = "sse"
    cli_ctx = CLIContext(
        config_path=config_path,
        ignore_cache=ignore_cache,
        verbose=verbose,
        username=username,
        password=password,
        backend=backend,
    )

    device_filters = parse_targets([filter_device]) if filter_device else []
    event_filters = [e.strip().lower() for e in filter_event.split(",") if e.strip()] if filter_event else []
    event_excludes = [e.strip().lower() for e in exclude_event.split(",") if e.strip()] if exclude_event else []

    async def _monitor() -> int:
        sys.stderr.write("Connecting to Arlo event stream...\n")
        arlo = await create_pyarlo(cli_ctx.config, wait_for_setup=True)

        stop_event = asyncio.Event()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except (NotImplementedError, RuntimeError):
                # Signal handlers may not be supported on all platforms/threads (e.g. Windows)
                pass

        def _truncate_val(val: Any) -> Any:
            limit: int | None = None
            if max_length is not None:
                limit = None if max_length <= 0 else max_length
            elif compact:
                limit = 80

            if isinstance(val, (bytes, bytearray)):
                if limit is not None and len(val) > limit:
                    return f"<bytes len={len(val)}>"
                val_str = repr(val)
            else:
                val_str = str(val)

            if limit is not None and len(val_str) > limit:
                return val_str[:limit] + "..."
            return val_str

        def _format_event(dev_name: str, dev_id: str, attr: str, value: Any) -> None:
            now_iso = datetime.datetime.now().isoformat(timespec="seconds")
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            formatted_val = _truncate_val(value)

            if json_output:
                payload = {
                    "timestamp": now_iso,
                    "device": dev_name,
                    "device_id": dev_id,
                    "attribute": attr,
                    "value": formatted_val if max_length is not None else value,
                }
                sys.stdout.write(json.dumps(payload) + "\n")
            elif compact:
                sys.stdout.write(f"{now_str} {dev_name} {attr}={formatted_val}\n")
            else:
                sys.stdout.write(f"[{now_str}] [{dev_name}] {attr}: {formatted_val}\n")
            sys.stdout.flush()

        def _on_attr_change(device: Any, attr: str, value: Any) -> None:
            attr_lower = attr.lower()

            # Filter checks
            if event_filters and attr_lower not in event_filters:
                return
            if event_excludes and attr_lower in event_excludes:
                return

            dev_name = getattr(device, "name", "unknown")
            dev_id = getattr(device, "device_id", "unknown")

            if device_filters:
                matched = any(match_device(device, df) for df in device_filters)
                if not matched:
                    return

            _format_event(dev_name, dev_id, attr, value)

        def _on_raw_event(resource: str, event: dict[str, Any]) -> None:
            if not raw:
                return
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if json_output:
                sys.stdout.write(json.dumps({"timestamp": now_str, "resource": resource, "event": event}) + "\n")
            else:
                sys.stdout.write(f"[{now_str}] RAW {resource}: {event}\n")
            sys.stdout.flush()

        # Collect all monitorable devices
        all_devices: list[Any] = []
        all_devices.extend(arlo.base_stations)
        all_devices.extend(arlo.cameras)
        all_devices.extend(arlo.lights)
        all_devices.extend(arlo.doorbells)
        all_devices.extend(arlo.sensors)
        all_devices.extend(arlo.locations)

        for dev in all_devices:
            if hasattr(dev, "add_attr_callback"):
                dev.add_attr_callback("*", _on_attr_change)

        if raw and hasattr(arlo._core.be, "add_any_listener"):
            arlo._core.be.add_any_listener(_on_raw_event)

        sys.stderr.write(f"Connected. Monitoring {len(all_devices)} devices. Press Ctrl+C to exit.\n")

        try:
            await stop_event.wait()
        except KeyboardInterrupt:
            pass
        finally:
            sys.stderr.write("\nDisconnecting from Arlo...\n")
            await arlo.stop(logout=False)

        return 0

    try:
        exit_code = asyncio.run(_monitor())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as err:
        sys.stderr.write(f"Error: {err}\n")
        sys.exit(1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
