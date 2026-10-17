from pyaarlo.cli.targets import (
    match_device,
    match_location,
    parse_targets,
    resolve_devices,
    resolve_location,
)


def test_parse_targets():
    # Split by comma and arguments, strip whitespace
    parsed = parse_targets(["garage light, porch light", "driveway", "backyard, patio"])
    assert parsed == ["garage light", "porch light", "driveway", "backyard", "patio"]

    # Deduplicate and ignore empty
    parsed = parse_targets(["garage light", "", "garage light, ", " "])
    assert parsed == ["garage light"]


def test_match_device_dict():
    dev = {"id": "12345ABC", "name": "Garage Light", "serial_number": "SN999"}

    assert match_device(dev, "garage light") is True
    assert match_device(dev, "GARAGE LIGHT") is True
    assert match_device(dev, "12345abc") is True
    assert match_device(dev, "sn999") is True
    assert match_device(dev, "kitchen") is False


class MockDevice:
    def __init__(self, name: str, device_id: str, serial_number: str):
        self.name = name
        self.device_id = device_id
        self.serial_number = serial_number


def test_resolve_devices():
    d1 = MockDevice("Garage Light", "DEV1", "SN1")
    d2 = MockDevice("Porch Light", "DEV2", "SN2")
    d3 = MockDevice("Driveway", "DEV3", "SN3")

    candidates = [d1, d2, d3]
    targets = ["garage light", "DEV2", "unknown device"]

    matched, missing = resolve_devices(candidates, targets)
    assert matched == [d1, d2]
    assert missing == ["unknown device"]


def test_resolve_location():
    loc1 = {"id": "LOC1", "name": "Primary Home"}
    loc2 = {"id": "LOC2", "name": "Cabin"}

    # Multiple locations: target required
    assert resolve_location([loc1, loc2], None) is None
    assert resolve_location([loc1, loc2], "Primary Home") == loc1
    assert resolve_location([loc1, loc2], "loc2") == loc2
    assert resolve_location([loc1, loc2], "Office") is None

    # Single location: defaults to that location when None target passed
    assert resolve_location([loc1], None) == loc1
