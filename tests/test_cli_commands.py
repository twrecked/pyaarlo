from unittest.mock import patch
from click.testing import CliRunner

from pyaarlo.cli.main_cmd import cli as pyaarlo_cli
from pyaarlo.cli.monitor_cmd import cli as monitor_cli
from pyaarlo.cli.utils_cmd import (
    cli as utils_cli,
    encrypt_to_string,
    decrypt_from_string,
    anonymize_text,
    BEGIN_PYAARLO_DUMP,
    END_PYAARLO_DUMP,
)


def test_pyaarlo_help():
    runner = CliRunner()
    result = runner.invoke(pyaarlo_cli, ["--help"])
    assert result.exit_code == 0
    assert "--backend" in result.output
    assert "--inline" in result.output
    assert "login" in result.output
    assert "cache" in result.output
    assert "light" in result.output
    assert "location" in result.output
    assert "camera" in result.output
    assert "config" in result.output
    assert "media" in result.output
    assert "local-media" in result.output
    assert "list" in result.output


def test_pyaarlo_media_help():
    runner = CliRunner()
    result = runner.invoke(pyaarlo_cli, ["media", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "download" in result.output

    res_list = runner.invoke(pyaarlo_cli, ["media", "list", "--help"])
    assert res_list.exit_code == 0
    assert "--camera" in res_list.output
    assert "--days" in res_list.output
    assert "--object" in res_list.output

    res_down = runner.invoke(pyaarlo_cli, ["media", "download", "--help"])
    assert res_down.exit_code == 0
    assert "--output-dir" in res_down.output
    assert "--thumbnails" in res_down.output


def test_pyaarlo_local_media_help():
    runner = CliRunner()
    result = runner.invoke(pyaarlo_cli, ["local-media", "--help"])
    assert result.exit_code == 0
    assert "status" in result.output
    assert "list" in result.output
    assert "download" in result.output

    res_stat = runner.invoke(pyaarlo_cli, ["local-media", "status", "--help"])
    assert res_stat.exit_code == 0
    assert "--public" in res_stat.output

    res_list = runner.invoke(pyaarlo_cli, ["local-media", "list", "--help"])
    assert res_list.exit_code == 0
    assert "--base" in res_list.output
    assert "--camera" in res_list.output
    assert "--public" in res_list.output

    res_down = runner.invoke(pyaarlo_cli, ["local-media", "download", "--help"])
    assert res_down.exit_code == 0
    assert "--base" in res_down.output
    assert "--output-dir" in res_down.output


def test_media_date_and_filter_helpers():
    from types import SimpleNamespace
    from pyaarlo.cli.main_cmd import _resolve_date_range, _filter_videos

    # Single date
    d_from, d_to = _resolve_date_range(None, "2026-10-15", None, None)
    assert d_from == "20261015"
    assert d_to == "20261015"

    # From-To
    d_from, d_to = _resolve_date_range(None, None, "2026-10-01", "2026-10-05")
    assert d_from == "20261001"
    assert d_to == "20261005"

    # Days
    d_from, d_to = _resolve_date_range(1, None, None, None)
    assert len(d_from) == 8
    assert len(d_to) == 8

    # Filter videos
    cam1 = SimpleNamespace(name="Front Door", device_id="CAM1")
    cam2 = SimpleNamespace(name="Driveway", device_id="CAM2")

    v1 = SimpleNamespace(camera=cam1, object_type="person", triggered_by="motion", created_at=100)
    v2 = SimpleNamespace(camera=cam2, object_type="vehicle", triggered_by="motion", created_at=200)
    v3 = SimpleNamespace(camera=cam1, object_type="animal", triggered_by="motion", created_at=300)

    videos = [v1, v2, v3]

    # Camera filter
    res = _filter_videos(videos, ["CAM1"], None)
    assert res == [v3, v1]  # Sorted newest first (300, 100)

    # Object filter
    res = _filter_videos(videos, [], "vehicle")
    assert res == [v2]

    # Combined
    res = _filter_videos(videos, ["Front Door"], "animal")
    assert res == [v3]


def test_pyaarlo_login_help():
    runner = CliRunner()
    result = runner.invoke(pyaarlo_cli, ["login", "--help"])
    assert result.exit_code == 0
    assert "--tfa" in result.output
    assert "--push" in result.output
    assert "--force" in result.output


def test_clear_user_session(tmp_path):
    from pyaarlo.cli.common import clear_user_session
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()

    session_file = storage_dir / "test_user_gmail_com.session"
    cookies_file = storage_dir / "test_user_gmail_com.cookies"
    session_file.write_text("session_content")
    cookies_file.write_text("cookie_content")

    cfg = {
        "username": "test.user@gmail.com",
        "storage_dir": str(storage_dir),
    }

    clear_user_session(cfg)
    assert not session_file.exists()
    assert not cookies_file.exists()


def test_pyaarlo_cache_commands(tmp_path):
    runner = CliRunner()
    cache_file = tmp_path / "cache.json"

    with patch("pyaarlo.cli.main_cmd.get_default_cache_path", return_value=cache_file):
        # Cache show when no cache
        res = runner.invoke(pyaarlo_cli, ["cache", "show"])
        assert res.exit_code == 0
        assert "No cache found" in res.output

        # Cache clear
        res = runner.invoke(pyaarlo_cli, ["cache", "clear"])
        assert res.exit_code == 0


def test_pyaarlo_monitor_help():
    runner = CliRunner()
    result = runner.invoke(monitor_cli, ["--help"])
    assert result.exit_code == 0
    assert "--filter-device" in result.output
    assert "--filter-event" in result.output
    assert "--compact" in result.output
    assert "--length" in result.output
    assert "--sse" in result.output
    assert "--backend" in result.output
    assert "--json" in result.output


def test_pyaarlo_utils_help():
    runner = CliRunner()
    result = runner.invoke(utils_cli, ["--help"])
    assert result.exit_code == 0
    assert "anonymize" in result.output
    assert "encrypt" in result.output
    assert "decrypt" in result.output
    assert "dump" in result.output


def test_pyaarlo_utils_anonymize():
    devices = [
        {"deviceId": "DEV123456", "userId": "USR987654", "name": "Front Cam"}
    ]
    raw_text = "Device DEV123456 owned by user USR987654 account test@example.com"
    anon = anonymize_text(raw_text, devices=devices, username="test@example.com")

    assert "DEV123456" not in anon
    assert "USR987654" not in anon
    assert "test@example.com" not in anon
    assert "DEV_01_ID" in anon
    assert "USER_01_ID" in anon
    assert "USERNAME" in anon


def test_pyaarlo_utils_encrypt_command():
    runner = CliRunner()
    result = runner.invoke(utils_cli, ["encrypt"], input="Hello PyArlo Secret!")
    assert result.exit_code == 0
    assert BEGIN_PYAARLO_DUMP in result.output
    assert END_PYAARLO_DUMP in result.output


def test_auth_status_formatting(tmp_path):
    import time
    import pickle
    from pyaarlo.cli.common import get_auth_status, print_auth_status, format_time_delta

    assert "in 1 hour" in format_time_delta(3600)
    assert "ago" in format_time_delta(-3600)

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()

    # Create dummy session with future expiry
    now = time.time()
    session_file = storage_dir / "user_test_com.session"
    with open(session_file, "wb") as f:
        pickle.dump({"token": "tok123", "expires_in": str(now + 7200)}, f)

    cfg = {"username": "user@test.com", "storage_dir": str(storage_dir)}
    status = get_auth_status(cfg)

    assert status["has_session"] is True
    assert status["session_valid"] is True
    assert status["has_browser_trust"] is False


def test_pyaarlo_login_status_cli(tmp_path):
    runner = CliRunner()
    empty_cfg = tmp_path / "empty.json"
    # Test with no session
    result = runner.invoke(pyaarlo_cli, ["--config", str(empty_cfg), "login", "--status"])
    assert result.exit_code == 1
    assert "Authentication Status:" in result.output
    assert "Session Token:            NOT FOUND" in result.output


def test_pyaarlo_config_show_and_set(tmp_path):
    runner = CliRunner()
    cfg_file = tmp_path / "config.json"

    # Set username
    res = runner.invoke(pyaarlo_cli, ["--config", str(cfg_file), "config", "set", "username", "alice@example.com"])
    assert res.exit_code == 0
    assert "alice@example.com" in res.output

    # Set tfa compound spec
    res = runner.invoke(pyaarlo_cli, ["--config", str(cfg_file), "config", "set", "tfa", "push"])
    assert res.exit_code == 0
    assert "tfa='push'" in res.output

    # Show config (masked)
    runner.invoke(pyaarlo_cli, ["--config", str(cfg_file), "config", "set", "password", "supersecret"])
    res = runner.invoke(pyaarlo_cli, ["--config", str(cfg_file), "config", "show"])
    assert res.exit_code == 0
    assert "********" in res.output
    assert "supersecret" not in res.output

    # Show config (unmasked)
    res_unmasked = runner.invoke(pyaarlo_cli, ["--config", str(cfg_file), "config", "show", "--unmask"])
    assert res_unmasked.exit_code == 0
    assert "supersecret" in res_unmasked.output


def test_pyaarlo_config_create_and_update_wizard(tmp_path):
    runner = CliRunner()
    cfg_file = tmp_path / "wizard_config.json"

    # 1. Create with push
    # Inputs: username, password, tfa_type (push), backend (auto), test auth? (no)
    user_inputs = "bob@example.com\nmypassword\npush\nauto\nn\n"
    res = runner.invoke(pyaarlo_cli, ["--config", str(cfg_file), "config", "create"], input=user_inputs)
    assert res.exit_code == 0
    assert cfg_file.is_file()

    from pyaarlo.cli.config import read_config_file
    saved = read_config_file(cfg_file)
    assert saved["username"] == "bob@example.com"
    assert saved["tfa"] == "push"

    # 2. Update to email:imap
    # Inputs:
    # username (enter to keep bob@example.com)
    # keep password? (y)
    # 2fa method (email)
    # email code entry (imap)
    # imap host (enter for default imap.example.com)
    # imap user (enter for bob@example.com)
    # imap pass (imappass)
    # backend (enter for auto)
    # test auth? (n)
    update_inputs = "\ny\nemail\nimap\n\n\nimappass\n\nn\n"
    res_up = runner.invoke(pyaarlo_cli, ["--config", str(cfg_file), "config", "update"], input=update_inputs)
    assert res_up.exit_code == 0

    saved_up = read_config_file(cfg_file)
    assert saved_up["username"] == "bob@example.com"
    assert saved_up["tfa"] == "email:imap"
    assert saved_up["tfa_password"] == "imappass"


