from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import platformdirs

from ..core.cfg import parse_tfa_spec

APP_NAME = "pyaarlo"


def get_config_dir() -> Path:
    """Return the OS-preferred configuration directory for pyaarlo."""
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def get_cache_dir() -> Path:
    """Return the OS-preferred cache directory for pyaarlo."""
    return Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))


def get_default_config_path() -> Path:
    """Return default config file path."""
    return get_config_dir() / "config.json"


def get_default_cache_path() -> Path:
    """Return default cache file path."""
    return get_cache_dir() / "cache.json"


def read_config_file(config_path: Path | str | None = None) -> dict[str, Any]:
    """Read configuration from a JSON file if it exists."""
    path = Path(config_path) if config_path is not None else get_default_config_path()
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            return {}
    return {}


def save_config_file(config_data: dict[str, Any], config_path: Path | str | None = None) -> Path:
    """Save configuration to JSON file."""
    path = Path(config_path) if config_path is not None else get_default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)
    return path


def read_env_config() -> dict[str, Any]:
    """Read configuration from environment variables with ARLO_ prefix (plus IMAP fallbacks)."""
    env_cfg: dict[str, Any] = {}

    env_mappings = {
        "ARLO_USERNAME": "username",
        "ARLO_PASSWORD": "password",
        "ARLO_TFA": "tfa",
        "ARLO_TFA_TYPE": "tfa",
        "ARLO_TFA_SOURCE": "tfa_source",
        "ARLO_TFA_HOST": "tfa_host",
        "ARLO_TFA_USERNAME": "tfa_username",
        "ARLO_TFA_PASSWORD": "tfa_password",
        "ARLO_STORAGE_DIR": "storage_dir",
        "ARLO_CACHE_DIR": "cache_dir",
        "ARLO_BACKEND": "backend",
        "ARLO_MODE_API": "mode_api",
        "ARLO_USER_AGENT": "user_agent",
        "ARLO_MQTT_HOST": "mqtt_host",
        "ARLO_INLINE_MODE": "inline_mode",
        "ARLO_START_BACKGROUND": "start_background",
    }

    for env_var, cfg_key in env_mappings.items():
        val = os.environ.get(env_var)
        if val is not None and val != "":
            env_cfg[cfg_key] = val

    if "inline_mode" in env_cfg:
        env_cfg["inline_mode"] = str(env_cfg["inline_mode"]).lower() in ("true", "1", "yes")
    if "start_background" in env_cfg:
        env_cfg["start_background"] = str(env_cfg["start_background"]).lower() in ("true", "1", "yes")

    # Backwards-compatible IMAP fallbacks for test.py compatibility
    if "tfa_host" not in env_cfg:
        imap_host = os.environ.get("IMAP_HOST") or os.environ.get("ARLO_IMAP_HOST")
        if imap_host:
            env_cfg["tfa_host"] = imap_host
    if "tfa_username" not in env_cfg:
        imap_user = os.environ.get("IMAP_USERNAME") or os.environ.get("ARLO_IMAP_USERNAME")
        if imap_user:
            env_cfg["tfa_username"] = imap_user
    if "tfa_password" not in env_cfg:
        imap_pwd = os.environ.get("IMAP_PASSWORD") or os.environ.get("ARLO_IMAP_PASSWORD")
        if imap_pwd:
            env_cfg["tfa_password"] = imap_pwd

    return env_cfg


def load_config(
    cli_overrides: dict[str, Any] | None = None,
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    """Load configuration resolving precedence: CLI overrides > Env Vars > JSON file > Defaults."""
    # 1. Defaults
    config: dict[str, Any] = {
        "storage_dir": str(get_cache_dir()),
        "cache_dir": str(get_cache_dir()),
        "backend": "auto",
        "mode_api": "auto",
    }

    # 2. JSON config file
    file_cfg = read_config_file(config_path)
    config.update({k: v for k, v in file_cfg.items() if v is not None})

    # 3. Environment variables
    env_cfg = read_env_config()
    config.update({k: v for k, v in env_cfg.items() if v is not None})

    # 4. CLI overrides
    if cli_overrides:
        config.update({k: v for k, v in cli_overrides.items() if v is not None})

    # 5. Normalize 2FA configuration
    tfa_spec = config.get("tfa")
    if not tfa_spec:
        if config.get("tfa_type") and config.get("tfa_source"):
            tfa_spec = f"{config['tfa_type']}:{config['tfa_source']}"
        elif config.get("tfa_type"):
            tfa_spec = config["tfa_type"]
        else:
            tfa_spec = "push"

    parsed_type, parsed_source = parse_tfa_spec(tfa_spec)
    config["tfa"] = tfa_spec
    config["tfa_type"] = parsed_type

    # If tfa_source wasn't explicitly given in cli or env, use parsed source
    explicit_source = (
        (cli_overrides and "tfa_source" in cli_overrides and cli_overrides["tfa_source"])
        or (env_cfg and "tfa_source" in env_cfg and env_cfg["tfa_source"])
    )
    config["tfa_source"] = config.get("tfa_source") if explicit_source else parsed_source

    return config
