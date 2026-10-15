"""Media refresh recovery with a synthetic backend and no downloader thread."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pyaarlo.media import ArloMediaLibrary


@pytest.fixture
def library(monkeypatch):
    monkeypatch.setattr("pyaarlo.media.ArloMediaDownloader", MagicMock())
    arlo = MagicMock()
    arlo.cfg.save_media_to = ""
    arlo.be.post = AsyncMock(return_value=[])
    library = ArloMediaLibrary(arlo)
    library._videos = [object()]
    library._video_keys = ["existing-video"]
    library._snapshots = {"camera": object()}
    library._count = 7
    return library


@pytest.mark.asyncio
async def test_failed_refresh_preserves_cache_and_pending_callbacks(library):
    callback = MagicMock()
    library.queue_update(callback)
    before = (library._videos, library._video_keys, library._snapshots)
    library._core.be.post.return_value = None

    await library.update()

    assert library.count == 7
    assert all(a is b for a, b in zip(before, (
        library._videos, library._video_keys, library._snapshots
    )))
    callback.assert_not_called()
    assert library._load_cbs_ == [callback]
    library._downloader.queue_download.assert_not_called()
    library._core.log.warning.assert_called_once_with("error updating the image library")


@pytest.mark.asyncio
async def test_new_event_requeues_after_each_failed_refresh(library):
    callbacks = [MagicMock() for _ in range(3)]
    library._core.be.post.return_value = None
    for index, callback in enumerate(callbacks, 1):
        library.queue_update(callback)
        assert library._core.tasks.run_in.call_count == index
        await library.update()
    assert library._load_cbs_ == callbacks
    assert library.count == 7


@pytest.mark.parametrize("has_video", [False, True])
@pytest.mark.asyncio
async def test_success_after_failure_notifies_waiters_and_allows_next_refresh(library, has_video):
    first, second, third = MagicMock(), MagicMock(), MagicMock()
    library.queue_update(first)
    library._core.be.post.return_value = None
    await library.update()

    camera = SimpleNamespace(device_id="camera", name="Test", base_station=None)
    library._core.lookup_camera_by_id.return_value = camera
    video = {"deviceId": "camera", "contentType": "video/mp4",
             "utcCreatedDate": 1700000000000, "name": "new-video"}
    library._core.be.post.return_value = [video] if has_video else []
    library.queue_update(second)
    await library.update()

    first.assert_called_once_with()
    second.assert_called_once_with()
    assert library.count == 8
    assert len(library.videos[1]) == (2 if has_video else 1)
    assert library._load_cbs_ == []
    assert library._downloader.queue_download.call_count == int(has_video)
    library.queue_update(third)
    assert library._core.tasks.run_in.call_count == 3


@pytest.mark.asyncio
async def test_successful_empty_refresh_is_not_a_failed_response(library):
    first, second = MagicMock(), MagicMock()
    library.queue_update(first)
    library.queue_update(second)
    library._core.tasks.run_in.assert_called_once()
    library._core.be.post.return_value = []

    await library.update()

    first.assert_called_once_with()
    second.assert_called_once_with()
    assert library.count == 8
    assert len(library.videos[1]) == 1
    library._core.log.warning.assert_not_called()
