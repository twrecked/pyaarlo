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
    assert "login" in result.output
    assert "cache" in result.output
    assert "light" in result.output
    assert "location" in result.output
    assert "camera" in result.output
    assert "list" in result.output


def test_pyaarlo_login_help():
    runner = CliRunner()
    result = runner.invoke(pyaarlo_cli, ["login", "--help"])
    assert result.exit_code == 0
    assert "--tfa" in result.output
    assert "--tfa-type" in result.output
    assert "--tfa-source" in result.output
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
    assert "XXXXXXXXX" in anon
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
    # Test with no session
    result = runner.invoke(pyaarlo_cli, ["login", "--status"])
    assert result.exit_code == 1
    assert "Authentication Status:" in result.output
    assert "Session Token:            NOT FOUND" in result.output

