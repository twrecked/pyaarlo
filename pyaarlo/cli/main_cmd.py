from __future__ import annotations

import asyncio
import datetime
import os
import sys
import time
from pathlib import Path
from typing import Any

import click

from .cache import clear_cache, fill_cache, load_cache, is_cache_stale
from .common import (
    CLIContext,
    clear_user_session,
    common_options,
    create_pyarlo,
    get_auth_status,
    print_auth_status,
    run_async_cli,
    setup_logging,
)
from .config import (
    get_default_cache_path,
    get_default_config_path,
    load_config,
    parse_tfa_spec,
    read_config_file,
    save_config_file,
)
from .targets import parse_targets, resolve_devices, resolve_location


@click.group()
@common_options
@click.pass_context
def cli(
    ctx: click.Context,
    config_path: str | None,
    verbose: int,
    username: str | None,
    password: str | None,
    backend: str | None,
    inline: bool | None,
    ignore_cache: bool,
    debug_report: str | None,
) -> None:
    """PyArlo command-line interface for device actions and automation."""
    setup_logging(verbose)
    ctx.obj = CLIContext(
        config_path=config_path,
        ignore_cache=ignore_cache,
        verbose=verbose,
        username=username,
        password=password,
        backend=backend,
        inline=inline,
        debug_report=debug_report,
    )


# -------------------------------------------------------------------------
# Login
# -------------------------------------------------------------------------
@cli.command()
@click.option("--status", is_flag=True, default=False, help="Display token timeouts and authentication status")
@click.option("--tfa", default=None, help="2FA delivery and entry spec (e.g. email:imap, email:console, push, sms)")
@click.option("--tfa-type", default=None, help="2FA delivery mechanism (email, sms, push)")
@click.option("--tfa-source", default=None, help="2FA entry mechanism (console, imap, push, rest-api)")
@click.option("--push", is_flag=True, default=False, help="Shortcut for --tfa push")
@click.option("--force", is_flag=True, default=False, help="Force full re-authentication even if session token is still valid")
@click.option("--tfa-host", default=None, help="IMAP server host for 2FA")
@click.option("--tfa-user", default=None, help="IMAP username for 2FA")
@click.option("--tfa-pass", default=None, help="IMAP password for 2FA")
@click.pass_obj
def login(
    cli_ctx: CLIContext,
    status: bool,
    tfa: str | None,
    tfa_type: str | None,
    tfa_source: str | None,
    push: bool,
    force: bool,
    tfa_host: str | None,
    tfa_user: str | None,
    tfa_pass: str | None,
) -> None:
    """Log in to Arlo, verify credentials, refresh cache, or check token status."""
    if status:
        auth_status = get_auth_status(cli_ctx.config)
        code = print_auth_status(auth_status)
        cli_ctx.finish_debug_report()
        sys.exit(code)

    if push:
        cli_ctx.cli_overrides["tfa_type"] = "push"
        cli_ctx.cli_overrides["tfa_source"] = "push"
    elif tfa:
        t_type, t_source = parse_tfa_spec(tfa)
        cli_ctx.cli_overrides["tfa_type"] = t_type
        cli_ctx.cli_overrides["tfa_source"] = t_source

    if tfa_type is not None:
        cli_ctx.cli_overrides["tfa_type"] = tfa_type
    if tfa_source is not None:
        cli_ctx.cli_overrides["tfa_source"] = tfa_source
    if tfa_host is not None:
        cli_ctx.cli_overrides["tfa_host"] = tfa_host
    if tfa_user is not None:
        cli_ctx.cli_overrides["tfa_username"] = tfa_user
    if tfa_pass is not None:
        cli_ctx.cli_overrides["tfa_password"] = tfa_pass

    if force:
        clear_user_session(cli_ctx.config)
        click.echo("Force flag set: previous session tokens cleared.")

    async def _login() -> int:
        click.echo(
            f"Authenticating with Arlo (2FA: {cli_ctx.config.get('tfa_type')}:{cli_ctx.config.get('tfa_source')})..."
        )
        arlo = await create_pyarlo(cli_ctx.config, wait_for_setup=True)
        try:
            cache_data = fill_cache(arlo)
            dev_count = len(cache_data.get("devices", []))
            loc_count = len(cache_data.get("locations", []))
            click.echo(f"Successfully authenticated as {cli_ctx.config.get('username')}.")
            click.echo(f"Discovered {dev_count} devices across {loc_count} locations.\n")

            auth_status = get_auth_status(cli_ctx.config)
            print_auth_status(auth_status)
            return 0
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _login())


# -------------------------------------------------------------------------
# Cache
# -------------------------------------------------------------------------
@cli.group()
def cache() -> None:
    """Manage local device and location cache."""
    pass


@cache.command("fill")
@click.pass_obj
def cache_fill(cli_ctx: CLIContext) -> None:
    """Populate or update local cache from Arlo."""
    async def _fill() -> int:
        click.echo("Querying Arlo for fresh device and location catalog...")
        arlo = await create_pyarlo(cli_ctx.config, wait_for_setup=True)
        try:
            cache_data = fill_cache(arlo)
            dev_count = len(cache_data.get("devices", []))
            loc_count = len(cache_data.get("locations", []))
            cache_path = get_default_cache_path()
            click.echo(f"Cache updated: {dev_count} devices, {loc_count} locations saved to {cache_path}")
            return 0
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _fill())


@cache.command("clear")
@click.pass_obj
def cache_clear(cli_ctx: CLIContext) -> None:
    """Remove local cache file."""
    path = get_default_cache_path()
    if clear_cache(path):
        click.echo(f"Cache cleared: {path}")
    else:
        click.echo(f"No cache file existed at {path}")
    cli_ctx.finish_debug_report()
    sys.exit(0)


@cache.command("show")
@click.pass_obj
def cache_show(cli_ctx: CLIContext) -> None:
    """Display information about current cache."""
    cache_path = get_default_cache_path()
    cached = load_cache(cache_path)
    if not cached:
        click.echo(f"No cache found at {cache_path}")
        cli_ctx.finish_debug_report()
        sys.exit(0)

    ts = cached.get("timestamp", 0)
    age_seconds = int(time.time() - ts) if ts else 0
    age_str = f"{age_seconds} seconds ago" if age_seconds < 120 else f"{age_seconds // 60} minutes ago"
    is_stale = is_cache_stale(cached)

    devices = cached.get("devices", [])
    locations = cached.get("locations", [])

    counts: dict[str, int] = {}
    for d in devices:
        t = d.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1

    click.echo(f"Cache Location: {cache_path}")
    click.echo(f"Last Updated:   {time.ctime(ts)} ({age_str}) {'[STALE]' if is_stale else '[VALID]'}")
    click.echo(f"Total Devices:  {len(devices)}")
    for t, cnt in sorted(counts.items()):
        click.echo(f"  - {t}: {cnt}")
    click.echo(f"Locations:      {len(locations)}")
    for loc in locations:
        click.echo(f"  - {loc.get('name')} (ID: {loc.get('id')}, Mode: {loc.get('mode')})")
    cli_ctx.finish_debug_report()
    sys.exit(0)


# -------------------------------------------------------------------------
# Config
# -------------------------------------------------------------------------
@cli.group("config")
def config_group() -> None:
    """View, create, update, or set configuration values."""
    pass


def _run_config_wizard(current: dict[str, Any] | None = None, is_update: bool = False) -> dict[str, Any]:
    current = current or {}
    new_cfg: dict[str, Any] = dict(current)

    click.echo("\n--- PyArlo Configuration Wizard ---")
    if is_update:
        click.echo("Press Enter to keep the current value shown in brackets.\n")
    else:
        click.echo("Please answer the following questions to create your configuration.\n")

    # 1. Username
    default_user = current.get("username", "")
    username = click.prompt(
        "Arlo username (email)",
        default=default_user if default_user else None,
    )
    new_cfg["username"] = username

    # 2. Password
    if is_update and current.get("password"):
        if click.confirm("Keep existing Arlo password?", default=True):
            new_cfg["password"] = current["password"]
        else:
            new_cfg["password"] = click.prompt("Enter new Arlo password", hide_input=True)
    else:
        new_cfg["password"] = click.prompt("Arlo password", hide_input=True)

    # 3. 2FA Delivery
    curr_tfa_type = current.get("tfa_type", "push").lower()
    if curr_tfa_type not in ("push", "email", "sms"):
        curr_tfa_type = "push"

    click.echo("\nSelect 2FA delivery method:")
    click.echo("  push  - Arlo mobile app push notification (Recommended - no code entry needed)")
    click.echo("  email - Verification code sent to your email inbox")
    click.echo("  sms   - Verification code sent via text message (SMS)")
    tfa_type = click.prompt(
        "2FA delivery method",
        type=click.Choice(["push", "email", "sms"], case_sensitive=False),
        default=curr_tfa_type,
    ).lower()

    if tfa_type == "push":
        new_cfg["tfa_type"] = "push"
        new_cfg["tfa_source"] = "push"
        new_cfg.pop("tfa_host", None)
        new_cfg.pop("tfa_username", None)
        new_cfg.pop("tfa_password", None)

    elif tfa_type == "sms":
        new_cfg["tfa_type"] = "sms"
        new_cfg["tfa_source"] = "console"
        new_cfg.pop("tfa_host", None)
        new_cfg.pop("tfa_username", None)
        new_cfg.pop("tfa_password", None)

    elif tfa_type == "email":
        new_cfg["tfa_type"] = "email"
        curr_tfa_source = current.get("tfa_source", "console").lower()
        if curr_tfa_source not in ("console", "imap"):
            curr_tfa_source = "console"

        click.echo("\nHow should PyArlo retrieve the email verification code?")
        click.echo("  console - Prompt you interactively on the terminal to type the code")
        click.echo("  imap    - Connect to your email inbox automatically via IMAP")
        tfa_source = click.prompt(
            "Email code entry method",
            type=click.Choice(["console", "imap"], case_sensitive=False),
            default=curr_tfa_source,
        ).lower()

        new_cfg["tfa_source"] = tfa_source

        if tfa_source == "imap":
            default_host = current.get("tfa_host")
            if not default_host:
                default_host = "imap.gmail.com" if "@gmail" in username.lower() else "imap.example.com"
            new_cfg["tfa_host"] = click.prompt("IMAP server host", default=default_host)

            default_imap_user = current.get("tfa_username", username)
            new_cfg["tfa_username"] = click.prompt("IMAP username", default=default_imap_user)

            if is_update and current.get("tfa_password"):
                if click.confirm("Keep existing IMAP password?", default=True):
                    new_cfg["tfa_password"] = current["tfa_password"]
                else:
                    new_cfg["tfa_password"] = click.prompt("Enter new IMAP password/app-password", hide_input=True)
            else:
                new_cfg["tfa_password"] = click.prompt("IMAP password or app-password", hide_input=True)
        else:
            new_cfg.pop("tfa_host", None)
            new_cfg.pop("tfa_username", None)
            new_cfg.pop("tfa_password", None)

    # 4. Backend
    curr_backend = current.get("backend", "auto").lower()
    if curr_backend not in ("auto", "mqtt", "sse"):
        curr_backend = "auto"
    new_cfg["backend"] = click.prompt(
        "\nEvent stream backend",
        type=click.Choice(["auto", "mqtt", "sse"], case_sensitive=False),
        default=curr_backend,
    ).lower()

    return new_cfg


@config_group.command("show")
@click.option("--unmask", is_flag=True, default=False, help="Display passwords in plain text instead of masking")
@click.pass_obj
def config_show(cli_ctx: CLIContext, unmask: bool) -> None:
    """Display current configuration and file path."""
    target_path = Path(cli_ctx.config_path) if cli_ctx.config_path else get_default_config_path()
    file_cfg = read_config_file(target_path)
    active_cfg = cli_ctx.config

    click.echo(f"Config File Path: {target_path}")
    click.echo(f"File Status:      {'Found' if target_path.is_file() else 'Not found'}\n")

    def _mask_val(key: str, val: Any) -> Any:
        if not unmask and key in ("password", "tfa_password") and val:
            return "********"
        return val

    if file_cfg:
        click.echo("Config File Contents:")
        for k, v in sorted(file_cfg.items()):
            click.echo(f"  {k}: {repr(_mask_val(k, v))}")
    else:
        click.echo("Config File Contents: (empty or missing)")

    click.echo("\nActive Resolved Configuration (including environment & defaults):")
    for k, v in sorted(active_cfg.items()):
        click.echo(f"  {k}: {repr(_mask_val(k, v))}")

    if not unmask and (active_cfg.get("password") or active_cfg.get("tfa_password")):
        click.echo("\n(Passwords are masked. Use 'pyaarlo config show --unmask' to display in plain text.)")

    cli_ctx.finish_debug_report()
    sys.exit(0)


@config_group.command("dump")
@click.option("--unmask", is_flag=True, default=False, help="Display passwords in plain text instead of masking")
@click.pass_obj
def config_dump(cli_ctx: CLIContext, unmask: bool) -> None:
    """Alias for 'pyaarlo config show'."""
    config_show.callback(cli_ctx, unmask=unmask)  # type: ignore


@config_group.command("create")
@click.option("--force", is_flag=True, default=False, help="Overwrite existing configuration file without prompting")
@click.pass_obj
def config_create(cli_ctx: CLIContext, force: bool) -> None:
    """Interactive wizard to create a new configuration file."""
    target_path = Path(cli_ctx.config_path) if cli_ctx.config_path else get_default_config_path()
    if target_path.is_file() and not force:
        if not click.confirm(f"Configuration file already exists at {target_path}. Overwrite?", default=False):
            click.echo("Aborted. Use 'pyaarlo config update' to edit existing settings.")
            cli_ctx.finish_debug_report()
            sys.exit(0)

    new_cfg = _run_config_wizard(is_update=False)
    save_config_file(new_cfg, target_path)
    click.echo(f"\nConfiguration successfully saved to {target_path}!")

    if click.confirm("\nTest authentication with Arlo now?", default=True):
        click.echo("Connecting to Arlo to verify credentials...")

        async def _test() -> int:
            try:
                test_cfg = load_config(config_path=target_path)
                arlo = await create_pyarlo(test_cfg, wait_for_setup=False, start_background=False)
                try:
                    fill_cache(arlo)
                    click.echo("Authentication successful! Cache populated.")
                    return 0
                finally:
                    await arlo.stop(logout=False)
            except Exception as err:
                click.echo(f"Authentication failed: {err}", err=True)
                return 1

        run_async_cli(cli_ctx, _test())
    else:
        cli_ctx.finish_debug_report()
        sys.exit(0)


@config_group.command("update")
@click.pass_obj
def config_update(cli_ctx: CLIContext) -> None:
    """Interactive wizard to update existing configuration with defaults."""
    target_path = Path(cli_ctx.config_path) if cli_ctx.config_path else get_default_config_path()
    existing = read_config_file(target_path)
    if not existing:
        click.echo(f"No existing configuration found at {target_path}. Starting new configuration.\n")

    updated_cfg = _run_config_wizard(current=existing, is_update=bool(existing))
    save_config_file(updated_cfg, target_path)
    click.echo(f"\nConfiguration successfully updated at {target_path}!")

    if click.confirm("\nTest authentication with Arlo now?", default=True):
        click.echo("Connecting to Arlo to verify credentials...")

        async def _test() -> int:
            try:
                test_cfg = load_config(config_path=target_path)
                arlo = await create_pyarlo(test_cfg, wait_for_setup=False, start_background=False)
                try:
                    fill_cache(arlo)
                    click.echo("Authentication successful! Cache updated.")
                    return 0
                finally:
                    await arlo.stop(logout=False)
            except Exception as err:
                click.echo(f"Authentication failed: {err}", err=True)
                return 1

        run_async_cli(cli_ctx, _test())
    else:
        cli_ctx.finish_debug_report()
        sys.exit(0)


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_obj
def config_set(cli_ctx: CLIContext, key: str, value: str) -> None:
    """Set a single configuration key and value directly."""
    target_path = Path(cli_ctx.config_path) if cli_ctx.config_path else get_default_config_path()
    cfg_data = read_config_file(target_path)

    key_lower = key.strip().lower()

    if key_lower in ("tfa", "tfa_type"):
        t_type, t_source = parse_tfa_spec(value)
        cfg_data["tfa_type"] = t_type
        cfg_data["tfa_source"] = t_source
        click.echo(f"Set tfa_type='{t_type}' and tfa_source='{t_source}'")
    else:
        # Convert booleans if applicable
        if value.lower() in ("true", "yes", "1"):
            cfg_data[key] = True
        elif value.lower() in ("false", "no", "0"):
            cfg_data[key] = False
        else:
            cfg_data[key] = value
        click.echo(f"Set {key}={repr(cfg_data[key])}")

    save_config_file(cfg_data, target_path)
    click.echo(f"Saved to {target_path}")
    cli_ctx.finish_debug_report()
    sys.exit(0)


# -------------------------------------------------------------------------
# Light
# -------------------------------------------------------------------------
@cli.group()
def light() -> None:
    """Control Arlo lights (turn on, turn off, set brightness)."""
    pass


@light.command("turn-on")
@click.argument("targets", nargs=-1, required=True)
@click.option("-b", "--brightness", type=int, default=None, help="Brightness level (0-255)")
@click.pass_obj
def light_turn_on(cli_ctx: CLIContext, targets: tuple[str, ...], brightness: int | None) -> None:
    """Turn on one or more lights by name or ID."""
    target_names = parse_targets(targets)
    if not target_names:
        click.echo("Error: Please specify at least one light name or ID.", err=True)
        sys.exit(1)

    async def _turn_on() -> int:
        use_cache = not cli_ctx.ignore_cache
        arlo = await create_pyarlo(
            cli_ctx.config,
            wait_for_setup=False,
            start_background=False,
            refresh_devices=not use_cache,
        )
        try:
            matched, missing = resolve_devices(arlo.lights, target_names)
            if missing and use_cache:
                await arlo._refresh_devices(force=True)
                arlo._build_objects()
                matched, missing = resolve_devices(arlo.lights, target_names)

            exit_code = 0
            for name in missing:
                click.echo(f"Error: Light '{name}' not found.", err=True)
                exit_code = 1

            for lt in matched:
                await lt.turn_on(brightness=brightness)
                bright_str = f" (brightness: {brightness})" if brightness is not None else ""
                click.echo(f"[{lt.name}] Turned ON{bright_str}")

            return exit_code
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _turn_on())


@light.command("turn-off")
@click.argument("targets", nargs=-1, required=True)
@click.pass_obj
def light_turn_off(cli_ctx: CLIContext, targets: tuple[str, ...]) -> None:
    """Turn off one or more lights by name or ID."""
    target_names = parse_targets(targets)
    if not target_names:
        click.echo("Error: Please specify at least one light name or ID.", err=True)
        sys.exit(1)

    async def _turn_off() -> int:
        use_cache = not cli_ctx.ignore_cache
        arlo = await create_pyarlo(
            cli_ctx.config,
            wait_for_setup=False,
            start_background=False,
            refresh_devices=not use_cache,
        )
        try:
            matched, missing = resolve_devices(arlo.lights, target_names)
            if missing and use_cache:
                await arlo._refresh_devices(force=True)
                arlo._build_objects()
                matched, missing = resolve_devices(arlo.lights, target_names)

            exit_code = 0
            for name in missing:
                click.echo(f"Error: Light '{name}' not found.", err=True)
                exit_code = 1

            for lt in matched:
                await lt.turn_off()
                click.echo(f"[{lt.name}] Turned OFF")

            return exit_code
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _turn_off())


@light.command("brightness")
@click.argument("level", type=int)
@click.argument("targets", nargs=-1, required=True)
@click.pass_obj
def light_brightness(cli_ctx: CLIContext, level: int, targets: tuple[str, ...]) -> None:
    """Set brightness level (0-255) for one or more lights."""
    target_names = parse_targets(targets)
    if not target_names:
        click.echo("Error: Please specify at least one light name or ID.", err=True)
        sys.exit(1)

    async def _set_brightness() -> int:
        use_cache = not cli_ctx.ignore_cache
        arlo = await create_pyarlo(
            cli_ctx.config,
            wait_for_setup=False,
            start_background=False,
            refresh_devices=not use_cache,
        )
        try:
            matched, missing = resolve_devices(arlo.lights, target_names)
            if missing and use_cache:
                await arlo._refresh_devices(force=True)
                arlo._build_objects()
                matched, missing = resolve_devices(arlo.lights, target_names)

            exit_code = 0
            for name in missing:
                click.echo(f"Error: Light '{name}' not found.", err=True)
                exit_code = 1

            for lt in matched:
                await lt.set_brightness(level)
                click.echo(f"[{lt.name}] Brightness set to {level}")

            return exit_code
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _set_brightness())


# -------------------------------------------------------------------------
# Location
# -------------------------------------------------------------------------
@cli.group()
def location() -> None:
    """View and change location modes."""
    pass


@location.command("list")
@click.pass_obj
def location_list(cli_ctx: CLIContext) -> None:
    """List locations and their current/available modes."""
    async def _list() -> int:
        # Check cache if valid
        if not cli_ctx.ignore_cache:
            cached = load_cache()
            if cached and not is_cache_stale(cached) and cached.get("locations"):
                for loc in cached["locations"]:
                    modes = list(loc.get("available_modes", {}).keys())
                    click.echo(f"Location: {loc.get('name')} (ID: {loc.get('id')})")
                    click.echo(f"  Active Mode:     {loc.get('mode')}")
                    click.echo(f"  Available Modes: {', '.join(modes)}")
                return 0

        arlo = await create_pyarlo(cli_ctx.config, wait_for_setup=True)
        try:
            for loc in arlo.locations:
                modes = list(loc.available_modes_with_ids.keys())
                click.echo(f"Location: {loc.name} (ID: {loc.device_id})")
                click.echo(f"  Active Mode:     {loc.mode}")
                click.echo(f"  Available Modes: {', '.join(modes)}")
            fill_cache(arlo)
            return 0
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _list())


@location.command("set-mode")
@click.argument("mode")
@click.option("-l", "--location", "loc_target", default=None, help="Location name or ID (optional if only 1 location)")
@click.pass_obj
def location_set_mode(cli_ctx: CLIContext, mode: str, loc_target: str | None) -> None:
    """Set the armed/disarmed mode for a location."""
    async def _set_mode() -> int:
        use_cache = not cli_ctx.ignore_cache
        arlo = await create_pyarlo(
            cli_ctx.config,
            wait_for_setup=False,
            start_background=False,
            refresh_devices=not use_cache,
        )
        try:
            target_loc = resolve_location(arlo.locations, loc_target)
            if target_loc is None and use_cache:
                await arlo._refresh_locations(force=True)
                target_loc = resolve_location(arlo.locations, loc_target)

            if target_loc is None:
                if not arlo.locations:
                    click.echo("Error: No locations found on this Arlo account.", err=True)
                elif loc_target is None:
                    click.echo("Error: Multiple locations found. Please specify --location <name-or-id>.", err=True)
                else:
                    click.echo(f"Error: Location '{loc_target}' not found.", err=True)
                return 1

            click.echo(f"Setting mode '{mode}' on location '{target_loc.name}'...")
            await target_loc.set_mode(mode)
            click.echo(f"[{target_loc.name}] Mode changed to '{mode}' (Current: {target_loc.mode})")
            return 0
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _set_mode())


# -------------------------------------------------------------------------
# Camera
# -------------------------------------------------------------------------
@cli.group()
def camera() -> None:
    """Manage Arlo cameras (snapshot, stream)."""
    pass


@camera.command("snapshot")
@click.argument("targets", nargs=-1, required=True)
@click.pass_obj
def camera_snapshot(cli_ctx: CLIContext, targets: tuple[str, ...]) -> None:
    """Request a fresh snapshot from one or more cameras."""
    target_names = parse_targets(targets)
    if not target_names:
        click.echo("Error: Please specify at least one camera name or ID.", err=True)
        sys.exit(1)

    async def _snapshot() -> int:
        arlo = await create_pyarlo(cli_ctx.config, wait_for_setup=True)
        try:
            matched, missing = resolve_devices(arlo.cameras, target_names)

            exit_code = 0
            for name in missing:
                click.echo(f"Error: Camera '{name}' not found.", err=True)
                exit_code = 1

            for cam in matched:
                click.echo(f"[{cam.name}] Requesting snapshot...")
                success = await cam.request_snapshot()
                if success:
                    click.echo(f"[{cam.name}] Snapshot requested successfully.")
                else:
                    click.echo(f"[{cam.name}] Snapshot request returned false.")
                    exit_code = 1
            return exit_code
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _snapshot())


@camera.command("stream")
@click.argument("target")
@click.option("-f", "--start-ffmpeg", is_flag=True, default=False, help="Launch ffmpeg to capture stream to video_dir")
@click.pass_obj
def camera_stream(cli_ctx: CLIContext, target: str, start_ffmpeg: bool) -> None:
    """Get live stream URL for a camera."""
    async def _stream() -> int:
        arlo = await create_pyarlo(cli_ctx.config, wait_for_setup=True)
        try:
            matched, missing = resolve_devices(arlo.cameras, [target])
            if not matched:
                click.echo(f"Error: Camera '{target}' not found.", err=True)
                return 1

            cam = matched[0]
            click.echo(f"[{cam.name}] Requesting stream URL...")
            stream_url = await cam.get_stream()
            if not stream_url:
                click.echo(f"[{cam.name}] Failed to obtain stream URL.", err=True)
                return 1

            click.echo(f"Stream URL: {stream_url}")

            if start_ffmpeg:
                click.echo("Starting ffmpeg HLS capture in ./video_dir...")
                os.makedirs("video_dir", exist_ok=True)
                os.system(
                    f"ffmpeg -i '{stream_url}' -fflags flush_packets -max_delay 2 "
                    f"-flags -global_header -hls_time 2 -hls_list_size 3 -vcodec copy -y video_dir/video.m3u8"
                )

            return 0
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _stream())


# -------------------------------------------------------------------------
# Media
# -------------------------------------------------------------------------
@cli.group()
def media() -> None:
    """List and download recorded media."""
    pass


def _resolve_date_range(
    days: int | None,
    single_date: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[str, str]:
    now = datetime.datetime.now()
    if single_date:
        d = single_date.replace("-", "").strip()
        return d, d
    if date_from or date_to:
        d_from = date_from.replace("-", "").strip() if date_from else (now - datetime.timedelta(days=7)).strftime("%Y%m%d")
        d_to = date_to.replace("-", "").strip() if date_to else now.strftime("%Y%m%d")
        return d_from, d_to
    n_days = days if days is not None and days > 0 else 1
    d_from = (now - datetime.timedelta(days=n_days - 1)).strftime("%Y%m%d")
    d_to = now.strftime("%Y%m%d")
    return d_from, d_to


def _filter_videos(
    videos: list[Any],
    camera_filters: list[str],
    object_filter: str | None,
) -> list[Any]:
    results = []
    for vid in videos:
        # Camera filter
        if camera_filters:
            cam = getattr(vid, "camera", None)
            cam_name = getattr(cam, "name", "").lower()
            cam_id = getattr(cam, "device_id", "").lower()
            if not any(cf.lower() in (cam_name, cam_id) for cf in camera_filters):
                continue

        # Object filter
        if object_filter and object_filter.lower() != "all":
            obj_type = str(getattr(vid, "object_type", "") or "").lower()
            trigger = str(getattr(vid, "triggered_by", "") or "").lower()
            target_obj = object_filter.lower()
            if target_obj == "motion":
                if trigger != "motion" and not obj_type:
                    continue
            else:
                if target_obj not in (obj_type, trigger):
                    continue

        results.append(vid)

    # Sort newest first
    results.sort(key=lambda v: getattr(v, "created_at", 0), reverse=True)
    return results


@media.command("list")
@click.option("-c", "--camera", "cameras", default=None, help="Filter by camera name or device ID (comma-separated)")
@click.option("--days", type=int, default=1, help="Number of days back to search (default: 1)")
@click.option("--date", "single_date", default=None, help="Specific date to search (YYYY-MM-DD)")
@click.option("--from", "date_from", default=None, help="Start date (YYYY-MM-DD)")
@click.option("--to", "date_to", default=None, help="End date (YYYY-MM-DD)")
@click.option("--object", "object_type", default=None, help="Filter by detected object (person, vehicle, animal, package, motion)")
@click.option("--compact", is_flag=True, default=False, help="Display one line per recording")
@click.option("--json", "json_output", is_flag=True, default=False, help="Display as JSON lines")
@click.pass_obj
def media_list(
    cli_ctx: CLIContext,
    cameras: str | None,
    days: int,
    single_date: str | None,
    date_from: str | None,
    date_to: str | None,
    object_type: str | None,
    compact: bool,
    json_output: bool,
) -> None:
    """List camera recordings with date and object filtering."""
    import json

    d_from, d_to = _resolve_date_range(days, single_date, date_from, date_to)
    cam_targets = parse_targets([cameras]) if cameras else []

    async def _run() -> int:
        use_cache = not cli_ctx.ignore_cache
        arlo = await create_pyarlo(
            cli_ctx.config,
            wait_for_setup=False,
            start_background=False,
            refresh_devices=not use_cache,
        )
        try:
            videos, _, _ = await arlo.ml._sync_library(d_from, d_to, [])
            if not videos:
                click.echo(f"No recordings found between {d_from} and {d_to}.")
                return 0

            filtered = _filter_videos(videos, cam_targets, object_type)
            if not filtered:
                click.echo(f"No recordings matching filters found between {d_from} and {d_to}.")
                return 0

            for vid in filtered:
                cam = getattr(vid, "camera", None)
                cam_name = getattr(cam, "name", "unknown")
                cam_id = getattr(cam, "device_id", "unknown")
                obj_label = getattr(vid, "object_type", None) or getattr(vid, "triggered_by", None) or "recording"
                duration = getattr(vid, "media_duration_seconds", 0)
                dt = getattr(vid, "datetime", None)
                dt_str = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "unknown"
                vid_id = getattr(vid, "id", "")
                url = getattr(vid, "video_url", "")

                if json_output:
                    payload = {
                        "id": vid_id,
                        "timestamp": dt_str,
                        "camera": cam_name,
                        "camera_id": cam_id,
                        "object": obj_label,
                        "duration": duration,
                        "url": url,
                    }
                    click.echo(json.dumps(payload))
                elif compact:
                    click.echo(f"{dt_str} [{cam_name}] {obj_label} ({duration}s) - id={vid_id}")
                else:
                    click.echo(f"[{dt_str}] {cam_name}: {obj_label} ({duration}s)")
                    click.echo(f"  ID:  {vid_id}")
                    click.echo(f"  URL: {url}")
            return 0
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _run())


@media.command("download")
@click.option("-c", "--camera", "cameras", default=None, help="Filter by camera name or device ID (comma-separated)")
@click.option("--days", type=int, default=1, help="Number of days back to search (default: 1)")
@click.option("--date", "single_date", default=None, help="Specific date to search (YYYY-MM-DD)")
@click.option("--from", "date_from", default=None, help="Start date (YYYY-MM-DD)")
@click.option("--to", "date_to", default=None, help="End date (YYYY-MM-DD)")
@click.option("--object", "object_type", default=None, help="Filter by detected object (person, vehicle, animal, package, motion)")
@click.option("-o", "--output-dir", default="./media", help="Destination folder for downloaded files (default: ./media)")
@click.option("--limit", type=int, default=None, help="Maximum number of files to download")
@click.option("--thumbnails", is_flag=True, default=False, help="Download thumbnail images instead of full videos")
@click.pass_obj
def media_download(
    cli_ctx: CLIContext,
    cameras: str | None,
    days: int,
    single_date: str | None,
    date_from: str | None,
    date_to: str | None,
    object_type: str | None,
    output_dir: str,
    limit: int | None,
    thumbnails: bool,
) -> None:
    """Download recordings or thumbnails to local disk."""
    d_from, d_to = _resolve_date_range(days, single_date, date_from, date_to)
    cam_targets = parse_targets([cameras]) if cameras else []

    async def _run() -> int:
        use_cache = not cli_ctx.ignore_cache
        arlo = await create_pyarlo(
            cli_ctx.config,
            wait_for_setup=False,
            start_background=False,
            refresh_devices=not use_cache,
        )
        try:
            videos, _, _ = await arlo.ml._sync_library(d_from, d_to, [])
            if not videos:
                click.echo(f"No recordings found between {d_from} and {d_to}.")
                return 0

            filtered = _filter_videos(videos, cam_targets, object_type)
            if not filtered:
                click.echo(f"No recordings matching filters found between {d_from} and {d_to}.")
                return 0

            if limit is not None and limit > 0:
                filtered = filtered[:limit]

            dest_dir = Path(output_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)

            file_type = "thumbnail" if thumbnails else "video"
            click.echo(f"Downloading {len(filtered)} {file_type}(s) to {dest_dir}...")
            count = 0
            for vid in filtered:
                cam = getattr(vid, "camera", None)
                cam_name = getattr(cam, "name", "cam").replace(" ", "_").lower()
                dt = getattr(vid, "datetime", None)
                dt_str = dt.strftime("%Y%m%d_%H%M%S") if dt else f"id_{getattr(vid, 'id', '0')}"
                obj_label = getattr(vid, "object_type", None) or getattr(vid, "triggered_by", None) or "recording"
                ext = "jpg" if thumbnails else getattr(vid, "extension", "mp4")

                filename = str(dest_dir / f"{dt_str}_{cam_name}_{obj_label}.{ext}")

                if thumbnails:
                    ok = await vid.download_thumbnail(filename)
                else:
                    ok = await vid.download_video(filename)

                if ok:
                    click.echo(f"  [OK] {filename}")
                    count += 1
                else:
                    click.echo(f"  [FAILED] {filename}", err=True)

            click.echo(f"Successfully downloaded {count}/{len(filtered)} file(s).")
            return 0 if count == len(filtered) else 1
        finally:
            await arlo.stop(logout=False)

    run_async_cli(cli_ctx, _run())


# -------------------------------------------------------------------------
# List
# -------------------------------------------------------------------------
@cli.command("list")
@click.argument("item", default="all", type=click.Choice(
    ["all", "devices", "cameras", "lights", "doorbells", "bases", "locations", "sensors"],
    case_sensitive=False,
))
@click.option("-c", "--compact", is_flag=True, default=False, help="Display items in compact format")
@click.pass_obj
def list_cmd(cli_ctx: CLIContext, item: str, compact: bool) -> None:
    """List Arlo devices, locations, or subsystems."""
    async def _list() -> int:
        # Check cache if not ignoring cache
        if not cli_ctx.ignore_cache:
            cached = load_cache()
            if cached and not is_cache_stale(cached):
                _print_cached_list(cached, item, compact)
                return 0

        # Live query
        arlo = await create_pyarlo(cli_ctx.config, wait_for_setup=True)
        try:
            cache_data = fill_cache(arlo)
            _print_cached_list(cache_data, item, compact)
            return 0
        finally:
            await arlo.stop(logout=False)

    def _print_cached_list(data: dict[str, Any], item_type: str, is_compact: bool) -> None:
        devices = data.get("devices", [])
        locations = data.get("locations", [])

        type_map = {
            "bases": ["base_station"],
            "cameras": ["camera"],
            "lights": ["light"],
            "doorbells": ["doorbell"],
            "sensors": ["sensor"],
            "devices": ["camera", "light", "doorbell", "sensor", "base_station"],
            "all": ["camera", "light", "doorbell", "sensor", "base_station"],
        }

        if item_type in type_map:
            filtered = [d for d in devices if d.get("type") in type_map[item_type]]
            for d in filtered:
                if is_compact:
                    click.echo(f"[{d.get('type')}] {d.get('name')} (ID: {d.get('id')}, SN: {d.get('serial_number')})")
                else:
                    click.echo(f"{d.get('name')}:")
                    click.echo(f"  Type:          {d.get('type')}")
                    click.echo(f"  Device ID:     {d.get('id')}")
                    click.echo(f"  Model:         {d.get('model_id')}")
                    click.echo(f"  Serial Number: {d.get('serial_number')}")

        if item_type in ("all", "locations"):
            for loc in locations:
                if is_compact:
                    click.echo(f"[location] {loc.get('name')} (ID: {loc.get('id')}, Mode: {loc.get('mode')})")
                else:
                    click.echo(f"Location {loc.get('name')}:")
                    click.echo(f"  ID:              {loc.get('id')}")
                    click.echo(f"  Mode:            {loc.get('mode')}")
                    modes = list(loc.get("available_modes", {}).keys())
                    click.echo(f"  Available Modes: {', '.join(modes)}")

    run_async_cli(cli_ctx, _list())


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
