import unittest

from pyaarlo.backend import ArloBackEnd


class _Location:
    def __init__(self, location_id):
        self.id = location_id


class _Config:
    host = "https://myapi.arlo.com"


class _Arlo:
    cfg = _Config()
    locations = [_Location("location-a"), _Location("location-b")]


class IntelligenceEventsTests(unittest.TestCase):
    def test_get_intelligence_events_flattens_all_locations(self):
        backend = ArloBackEnd.__new__(ArloBackEnd)
        backend._arlo = _Arlo()
        backend._web_id = "T84AM-unknown"
        calls = []

        def request(path, **kwargs):
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
        events = backend.get_intelligence_events("20260828", limit=25)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["eventId"], "event-1")
        self.assertEqual(events[0]["locationId"], "location-a")
        self.assertEqual(events[0]["deviceId"], "camera-1")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][0], "/users/T84AM-unknown/location-b/metadata")
        self.assertEqual(calls[0][0], "/users/T84AM-unknown/location-a/metadata")
        self.assertEqual(calls[0][1]["method"], "POST")
        self.assertEqual(calls[0][1]["params"]["fromDate"], "20260828")
        self.assertEqual(calls[0][1]["params"]["limit"], 25)


if __name__ == "__main__":
    unittest.main()
