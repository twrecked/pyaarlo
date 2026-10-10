"""Behavioral contracts for refresh coalescing and recording deduplication."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pyaarlo.media import ArloMediaLibrary


@pytest.fixture
def library(monkeypatch):
    monkeypatch.setattr("pyaarlo.media.ArloMediaDownloader", MagicMock())
    arlo = MagicMock()
    arlo.cfg.save_media_to = ""
    arlo.cfg.library_days = 7
    arlo.be.post.return_value = []
    return ArloMediaLibrary(arlo)


def test_repeated_bound_callbacks_stay_bounded_during_outage(library):
    calls = []

    class Camera:
        def refresh(self):
            calls.append("refresh")

    camera = Camera()
    library._arlo.be.post.return_value = None
    for _ in range(20):
        for _ in range(50):
            # Each access creates a new bound method for the same subscriber.
            library.queue_update(camera.refresh)
        library.update()

    assert len(library._load_cbs_) == 1
    assert calls == []
    assert library._arlo.bg.run_low_in.call_count == 20
    library._arlo.be.post.return_value = []
    library.queue_update(camera.refresh)
    library.update()
    assert calls == ["refresh"]


def test_distinct_unhashable_callbacks_keep_first_seen_order(library):
    calls = []

    class Callback:
        __hash__ = None

        def __init__(self, name):
            self.name = name

        def __call__(self):
            calls.append(self.name)

    first, second = Callback("first"), Callback("second")
    for cb in [first, second, first, second]:
        library.queue_update(cb)
    library.update()
    assert calls == ["first", "second"]
    library._arlo.bg.run_low_in.assert_called_once()


def test_callback_can_queue_itself_for_the_next_refresh(library):
    calls = []

    def callback():
        calls.append(library.count)
        if len(calls) == 1:
            library.queue_update(callback)

    library.queue_update(callback)
    library.queue_update(callback)
    library.update()
    assert calls == [1]
    assert library._load_cbs_ == [callback]
    assert library._arlo.bg.run_low_in.call_count == 2
    library.update()
    assert calls == [1, 2]


def test_recording_order_and_deduplication_survive_load_and_refresh(library):
    camera = SimpleNamespace(device_id="test-camera", name="Test", base_station=None)
    library._arlo.lookup_camera_by_id.side_effect = (
        lambda device_id: camera if device_id == camera.device_id else None
    )

    def record(name, timestamp, device_id=camera.device_id):
        return {"deviceId": device_id, "contentType": "video/mp4",
                "utcCreatedDate": timestamp, "name": name}

    old = record("old", 1700000000000)
    first = record("first", 1700000002000)
    second = record("second", 1700000001000)
    library._arlo.be.post.return_value = [old]
    library.load()
    library._downloader.queue_download.reset_mock()
    library._arlo.be.post.return_value = [
        first, old, first, second, record("unknown", 1700000003000, "other")
    ]
    library.update()
    assert [video.id for video in library.videos[1]] == ["first", "second", "old"]
    assert library._downloader.queue_download.call_count == 2
    library.update()
    assert [video.id for video in library.videos[1]] == ["first", "second", "old"]
    assert library._downloader.queue_download.call_count == 2
