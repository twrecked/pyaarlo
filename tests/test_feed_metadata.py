from inspect import signature
from unittest import TestCase

from pyaarlo import FeedMetadataError, PyArlo


class FakeBackend(object):
    def __init__(self, response=None, http_status=200):
        self.response = response
        self.http_status = http_status
        self.posts = []

    def post_with_status(self, path, params, raw=False):
        self.posts.append((path, params, raw))
        return self.http_status, self.response


class TestFeedMetadata(TestCase):
    def test_feed_metadata_posts_request_and_returns_data(self):
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

        metadata = arlo.feed_metadata(
            "owner-id",
            "location-id",
            "20260524",
            limit=25,
            group_by="type",
            next_page="previous-page",
            asc=True,
        )

        self.assertIs(metadata, data)
        self.assertEqual(
            backend.posts,
            [
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
            ],
        )

    def test_feed_metadata_uses_feed_defaults(self):
        backend = FakeBackend({"meta": {"code": 200}, "data": {}})
        arlo = PyArlo.__new__(PyArlo)
        arlo._be = backend

        metadata = arlo.feed_metadata("owner-id", "location-id", "20260524")

        self.assertEqual(metadata, {})
        self.assertEqual(
            backend.posts[0],
            (
                "/hmsfeeds/users/owner-id/location-id/metadata",
                {
                    "asc": False,
                    "fromDate": "20260524",
                    "limit": 200,
                    "groupBy": "events",
                },
                True,
            ),
        )

    def test_feed_metadata_returns_data_when_meta_has_no_code(self):
        data = {"groupByEvents": {}}
        backend = FakeBackend({"meta": {}, "data": data})
        arlo = PyArlo.__new__(PyArlo)
        arlo._be = backend

        metadata = arlo.feed_metadata("owner-id", "location-id", "20260524")

        self.assertIs(metadata, data)

    def test_feed_metadata_raises_for_http_failure(self):
        backend = FakeBackend(None, http_status=429)
        arlo = PyArlo.__new__(PyArlo)
        arlo._be = backend

        with self.assertRaises(FeedMetadataError) as ctx:
            arlo.feed_metadata("owner-id", "location-id", "20260524")

        self.assertEqual(ctx.exception.http_status, 429)
        self.assertIsNone(ctx.exception.meta_code)
        self.assertIsNone(ctx.exception.response_type)
        self.assertIn("http_status=429", str(ctx.exception))

    def test_feed_metadata_raises_for_meta_error(self):
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

        with self.assertRaises(FeedMetadataError) as ctx:
            arlo.feed_metadata("owner-id", "location-id", "20260524")

        self.assertEqual(ctx.exception.http_status, 200)
        self.assertEqual(ctx.exception.response_type, "dict")
        self.assertEqual(ctx.exception.response_keys, ("meta",))
        self.assertEqual(ctx.exception.meta_code, 400)
        self.assertEqual(ctx.exception.meta_error, 9261)
        self.assertIn("response_keys=meta", str(ctx.exception))

    def test_feed_metadata_raises_for_no_usable_response(self):
        backend = FakeBackend("not-json")
        arlo = PyArlo.__new__(PyArlo)
        arlo._be = backend

        with self.assertRaises(FeedMetadataError) as ctx:
            arlo.feed_metadata("owner-id", "location-id", "20260524")

        self.assertEqual(ctx.exception.http_status, 200)
        self.assertEqual(ctx.exception.response_type, "str")
        self.assertIsNone(ctx.exception.meta_code)

    def test_feed_metadata_raises_for_missing_data(self):
        backend = FakeBackend({"meta": {"code": 200}})
        arlo = PyArlo.__new__(PyArlo)
        arlo._be = backend

        with self.assertRaises(FeedMetadataError) as ctx:
            arlo.feed_metadata("owner-id", "location-id", "20260524")

        self.assertEqual(ctx.exception.http_status, 200)
        self.assertEqual(ctx.exception.response_type, "dict")
        self.assertEqual(ctx.exception.response_keys, ("meta",))
        self.assertEqual(ctx.exception.meta_code, 200)

    def test_feed_metadata_raises_for_non_dict_data(self):
        backend = FakeBackend({"meta": {"code": 200}, "data": []})
        arlo = PyArlo.__new__(PyArlo)
        arlo._be = backend

        with self.assertRaises(FeedMetadataError) as ctx:
            arlo.feed_metadata("owner-id", "location-id", "20260524")

        self.assertEqual(ctx.exception.http_status, 200)
        self.assertEqual(ctx.exception.response_type, "dict")
        self.assertEqual(ctx.exception.response_keys, ("data", "meta"))
        self.assertEqual(ctx.exception.meta_code, 200)

    def test_feed_items_flattens_group_by_events(self):
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

        items = arlo.feed_items(
            "owner-id",
            "location-id",
            "20260524",
            limit=25,
            next_page="previous-page",
        )

        self.assertEqual(items, [first_item, second_item, third_item])
        self.assertIs(items[0], first_item)
        self.assertIs(items[1], second_item)
        self.assertIs(items[2], third_item)
        self.assertIs(items[0]["harlem"], harlem)
        self.assertEqual(
            backend.posts,
            [
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
            ],
        )

    def test_feed_items_always_requests_event_grouping(self):
        self.assertNotIn("group_by", signature(PyArlo.feed_items).parameters)

        backend = FakeBackend({"meta": {"code": 200}, "data": {}})
        arlo = PyArlo.__new__(PyArlo)
        arlo._be = backend

        arlo.feed_items("owner-id", "location-id", "20260524")

        self.assertEqual(backend.posts[0][1]["groupBy"], "events")

    def test_feed_items_propagates_metadata_errors(self):
        backend = FakeBackend(None, http_status=500)
        arlo = PyArlo.__new__(PyArlo)
        arlo._be = backend

        with self.assertRaises(FeedMetadataError) as ctx:
            arlo.feed_items("owner-id", "location-id", "20260524")

        self.assertEqual(ctx.exception.http_status, 500)

    def test_feed_items_returns_empty_list_for_unexpected_metadata(self):
        arlo = PyArlo.__new__(PyArlo)

        self.assertEqual(arlo._feed_items_from_metadata(None), [])
        self.assertEqual(arlo._feed_items_from_metadata({}), [])
        self.assertEqual(arlo._feed_items_from_metadata({"groupByEvents": []}), [])
