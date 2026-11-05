import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from pyaarlo.cli.main_cmd import cli
from pyaarlo.media import (
    ArloMediaDownloader,
    extract_base_dir_from_format,
    format_bytes,
    prune_media_files,
    scan_prunable_media,
)


def test_extract_base_dir_from_format():
    assert extract_base_dir_from_format("/config/media/${SN}/${Y}/${m}/${d}/${T}") == "/config/media"
    assert extract_base_dir_from_format("./media/${SN}/${Y}") == "./media"
    assert extract_base_dir_from_format("media/${SN}") == "media"
    assert extract_base_dir_from_format("${SN}/${T}") == "."
    assert extract_base_dir_from_format("") == ""
    assert extract_base_dir_from_format("/var/media/cam.mp4") == "/var/media"


def test_format_bytes():
    assert format_bytes(500) == "500 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1024 * 1024 * 5) == "5.0 MB"
    assert format_bytes(1024 * 1024 * 1024 * 2) == "2.0 GB"


def test_scan_and_prune_media(tmp_path):
    base = tmp_path / "media"
    cam_dir = base / "4N71687"
    old_dir = cam_dir / "2026" / "01" / "01"
    new_dir = cam_dir / "2026" / "03" / "01"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)

    old_mp4 = old_dir / "10-00-00.mp4"
    old_jpg = old_dir / "10-00-00.jpg"
    old_tmp = old_dir / "download.tmp"
    new_mp4 = new_dir / "12-00-00.mp4"
    non_media = cam_dir / "config.txt"

    for f in (old_mp4, old_jpg, old_tmp, new_mp4, non_media):
        f.write_bytes(b"x" * 1024)

    now = time.time()
    old_time = now - (45 * 86400)
    new_time = now - (5 * 86400)

    for f in (old_mp4, old_jpg, old_tmp, non_media):
        os.utime(f, (old_time, old_time))
    os.utime(new_mp4, (new_time, new_time))

    candidates = scan_prunable_media(base, retention_days=30, now=now)
    cand_paths = {c.path.resolve() for c in candidates}

    assert old_mp4.resolve() in cand_paths
    assert old_jpg.resolve() in cand_paths
    assert old_tmp.resolve() in cand_paths
    assert new_mp4.resolve() not in cand_paths
    assert non_media.resolve() not in cand_paths
    assert len(candidates) == 3

    # Prune
    deleted, freed, dirs = prune_media_files(candidates, remove_empty_dirs=True, root_dir=base)
    assert deleted == 3
    assert freed == 3072
    assert dirs == 2  # 01, 01 removed; 2026 retained because 03 is still inside
    assert not old_dir.exists()
    assert new_mp4.exists()
    assert non_media.exists()
    assert base.exists()


def test_camera_filter(tmp_path):
    base = tmp_path / "media"
    cam1 = base / "cam1"
    cam2 = base / "cam2"
    cam1.mkdir(parents=True)
    cam2.mkdir(parents=True)

    f1 = cam1 / "video.mp4"
    f2 = cam2 / "video.mp4"
    f1.write_bytes(b"test")
    f2.write_bytes(b"test")

    now = time.time()
    old_time = now - (40 * 86400)
    os.utime(f1, (old_time, old_time))
    os.utime(f2, (old_time, old_time))

    cands = scan_prunable_media(base, retention_days=30, camera_filter="cam1", now=now)
    assert len(cands) == 1
    assert cands[0].path.resolve() == f1.resolve()


@pytest.mark.asyncio
async def test_downloader_retention_scheduling():
    core = MagicMock()
    core.tasks = MagicMock()
    core.tasks.run_every.return_value = "task_123"

    downloader = ArloMediaDownloader(core, "/tmp/media/${SN}/${T}", retention_days=30)
    downloader.start()

    assert core.tasks.run_in.call_count == 1
    assert core.tasks.run_every.call_count == 1
    assert downloader._prune_task_id == "task_123"

    downloader.stop()
    core.tasks.cancel.assert_called_once_with("task_123")


def test_cli_media_prune_dry_run_and_execution(tmp_path):
    media_dir = tmp_path / "media"
    cam_dir = media_dir / "FrontDoor"
    cam_dir.mkdir(parents=True)

    old_file = cam_dir / "old_clip.mp4"
    old_file.write_bytes(b"A" * 2048)
    now = time.time()
    old_time = now - (40 * 86400)
    os.utime(old_file, (old_time, old_time))

    runner = CliRunner()

    # Dry-run
    res_dry = runner.invoke(
        cli,
        ["media", "prune", "--dir", str(media_dir), "--days", "30", "--dry-run"],
    )
    assert res_dry.exit_code == 0
    assert "old_clip.mp4" in res_dry.output
    assert "Dry run: No files were deleted." in res_dry.output
    assert old_file.exists()

    # Real run with --yes
    res_run = runner.invoke(
        cli,
        ["media", "prune", "--dir", str(media_dir), "--days", "30", "--yes"],
    )
    assert res_run.exit_code == 0
    assert "Deleted 1 file(s)" in res_run.output
    assert not old_file.exists()
