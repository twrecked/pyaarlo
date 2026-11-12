from typing import Any
from pathlib import Path
from unittest.mock import patch

from pyaarlo.cli.config import (
    get_config_dir,
    get_cache_dir,
    read_config_file,
    save_config_file,
    read_env_config,
    load_config,
)


def test_cli_config_paths():
    config_dir = get_config_dir()
    cache_dir = get_cache_dir()
    assert isinstance(config_dir, Path)
    assert isinstance(cache_dir, Path)
    assert "pyaarlo" in str(config_dir).lower()
    assert "pyaarlo" in str(cache_dir).lower()


def test_cli_config_save_and_read(tmp_path: Path):
    cfg_file = tmp_path / "sub" / "config.json"
    data = {"username": "test@example.com", "tfa_source": "imap"}

    saved_path = save_config_file(data, cfg_file)
    assert saved_path == cfg_file
    assert cfg_file.is_file()

    loaded = read_config_file(cfg_file)
    assert loaded == data


def test_cli_config_env_vars():
    env_vars = {
        "ARLO_USERNAME": "env_user@example.com",
        "ARLO_PASSWORD": "env_password",
        "ARLO_TFA_HOST": "imap.env.com",
        "IMAP_USERNAME": "imap_user",
        "IMAP_PASSWORD": "imap_password",
    }
    with patch.dict("os.environ", env_vars, clear=True):
        parsed = read_env_config()
        assert parsed["username"] == "env_user@example.com"
        assert parsed["password"] == "env_password"
        assert parsed["tfa_host"] == "imap.env.com"
        assert parsed["tfa_username"] == "imap_user"
        assert parsed["tfa_password"] == "imap_password"


def test_cli_config_precedence(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    save_config_file({
        "username": "file_user@example.com",
        "password": "file_password",
        "tfa_type": "sms",
    }, cfg_file)

    env_vars = {
        "ARLO_PASSWORD": "env_password",
        "ARLO_TFA_SOURCE": "imap",
    }

    cli_overrides = {
        "password": "cli_password",
    }

    with patch.dict("os.environ", env_vars, clear=True):
        final_cfg = load_config(cli_overrides=cli_overrides, config_path=cfg_file)

        # CLI overrides Env and File
        assert final_cfg["password"] == "cli_password"
        # File provides username (not in env or cli)
        assert final_cfg["username"] == "file_user@example.com"
        # Env provides tfa_source (not in file or cli)
        assert final_cfg["tfa_source"] == "imap"
        # File provides tfa_type
        assert final_cfg["tfa_type"] == "sms"


def test_cli_config_tfa_spec():
    from pyaarlo.cli.config import parse_tfa_spec

    assert parse_tfa_spec("push") == ("push", "push")
    assert parse_tfa_spec("email:imap") == ("email", "imap")
    assert parse_tfa_spec("email:console") == ("email", "console")
    assert parse_tfa_spec("sms:console") == ("sms", "console")
    assert parse_tfa_spec("sms") == ("sms", "console")
    assert parse_tfa_spec("imap") == ("email", "imap")
    assert parse_tfa_spec("console") == ("email", "console")
    assert parse_tfa_spec("email") == ("email", "console")


def test_cli_config_compound_env_vars(tmp_path):
    empty_cfg = tmp_path / "empty.json"
    # Test ARLO_TFA_TYPE="email:imap"
    with patch.dict("os.environ", {"ARLO_TFA_TYPE": "email:imap"}, clear=True):
        cfg = load_config(config_path=empty_cfg)
        assert cfg["tfa_type"] == "email"
        assert cfg["tfa_source"] == "imap"

    # Test ARLO_TFA="push"
    with patch.dict("os.environ", {"ARLO_TFA": "push"}, clear=True):
        cfg = load_config(config_path=empty_cfg)
        assert cfg["tfa_type"] == "push"
        assert cfg["tfa_source"] == "push"

    # Test ARLO_TFA_TYPE="sms"
    with patch.dict("os.environ", {"ARLO_TFA_TYPE": "sms"}, clear=True):
        cfg = load_config(config_path=empty_cfg)
        assert cfg["tfa_type"] == "sms"
        assert cfg["tfa_source"] == "console"



def test_read_hass_config(tmp_path: Path):
    from pyaarlo.cli.config import read_hass_config
    import json
    import pytest

    storage_dir = tmp_path / ".storage"
    storage_dir.mkdir(parents=True)
    entries_file = storage_dir / "core.config.entries"

    sample_entries: dict[str, Any] = {
        "version": 1,
        "key": "core.config.entries",
        "data": {
            "entries": [
                {
                    "domain": "other_component",
                    "data": {"foo": "bar"}
                },
                {
                    "domain": "aarlo",
                    "data": {
                        "username": "ha_user@example.com",
                        "password": "ha_password",
                        "tfa": "push",
                        "tfa_type": "push",
                        "tfa_source": "push"
                    },
                    "options": {}
                }
            ]
        }
    }
    with open(entries_file, "w") as f:
        json.dump(sample_entries, f)

    # 1. Parse from directory
    cfg_dir = read_hass_config(tmp_path)
    assert cfg_dir["username"] == "ha_user@example.com"
    assert cfg_dir["password"] == "ha_password"
    assert cfg_dir["tfa"] == "push"
    assert cfg_dir["storage_dir"] == str(tmp_path / ".aarlo")
    assert cfg_dir["cache_dir"] == str(tmp_path / ".aarlo")

    # 2. Parse from file directly
    cfg_file = read_hass_config(entries_file)
    assert cfg_file["username"] == "ha_user@example.com"
    assert cfg_file["storage_dir"] == str(tmp_path / ".aarlo")

    # 3. Missing aarlo domain
    sample_entries = {"data": {"entries": [{"domain": "other"}]}}
    with open(entries_file, "w") as f:
        json.dump(sample_entries, f)
    with pytest.raises(ValueError, match="No 'aarlo' integration entry found"):
        read_hass_config(tmp_path)

    # 4. Missing core.config.entries file
    empty_dir = tmp_path / "nonexistent"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        read_hass_config(empty_dir)


def test_load_config_with_hass(tmp_path: Path):
    import json

    storage_dir = tmp_path / ".storage"
    storage_dir.mkdir(parents=True)
    entries_file = storage_dir / "core.config.entries"

    sample_entries: dict[str, Any] = {
        "version": 1,
        "key": "core.config.entries",
        "data": {
            "entries": [
                {
                    "domain": "aarlo",
                    "data": {
                        "username": "ha_user@example.com",
                        "password": "ha_password",
                        "tfa": "push"
                    },
                    "options": {}
                }
            ]
        }
    }
    with open(entries_file, "w") as f:
        json.dump(sample_entries, f)

    # File cfg with different user
    cfg_file = tmp_path / "config.json"
    save_config_file({"username": "file_user@example.com", "password": "file_password"}, cfg_file)

    # CLI override
    cli_overrides = {"password": "override_password"}

    final_cfg = load_config(
        cli_overrides=cli_overrides,
        config_path=cfg_file,
        hass_path=tmp_path,
    )

    # HASS overrides config.json
    assert final_cfg["username"] == "ha_user@example.com"
    # CLI overrides HASS
    assert final_cfg["password"] == "override_password"
    # Storage dir set to .aarlo
    assert final_cfg["storage_dir"] == str(tmp_path / ".aarlo")
