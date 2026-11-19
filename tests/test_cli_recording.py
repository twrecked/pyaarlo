"""Cloud recording CLI tests with a synthetic stream and Arlo camera."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import click
import pytest
from click.testing import CliRunner

from pyaarlo.cli import main_cmd, recording


SOURCE = "rtsps://example.invalid/stream?token=secret"


def test_record_command_uses_ha_zone_and_background_events(monkeypatch, tmp_path):
    storage = tmp_path / ".storage"
    storage.mkdir()
    (storage / "core.config").write_text(json.dumps({"data": {"time_zone": "America/New_York"}}))
    (storage / "core.config_entries").write_text(json.dumps({"data": {"entries": [
        {"domain": "aarlo", "data": {"username": "demo", "password": "demo"}}
    ]}}))
    camera = SimpleNamespace(name="Test 03", device_id="device-id")
    arlo = SimpleNamespace(cameras=[camera], stop=AsyncMock())
    create = AsyncMock(return_value=arlo)
    record = AsyncMock()
    monkeypatch.setattr(main_cmd.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(main_cmd, "create_pyarlo", create)
    monkeypatch.setattr(main_cmd, "record_camera", record)
    result = CliRunner().invoke(main_cmd.cli, [
        "--hass-dir", str(tmp_path), "camera", "record", "Test 03", "--duration", "5",
    ])
    assert result.exit_code == 0, result.output
    assert create.await_args.kwargs["start_background"] is True
    record.assert_awaited_once_with(camera, "/usr/bin/ffmpeg", 5, "America/New_York")
    arlo.stop.assert_awaited_once_with(logout=False)


def test_record_rejects_bad_options_before_opening_an_arlo_session(monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(main_cmd, "create_pyarlo", create)
    monkeypatch.setattr(main_cmd.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    for option in (["--duration", "0"], ["--timezone", "-05:00"]):
        result = CliRunner().invoke(main_cmd.cli, ["camera", "record", "Test 03", *option])
        assert result.exit_code == 2, result.output
    create.assert_not_awaited()


@pytest.fixture
def camera():
    return SimpleNamespace(
        name="Test 03", timezone=None,
        start_recording_stream=AsyncMock(return_value=SOURCE),
        wait_for_user_stream=AsyncMock(return_value=True),
        start_recording=AsyncMock(return_value=SOURCE),
        stop_recording=AsyncMock(return_value=True),
        stop_recording_stream=AsyncMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "start", "stop", "not_ready", "early_exit"])
async def test_recording_checks_cloud_results_and_cleans_up(camera, monkeypatch, capsys, failure):
    done = asyncio.Event()
    process = SimpleNamespace(returncode=None)

    async def wait():
        await done.wait()
        return process.returncode

    def exit_process(code):
        process.returncode = code
        done.set()

    process.wait = AsyncMock(side_effect=wait)
    process.kill = MagicMock(side_effect=lambda: exit_process(-9))
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(recording.asyncio, "create_subprocess_exec", spawn)
    if failure == "start":
        camera.start_recording.return_value = None
    if failure == "stop":
        camera.stop_recording.return_value = False
    if failure == "not_ready":
        camera.wait_for_user_stream.return_value = False
    if failure == "early_exit":
        exit_process(1)

    if failure is None:
        await recording.record_camera(camera, "ffmpeg", 0, "UTC")
        assert "Arlo accepted stop" in capsys.readouterr().out
    else:
        with pytest.raises(click.ClickException):
            await recording.record_camera(camera, "ffmpeg", 0, "UTC")

    args = spawn.await_args.args
    assert args[args.index("-i") + 1] == SOURCE
    assert args[-3:] == ("-f", "null", "-")
    if failure in {"not_ready", "early_exit"}:
        camera.start_recording.assert_not_awaited()
    else:
        camera.start_recording.assert_awaited_once_with(fallback_timezone="UTC")
    if failure in {None, "stop"}:
        camera.stop_recording.assert_awaited_once_with(release_stream=False)
    else:
        camera.stop_recording.assert_not_awaited()
    camera.stop_recording_stream.assert_awaited_once()
    assert process.returncode is not None
