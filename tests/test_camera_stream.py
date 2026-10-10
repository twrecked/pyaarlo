"""Stream setup regressions using in-memory state and a synthetic backend."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock

import pytest

from pyaarlo.camera import ArloCamera
from pyaarlo.storage import ArloStorage


@pytest.fixture
def camera():
    arlo = MagicMock()
    arlo.cfg.state_file = None
    arlo.cfg.library_days = 7
    arlo.st = ArloStorage(arlo)
    return ArloCamera("Synthetic camera", arlo, {
        "deviceId": "test-device", "deviceType": "camera",
        "parentId": "test-base", "userId": "test-user", "modelId": "TEST",
    })


@pytest.mark.parametrize("cached", [None, "rtsps://example.invalid/expired"])
@pytest.mark.parametrize("method,user", [("get_stream", "streaming"),
                                        ("get_stream_url", "remote")])
def test_concurrent_starts_wait_for_the_current_source(camera, cached, method, user):
    entered, release, second_entered = Event(), Event(), Event()
    camera._stream_url = cached

    def response(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return {"url": "rtsp://example.invalid/current"}

    def second_request():
        second_entered.set()
        return camera.start_snapshot_stream()

    camera._arlo.be.post.side_effect = response
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(getattr(camera, method))
        try:
            assert entered.wait(2)
            second = pool.submit(second_request)
            assert second_entered.wait(2)
            # A pending backend request must not expose an empty or stale source.
            with pytest.raises(TimeoutError):
                second.result(timeout=0.1)
        finally:
            release.set()
        assert first.result(2) == "rtsps://example.invalid/current"
        assert second.result(2) == "rtsps://example.invalid/current"
    assert camera._arlo.be.post.call_count == 1
    assert camera.has_local_user(user)
    assert camera.has_local_user("snapshot")


@pytest.mark.parametrize("failure", [RuntimeError("synthetic failure"), {}])
def test_failed_start_can_retry_without_reusing_cached_source(camera, failure):
    camera._stream_url = "rtsps://example.invalid/expired"
    camera._arlo.be.post.side_effect = [failure, {"url": "rtsp://example.invalid/retry"}]
    with pytest.raises((RuntimeError, KeyError)):
        camera.get_stream()
    assert not camera.has_local_user("streaming")
    assert camera.get_stream() == "rtsps://example.invalid/retry"
    assert camera._arlo.be.post.call_count == 2


def test_empty_response_can_retry(camera):
    camera._arlo.be.post.side_effect = [None, {"url": "rtsp://example.invalid/retry"}]
    assert camera.get_stream() is None
    assert camera.get_stream() == "rtsps://example.invalid/retry"


def test_existing_stream_is_shared_without_another_backend_request(camera):
    camera._arlo.be.post.return_value = {"url": "rtsps://example.invalid/shared"}
    assert camera.get_stream() == camera.start_snapshot_stream()
    assert camera._arlo.be.post.call_count == 1


def test_idle_snapshot_does_not_start_stream(camera):
    camera._user_requests.add("snapshot")
    assert camera.get_stream() is None
    camera._arlo.be.post.assert_not_called()


def test_backend_event_can_acquire_activity_lock_during_start(camera):
    def response(*args, **kwargs):
        # The network backend may wait for an event handled by another thread.
        def event():
            acquired = camera._lock.acquire(timeout=0.5)
            if acquired:
                camera._lock.release()
            return acquired

        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(event).result(timeout=1)
        return {"url": "rtsp://example.invalid/current"}

    camera._arlo.be.post.side_effect = response
    assert camera.get_stream() == "rtsps://example.invalid/current"


def test_failed_start_does_not_erase_a_remote_activity(camera):
    def response(*args, **kwargs):
        # A remote activity can be reported while the local request is pending.
        camera._local_users.add("remote")
        camera._remote_users.add("recording")
        return None

    camera._arlo.be.post.side_effect = response
    assert camera.get_stream() is None
    assert not camera.has_local_user("streaming")
    assert camera.has_local_user("remote")
    assert camera.has_remote_user("recording")
