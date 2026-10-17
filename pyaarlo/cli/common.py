from __future__ import annotations

import asyncio
import functools
import logging
import sys
from typing import Any, Callable, Coroutine

import click

from .config import load_config
from .cache import load_cache, is_cache_stale, fill_cache
from .. import PyArlo


class CLIContext:
    def __init__(
        self,
        config_path: str | None = None,
        ignore_cache: bool = False,
        verbose: int = 0,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.config_path = config_path
        self.ignore_cache = ignore_cache
        self.verbose = verbose
        self.cli_overrides: dict[str, Any] = {}
        if username is not None:
            self.cli_overrides["username"] = username
        if password is not None:
            self.cli_overrides["password"] = password

        self._config: dict[str, Any] | None = None

    @property
    def config(self) -> dict[str, Any]:
        if self._config is None:
            self._config = load_config(self.cli_overrides, self.config_path)
        return self._config


def setup_logging(verbose: int) -> None:
    """Configure logging level based on verbosity count."""
    level = logging.ERROR
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("pyaarlo").setLevel(level)


def common_options(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to apply common CLI options across commands."""
    options = [
        click.option("-c", "--config", "config_path", default=None, help="Path to JSON config file"),
        click.option("-v", "--verbose", count=True, help="Increase verbosity (-v for INFO, -vv for DEBUG)"),
        click.option("-u", "--username", default=None, help="Arlo username (overrides config/env)"),
        click.option("-p", "--password", default=None, help="Arlo password (overrides config/env)"),
        click.option("--ignore-cache", is_flag=True, default=False, help="Bypass cache and query Arlo live"),
    ]
    for option in reversed(options):
        f = option(f)
    return f


def async_command(coro_fn: Callable[..., Coroutine[Any, Any, int | None]]) -> Callable[..., None]:
    """Wrapper to run an async Click command in the asyncio event loop."""
    @functools.wraps(coro_fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            exit_code = asyncio.run(coro_fn(*args, **kwargs))
            if exit_code is None:
                exit_code = 0
            sys.exit(exit_code)
        except click.ClickException:
            raise
        except KeyboardInterrupt:
            sys.stderr.write("\nInterrupted by user.\n")
            sys.exit(0)
        except Exception as err:
            sys.stderr.write(f"Error: {err}\n")
            sys.exit(1)

    return wrapper


async def create_pyarlo(
    cfg: dict[str, Any],
    wait_for_setup: bool = True,
    dump: bool = False,
) -> PyArlo:
    """Create and initialize an async PyArlo instance from resolved configuration."""
    username = cfg.get("username")
    password = cfg.get("password")

    if not username or not password:
        raise ValueError("Missing Arlo username or password. Specify in config.json, environment, or --username/--password")

    arlo = await PyArlo.create(
        username=username,
        password=password,
        tfa_source=cfg.get("tfa_source", "console"),
        tfa_type=cfg.get("tfa_type", "email"),
        tfa_host=cfg.get("tfa_host"),
        tfa_username=cfg.get("tfa_username"),
        tfa_password=cfg.get("tfa_password"),
        storage_dir=cfg.get("storage_dir"),
        mode_api=cfg.get("mode_api", "auto"),
        backend=cfg.get("backend", "auto"),
        user_agent=cfg.get("user_agent", "arlo"),
        mqtt_host=cfg.get("mqtt_host"),
        save_session=True,
        save_state=True,
        wait_for_initial_setup=wait_for_setup,
        dump=dump,
    )

    if not arlo.is_connected:
        raise RuntimeError("Failed to connect or authenticate with Arlo")

    return arlo


def clear_user_session(cfg: dict[str, Any]) -> None:
    """Remove saved session and cookie files for the configured user to force full re-login."""
    import re
    from pathlib import Path

    username = cfg.get("username")
    storage_dir = cfg.get("storage_dir")
    if username and storage_dir:
        safe_user = re.sub(r"[^0-9a-zA-Z]+", "_", username)
        storage_path = Path(storage_dir)
        for suffix in ("session", "cookies"):
            f = storage_path / f"{safe_user}.{suffix}"
            if f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass


def format_time_delta(seconds: float) -> str:
    """Format duration in seconds into a friendly human-readable string."""
    is_past = seconds < 0
    sec = abs(int(seconds))
    days, remainder = divmod(sec, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0 or days > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if days == 0 and (minutes > 0 or len(parts) == 0):
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

    res = ", ".join(parts[:2])
    return f"{res} ago" if is_past else f"in {res}"


def get_auth_status(cfg: dict[str, Any]) -> dict[str, Any]:
    """Inspect saved session and cookies for token expiration details."""
    import datetime
    import pickle
    import re
    import time
    from http.cookiejar import LWPCookieJar
    from pathlib import Path

    username = cfg.get("username", "unknown")
    storage_dir = cfg.get("storage_dir")

    status: dict[str, Any] = {
        "username": username,
        "has_session": False,
        "session_expires_at": None,
        "session_remaining": None,
        "session_valid": False,
        "has_browser_trust": False,
        "browser_trust_name": None,
        "browser_trust_expires_at": None,
        "browser_trust_remaining": None,
        "browser_trust_valid": False,
    }

    if not storage_dir or username == "unknown":
        return status

    safe_user = re.sub(r"[^0-9a-zA-Z]+", "_", username)
    storage_path = Path(storage_dir)
    session_file = storage_path / f"{safe_user}.session"
    cookies_file = storage_path / f"{safe_user}.cookies"
    now = time.time()

    # 1. Read session file
    if session_file.is_file():
        try:
            with open(session_file, "rb") as f:
                sdata = pickle.load(f)
                if isinstance(sdata, dict) and sdata.get("token"):
                    status["has_session"] = True
                    exp = sdata.get("expires_in")
                    if exp:
                        exp_ts = float(exp)
                        status["session_expires_at"] = exp_ts
                        rem = exp_ts - now
                        status["session_remaining"] = rem
                        status["session_valid"] = rem > 0
        except Exception:
            pass

    # 2. Read cookies file for browser_trust_*
    if cookies_file.is_file():
        try:
            jar = LWPCookieJar(str(cookies_file))
            jar.load(ignore_discard=True)
            for c in jar:
                if c.name.startswith("browser_trust"):
                    status["has_browser_trust"] = True
                    status["browser_trust_name"] = c.name
                    if c.expires:
                        exp_ts = float(c.expires)
                        status["browser_trust_expires_at"] = exp_ts
                        rem = exp_ts - now
                        status["browser_trust_remaining"] = rem
                        status["browser_trust_valid"] = rem > 0
                    break
        except Exception:
            pass

    return status


def print_auth_status(status: dict[str, Any]) -> int:
    """Print formatted authentication status and return appropriate exit code (0 if valid, 1 if expired/missing)."""
    import datetime

    username = status.get("username", "unknown")
    has_session = status.get("has_session", False)
    session_valid = status.get("session_valid", False)
    session_exp = status.get("session_expires_at")
    session_rem = status.get("session_remaining")

    has_trust = status.get("has_browser_trust", False)
    trust_valid = status.get("browser_trust_valid", False)
    trust_name = status.get("browser_trust_name")
    trust_exp = status.get("browser_trust_expires_at")
    trust_rem = status.get("browser_trust_remaining")

    sys.stdout.write("Authentication Status:\n")
    sys.stdout.write(f"  User:                     {username}\n")

    # Session token
    if has_session and session_exp and session_rem is not None:
        dt_str = datetime.datetime.fromtimestamp(session_exp).strftime("%Y-%m-%d %H:%M:%S")
        delta_str = format_time_delta(session_rem)
        state_label = "ACTIVE" if session_valid else "EXPIRED"
        sys.stdout.write(f"  Session Token:            {state_label}\n")
        sys.stdout.write(f"    - Expires At:           {dt_str} ({delta_str})\n")
    elif has_session:
        sys.stdout.write("  Session Token:            PRESENT (no expiry timestamp)\n")
    else:
        sys.stdout.write("  Session Token:            NOT FOUND\n")

    # Browser trust token
    if has_trust and trust_exp and trust_rem is not None:
        dt_str = datetime.datetime.fromtimestamp(trust_exp).strftime("%Y-%m-%d %H:%M:%S")
        delta_str = format_time_delta(trust_rem)
        state_label = "ACTIVE" if trust_valid else "EXPIRED"
        label_suffix = f" ({trust_name})" if trust_name else ""
        sys.stdout.write(f"  2FA Browser Trust Token:  {state_label}{label_suffix}\n")
        sys.stdout.write(f"    - Expires At:           {dt_str} ({delta_str})\n")
    elif has_trust:
        sys.stdout.write(f"  2FA Browser Trust Token:  PRESENT ({trust_name})\n")
    else:
        sys.stdout.write("  2FA Browser Trust Token:  NOT FOUND\n")

    sys.stdout.write("\nSummary: ")
    if session_valid and trust_valid:
        sys.stdout.write("Both tokens are valid. Background renewals will not require 2FA.\n")
        return 0
    elif session_valid:
        sys.stdout.write("Session token is valid, but 2FA trust is missing or expired. Next re-auth will require 2FA.\n")
        return 0
    elif trust_valid:
        sys.stdout.write("Session token expired, but 2FA browser trust is valid. Run 'pyaarlo login' to renew without 2FA.\n")
        return 1
    else:
        sys.stdout.write("No valid session or 2FA trust. Run 'pyaarlo login' to authenticate with 2FA.\n")
        return 1


async def ensure_cache(
    ctx: CLIContext,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Ensure cache is populated, refreshing from Arlo if empty, stale, or forced."""
    if not force_refresh and not ctx.ignore_cache:
        cached = load_cache()
        if cached is not None and not is_cache_stale(cached):
            return cached

    arlo = await create_pyarlo(ctx.config, wait_for_setup=True)
    try:
        cache_data = fill_cache(arlo)
        return cache_data
    finally:
        await arlo.stop(logout=False)
