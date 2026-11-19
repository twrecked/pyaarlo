"""Stream setup regressions using in-memory state and a synthetic backend."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pyaarlo.camera import ArloCamera
from pyaarlo.core.storage import ArloStorage
from pyaarlo.location import ArloLocation


@pytest.fixture
def camera():
    arlo = MagicMock()
    arlo.cfg.state_file = None
    arlo.cfg.library_days = 7
    arlo.be.post = AsyncMock()
    arlo.st = ArloStorage(arlo.cfg, arlo.log)
    objs = MagicMock()
    objs.cameras = []
    objs.base_stations = []
    objs.locations = []
    return ArloCamera("Synthetic camera", arlo, objs, {
        "deviceId": "test-device", "deviceType": "camera",
        "parentId": "test-base", "userId": "test-user", "modelId": "TEST",
    })


@pytest.mark.parametrize("cached", [None, "rtsps://example.invalid/expired"])
@pytest.mark.parametrize("method,user", [("get_stream", "streaming"),
                                        ("get_stream_url", "remote")])
@pytest.mark.asyncio
async def test_concurrent_starts_wait_for_the_current_source(camera, cached, method, user):
    entered, release, second_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    camera._stream_url = cached

    async def response(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"url": "rtsp://example.invalid/current"}

    async def second_request():
        second_entered.set()
        return await camera.start_snapshot_stream()

    camera._core.be.post.side_effect = response
    first_task = asyncio.create_task(getattr(camera, method)())
    await entered.wait()

    second_task = asyncio.create_task(second_request())
    await second_entered.wait()

    # The second request must wait for the first to complete
    assert not first_task.done()
    assert not second_task.done()

    release.set()
    first_result = await first_task
    second_result = await second_task

    assert first_result == "rtsps://example.invalid/current"
    assert second_result == "rtsps://example.invalid/current"
    assert camera._core.be.post.call_count == 1
    assert camera.has_local_user(user)
    assert camera.has_local_user("snapshot")


@pytest.mark.parametrize("failure", [RuntimeError("synthetic failure"), {}])
@pytest.mark.asyncio
async def test_failed_start_can_retry_without_reusing_cached_source(camera, failure):
    camera._stream_url = "rtsps://example.invalid/expired"
    camera._core.be.post.side_effect = [failure, {"url": "rtsp://example.invalid/retry"}]
    with pytest.raises((RuntimeError, KeyError)):
        await camera.get_stream()
    assert not camera.has_local_user("streaming")
    assert await camera.get_stream() == "rtsps://example.invalid/retry"
    assert camera._core.be.post.call_count == 2


@pytest.mark.asyncio
async def test_empty_response_can_retry(camera):
    camera._core.be.post.side_effect = [None, {"url": "rtsp://example.invalid/retry"}]
    assert await camera.get_stream() is None
    assert await camera.get_stream() == "rtsps://example.invalid/retry"


@pytest.mark.asyncio
async def test_existing_stream_is_shared_without_another_backend_request(camera):
    camera._core.be.post.return_value = {"url": "rtsps://example.invalid/shared"}
    assert await camera.get_stream() == await camera.start_snapshot_stream()
    assert camera._core.be.post.call_count == 1


@pytest.mark.asyncio
async def test_idle_snapshot_does_not_start_stream(camera):
    camera._user_requests.add("snapshot")
    assert await camera.get_stream() is None
    camera._core.be.post.assert_not_called()


@pytest.mark.asyncio
async def test_backend_event_can_run_during_start(camera):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def response(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"url": "rtsp://example.invalid/current"}

    camera._core.be.post.side_effect = response
    task = asyncio.create_task(camera.get_stream())
    await entered.wait()

    # While start stream request is pending, non-stream state checks run freely
    assert not camera.is_streaming

    release.set()
    assert await task == "rtsps://example.invalid/current"


@pytest.mark.asyncio
async def test_failed_start_does_not_erase_a_remote_activity(camera):
    async def response(*args, **kwargs):
        # A remote activity can be reported while the local request is pending.
        camera._local_users.add("remote")
        camera._remote_users.add("recording")
        return None

    camera._core.be.post.side_effect = response
    assert await camera.get_stream() is None
    assert not camera.has_local_user("streaming")
    assert camera.has_local_user("remote")
    assert camera.has_remote_user("recording")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("camera_zone", "base_zone", "expected"),
    [
        ("Europe/Paris", "Europe/London", "Europe/Paris"),
        (" ", "Europe/London", "Europe/London"),
        (None, None, "America/New_York"),
    ],
)
async def test_start_recording_time_zone_priority(camera, camera_zone, base_zone, expected):
    camera._attrs["properties"] = {"olsonTimeZone": camera_zone}
    camera._objs.base_stations = [MagicMock(device_id=camera.parent_id, timezone=base_zone)]
    camera._local_users.add("recording")
    camera._stream_url = "rtsps://example.invalid/current"
    camera._core.be.post_with_status = AsyncMock(return_value=(200, {}))

    assert await camera.start_recording(30, fallback_timezone="America/New_York") == camera._stream_url
    assert camera._core.be.post_with_status.await_args.kwargs["params"]["olsonTimeZone"] == expected
    assert camera.has_user_request("recording")
    camera._core.tasks.run_in.assert_called_once_with(camera.stop_recording, 30)


@pytest.mark.asyncio
async def test_start_recording_without_a_time_zone_does_not_send_request(camera):
    camera._local_users.add("recording")
    camera._stream_url = "rtsps://example.invalid/current"
    camera._core.be.post_with_status = AsyncMock()

    assert await camera.start_recording(30) is None
    camera._core.be.post_with_status.assert_not_awaited()
    camera._core.tasks.run_in.assert_not_called()
    assert not camera.has_user_request("recording")


@pytest.mark.asyncio
async def test_rejected_start_recording_does_not_publish_state_and_can_retry(camera):
    camera._local_users.add("recording")
    camera._stream_url = "rtsps://example.invalid/current"
    camera._core.be.post_with_status = AsyncMock(side_effect=[(400, None), (200, {})])
    camera._save_and_do_callbacks = MagicMock()

    assert await camera.start_recording(30, fallback_timezone="UTC") is None
    assert not camera.has_user_request("recording")
    camera._save_and_do_callbacks.assert_not_called()
    camera._core.tasks.run_in.assert_not_called()

    assert await camera.start_recording(30, fallback_timezone="UTC") == camera._stream_url
    assert camera._core.be.post_with_status.await_count == 2
    camera._core.tasks.run_in.assert_called_once_with(camera.stop_recording, 30)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400])
async def test_stop_recording_reports_cloud_status(camera, status):
    camera._user_requests.add("recording")
    camera._core.be.post_with_status = AsyncMock(return_value=(status, {}))

    assert await camera.stop_recording(release_stream=False) is (status == 200)
    assert camera._core.be.post_with_status.await_args.kwargs["path"].endswith("/stopRecord")
    camera._core.tasks.run_in.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gateway_ids", "location_id", "duplicate", "expected"),
    [
        (["test-base"], None, False, "America/New_York"),
        (["owner_test-base"], None, False, "America/New_York"),
        (["test-device"], None, False, "America/New_York"),
        ([], "home", False, "America/New_York"),
        (["test-base"], "missing", False, "UTC"),
        (["unrelated-base"], None, False, "UTC"),
        (["test-base"], None, True, "UTC"),
    ],
)
async def test_recording_uses_only_an_associated_location_zone(
    camera, gateway_ids, location_id, duplicate, expected
):
    core, objs = camera._core, camera._objs
    camera._attrs["locationId"] = location_id
    objs.base_stations = [MagicMock(device_id="unrelated-base", timezone="Europe/Paris")]
    other = ArloLocation(core, objs, {
        "locationId": "other",
        "gatewayDeviceIds": [camera.parent_id if duplicate else "different-gateway"],
    })
    home = ArloLocation(core, objs, {"locationId": "home", "gatewayDeviceIds": gateway_ids})
    objs.locations = [other, home]
    core.be.get = AsyncMock(side_effect=[
        {"info": {"properties": {"olsonTimeZone": "Europe/London"}}},
        {"info": {"properties": {"olsonTimeZone": "America/New_York"}}},
        {},
        {"info": {"properties": {"olsonTimeZone": " "}}},
    ])
    await other.update_modes()
    await home.update_modes()
    await home.update_modes()
    await home.update_modes()
    assert home.timezone == "America/New_York"

    camera._local_users.add("recording")
    camera._stream_url = "rtsps://example.invalid/current"
    core.be.post_with_status = AsyncMock(return_value=(200, {}))
    fallback = "UTC" if expected == "UTC" else None
    assert await camera.start_recording(30, fallback_timezone=fallback) == camera._stream_url
    assert core.be.post_with_status.await_args.kwargs["params"]["olsonTimeZone"] == expected
