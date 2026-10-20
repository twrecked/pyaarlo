from unittest.mock import patch
from click.testing import CliRunner

from pyaarlo.cli.diagnostics import (
    DebugReportCapture,
    anonymize_text,
    decrypt_from_string,
    encrypt_to_string,
)
from pyaarlo.cli.main_cmd import cli as pyaarlo_cli


def test_anonymize_text_privacy():
    raw_log = "User test@arlo.com password secretpass device 4N71687207851 owner USR999"
    devices = [{"deviceId": "4N71687207851", "owner": {"ownerId": "USR999"}}]

    anon = anonymize_text(
        raw_log,
        devices=devices,
        username="test@arlo.com",
        password="secretpass",
    )

    assert "test@arlo.com" not in anon
    assert "secretpass" not in anon
    assert "4N71687207851" not in anon
    assert "USR999" not in anon
    assert "USERNAME" in anon
    assert "PASSWORD" in anon
    assert "DEV_01_ID" in anon
    assert "OWNER_01_ID" in anon


def test_debug_report_capture_lifecycle(tmp_path):
    report_file = tmp_path / "debug.enc"
    capture = DebugReportCapture(filename=str(report_file))

    capture.start(username="myuser@example.com", password="mypassword")

    import logging
    log = logging.getLogger("pyaarlo")
    log.debug("Step 1: connecting to test endpoint")
    log.info("Step 2: connected successfully")

    out_path = capture.finish(output_filename=str(report_file))
    assert out_path is not None
    assert report_file.is_file()

    content = report_file.read_text(encoding="utf-8")
    assert "-----BEGIN PYAARLO DUMP-----" in content
    assert "-----END PYAARLO DUMP-----" in content


def test_debug_report_with_exception(tmp_path):
    report_file = tmp_path / "crash_debug.enc"
    capture = DebugReportCapture(filename=str(report_file))
    capture.start()

    try:
        raise RuntimeError("simulated Arlo cloud failure")
    except RuntimeError as e:
        capture.finish(output_filename=str(report_file), exception=e)

    assert report_file.is_file()
    content = report_file.read_text(encoding="utf-8")
    assert "-----BEGIN PYAARLO DUMP-----" in content


def test_pyaarlo_cli_debug_report_flag(tmp_path):
    runner = CliRunner()
    report_file = tmp_path / "cli_report.enc"

    result = runner.invoke(pyaarlo_cli, ["--debug-report", str(report_file), "login", "--status"])
    assert report_file.is_file()
    assert "PyArlo Debug Report Generated" in result.output
