import pytest

from pyaarlo.core.backend import ArloBackEnd, _flatten_intelligence_events


class _Location:
    def __init__(self, location_id):
        self.id = location_id


class _Config:
    host = "https://myapi.arlo.com"


class _Arlo:
    cfg = _Config()
    locations = [_Location("location-a"), _Location("location-b")]


def test_flatten_accepts_dictionary_shaped_group():
    events = _flatten_intelligence_events({
        "event-1": {
            "camera-1": {
                "feedId": "feed-1",
                "utcCreatedDate": 1787162940000,
                "harlem": [{"shortCaption": "Person"}],
            }
        }
    }, "location-a")
    assert len(events) == 1
    assert events[0]["eventId"] == "event-1"
    assert events[0]["locationId"] == "location-a"
    assert events[0]["deviceId"] == "camera-1"


@pytest.mark.asyncio
async def test_get_intelligence_events_flattens_all_locations():
    backend = ArloBackEnd.__new__(ArloBackEnd)
    backend._arlo = _Arlo()
    backend._web_id = "T84AM-unknown"
    calls = []

    async def request(path, **kwargs):
        calls.append((path, kwargs))
        location_id = path.split("/")[3]
        return {
            "success": True,
            "data": {
                "groupByEvents": {
                    "event-1": [{"camera-1": [[{"harlem": [{"shortCaption": "Person", "aiDigest": [{"content": "A person is visible."}]}]}]]}]
                } if location_id == "location-a" else {}
            }
        }

    backend._request = request
    events = await backend.get_intelligence_events("20260828", limit=25)

    assert len(events) == 1
    assert events[0]["eventId"] == "event-1"
    assert events[0]["locationId"] == "location-a"
    assert events[0]["deviceId"] == "camera-1"
    assert len(calls) == 2
    assert calls[1][0] == "/users/T84AM-unknown/location-b/metadata"
    assert calls[0][0] == "/users/T84AM-unknown/location-a/metadata"
    assert calls[0][1]["method"] == "POST"
    assert calls[0][1]["params"]["fromDate"] == "20260828"
    assert calls[0][1]["params"]["limit"] == 25
