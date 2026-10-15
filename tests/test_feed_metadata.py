from inspect import signature
import pytest

from pyaarlo import FeedMetadataError, PyArlo


class FakeBackend(object):
    def __init__(self, response=None, http_status=200):
        self.response = response
        self.http_status = http_status
        self.posts = []

    async def post_with_status(self, path, params, raw=False):
        self.posts.append((path, params, raw))
        return self.http_status, self.response


@pytest.mark.asyncio
async def test_feed_metadata_posts_request_and_returns_data():
    data = {
        "groupByEvents": {
            "event-key": [
                {
                    "device-key": [
                        {
                            "feedId": "feed-id",
                            "name": "video-id",
                            "deviceId": "device-id",
                            "harlem": [
                                {
                                    "shortCaption": "Animal crosses yard",
                                    "aiDigest": [
                                        {
                                            "sectionName": "Generic Description",
                                            "content": "Animal crosses yard.",
                                        }
                                    ],
                                    "highlight": False,
                                    "modelName": "gemini",
                                }
                            ],
                        }
                    ]
                }
            ]
        },
        "nextPage": "next-page",
    }
    backend = FakeBackend({"meta": {"code": 200}, "data": data})
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    metadata = await arlo.feed_metadata(
        "owner-id",
        "location-id",
        "20260524",
        limit=25,
        group_by="type",
        next_page="previous-page",
        asc=True,
    )

    assert metadata is data
    assert backend.posts == [
        (
            "/hmsfeeds/users/owner-id/location-id/metadata",
            {
                "asc": True,
                "fromDate": "20260524",
                "limit": 25,
                "groupBy": "type",
                "nextPage": "previous-page",
            },
            True,
        )
    ]


@pytest.mark.asyncio
async def test_feed_metadata_uses_feed_defaults():
    backend = FakeBackend({"meta": {"code": 200}, "data": {}})
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    metadata = await arlo.feed_metadata("owner-id", "location-id", "20260524")

    assert metadata == {}
    assert backend.posts[0] == (
        "/hmsfeeds/users/owner-id/location-id/metadata",
        {
            "asc": False,
            "fromDate": "20260524",
            "limit": 200,
            "groupBy": "events",
        },
        True,
    )


@pytest.mark.asyncio
async def test_feed_metadata_returns_data_when_meta_has_no_code():
    data = {"groupByEvents": {}}
    backend = FakeBackend({"meta": {}, "data": data})
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    metadata = await arlo.feed_metadata("owner-id", "location-id", "20260524")

    assert metadata is data


@pytest.mark.asyncio
async def test_feed_metadata_raises_for_http_failure():
    backend = FakeBackend(None, http_status=429)
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    with pytest.raises(FeedMetadataError) as ctx:
        await arlo.feed_metadata("owner-id", "location-id", "20260524")

    assert ctx.value.http_status == 429
    assert ctx.value.meta_code is None
    assert ctx.value.response_type is None
    assert "http_status=429" in str(ctx.value)


@pytest.mark.asyncio
async def test_feed_metadata_raises_for_meta_error():
    backend = FakeBackend(
        {
            "meta": {
                "code": 400,
                "error": 9261,
                "message": "temporarily unavailable",
            }
        }
    )
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    with pytest.raises(FeedMetadataError) as ctx:
        await arlo.feed_metadata("owner-id", "location-id", "20260524")

    assert ctx.value.http_status == 200
    assert ctx.value.response_type == "dict"
    assert ctx.value.response_keys == ("meta",)
    assert ctx.value.meta_code == 400
    assert ctx.value.meta_error == 9261
    assert "response_keys=meta" in str(ctx.value)


@pytest.mark.asyncio
async def test_feed_metadata_raises_for_no_usable_response():
    backend = FakeBackend("not-json")
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    with pytest.raises(FeedMetadataError) as ctx:
        await arlo.feed_metadata("owner-id", "location-id", "20260524")

    assert ctx.value.http_status == 200
    assert ctx.value.response_type == "str"
    assert ctx.value.meta_code is None


@pytest.mark.asyncio
async def test_feed_metadata_raises_for_missing_data():
    backend = FakeBackend({"meta": {"code": 200}})
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    with pytest.raises(FeedMetadataError) as ctx:
        await arlo.feed_metadata("owner-id", "location-id", "20260524")

    assert ctx.value.http_status == 200
    assert ctx.value.response_type == "dict"
    assert ctx.value.response_keys == ("meta",)
    assert ctx.value.meta_code == 200


@pytest.mark.asyncio
async def test_feed_metadata_raises_for_non_dict_data():
    backend = FakeBackend({"meta": {"code": 200}, "data": []})
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    with pytest.raises(FeedMetadataError) as ctx:
        await arlo.feed_metadata("owner-id", "location-id", "20260524")

    assert ctx.value.http_status == 200
    assert ctx.value.response_type == "dict"
    assert ctx.value.response_keys == ("data", "meta")
    assert ctx.value.meta_code == 200


@pytest.mark.asyncio
async def test_feed_items_flattens_group_by_events():
    harlem = [
        {
            "shortCaption": "Animal crosses yard",
            "modelName": "gemini",
        }
    ]
    first_item = {
        "feedId": "feed-id-1",
        "name": "video-id-1",
        "deviceId": "device-id-1",
        "harlem": harlem,
    }
    second_item = {
        "feedId": "feed-id-2",
        "name": "video-id-2",
        "deviceId": "device-id-2",
    }
    third_item = {
        "feedId": "feed-id-3",
        "name": "video-id-3",
        "deviceId": "device-id-3",
    }
    data = {
        "groupByEvents": {
            "event-key-1": [
                {
                    "device-key-1": [
                        first_item,
                        second_item,
                    ],
                    "device-key-2": [
                        third_item,
                    ],
                }
            ],
        },
        "nextPage": "next-page",
    }
    backend = FakeBackend({"meta": {"code": 200}, "data": data})
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    items = await arlo.feed_items(
        "owner-id",
        "location-id",
        "20260524",
        limit=25,
        next_page="previous-page",
    )

    assert items == [first_item, second_item, third_item]
    assert items[0] is first_item
    assert items[1] is second_item
    assert items[2] is third_item
    assert items[0]["harlem"] is harlem
    assert backend.posts == [
        (
            "/hmsfeeds/users/owner-id/location-id/metadata",
            {
                "asc": False,
                "fromDate": "20260524",
                "limit": 25,
                "groupBy": "events",
                "nextPage": "previous-page",
            },
            True,
        )
    ]


@pytest.mark.asyncio
async def test_feed_items_always_requests_event_grouping():
    assert "group_by" not in signature(PyArlo.feed_items).parameters

    backend = FakeBackend({"meta": {"code": 200}, "data": {}})
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    await arlo.feed_items("owner-id", "location-id", "20260524")

    assert backend.posts[0][1]["groupBy"] == "events"


@pytest.mark.asyncio
async def test_feed_items_propagates_metadata_errors():
    backend = FakeBackend(None, http_status=500)
    arlo = PyArlo.__new__(PyArlo)
    arlo._be = backend

    with pytest.raises(FeedMetadataError) as ctx:
        await arlo.feed_items("owner-id", "location-id", "20260524")

    assert ctx.value.http_status == 500


def test_feed_items_returns_empty_list_for_unexpected_metadata():
    arlo = PyArlo.__new__(PyArlo)

    assert arlo._feed_items_from_metadata(None) == []
    assert arlo._feed_items_from_metadata({}) == []
    assert arlo._feed_items_from_metadata({"groupByEvents": []}) == []
