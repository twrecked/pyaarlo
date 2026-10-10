"""Media refresh recovery with a synthetic backend and no downloader thread."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pyaarlo.media import ArloMediaLibrary


@pytest.fixture
def library(monkeypatch):
    monkeypatch.setattr("pyaarlo.media.ArloMediaDownloader", MagicMock())
    arlo = MagicMock()
    arlo.cfg.save_media_to = ""
    library = ArloMediaLibrary(arlo)
    library._videos = [object()]
    library._video_keys = ["existing-video"]
    library._snapshots = {"camera": object()}
    library._count = 7
    return library


def test_failed_refresh_preserves_cache_and_pending_callbacks(library):
    callback = MagicMock()
    library.queue_update(callback)
    before = (library._videos, library._video_keys, library._snapshots)
    library._arlo.be.post.return_value = None

    library.update()

    assert library.count == 7
    assert all(a is b for a, b in zip(before, (
        library._videos, library._video_keys, library._snapshots
    )))
    callback.assert_not_called()
    assert library._load_cbs_ == [callback]
    library._downloader.queue_download.assert_not_called()
    library._arlo.warning.assert_called_once_with("error updating the image library")


def test_new_event_requeues_after_each_failed_refresh(library):
    callbacks = [MagicMock() for _ in range(3)]
    library._arlo.be.post.return_value = None
    for index, callback in enumerate(callbacks, 1):
        library.queue_update(callback)
        assert library._arlo.bg.run_low_in.call_count == index
        library.update()
    assert library._load_cbs_ == callbacks
    assert library.count == 7


@pytest.mark.parametrize("has_video", [False, True])
def test_success_after_failure_notifies_waiters_and_allows_next_refresh(library, has_video):
    first, second, third = MagicMock(), MagicMock(), MagicMock()
    library.queue_update(first)
    library._arlo.be.post.return_value = None
    library.update()

    camera = SimpleNamespace(device_id="camera", name="Test", base_station=None)
    library._arlo.lookup_camera_by_id.return_value = camera
    video = {"deviceId": "camera", "contentType": "video/mp4",
             "utcCreatedDate": 1700000000000, "name": "new-video"}
    library._arlo.be.post.return_value = [video] if has_video else []
    library.queue_update(second)
    library.update()

    first.assert_called_once_with()
    second.assert_called_once_with()
    assert library.count == 8
    assert len(library.videos[1]) == (2 if has_video else 1)
    assert library._load_cbs_ == []
    assert library._downloader.queue_download.call_count == int(has_video)
    library.queue_update(third)
    assert library._arlo.bg.run_low_in.call_count == 3


def test_successful_empty_refresh_is_not_a_failed_response(library):
    first, second = MagicMock(), MagicMock()
    library.queue_update(first)
    library.queue_update(second)
    library._arlo.bg.run_low_in.assert_called_once()
    library._arlo.be.post.return_value = []

    library.update()

    first.assert_called_once_with()
    second.assert_called_once_with()
    assert library.count == 8
    assert len(library.videos[1]) == 1
    library._arlo.warning.assert_not_called()
