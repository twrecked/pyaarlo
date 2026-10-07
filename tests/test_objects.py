import pytest
import asyncio
from tests.devices import *
from pyaarlo import (
    ArloBackEnd,
    ArloTaskManager,
    ArloBaseStation,
    ArloCfg,
    ArloCore,
    ArloDoorBell,
    ArloLogger,
    ArloObjects,
    ArloStorage,
    PyArlo,
)
from pyaarlo.camera import ArloCamera
from pyaarlo.types import ArloTypes

@pytest.fixture
def core_factory():
    """Returns a factory function to create a core object within an active loop."""
    def _create():
        log = ArloLogger(False)
        cfg = ArloCfg(log, username="testing123")
        core_obj = ArloCore()
        core_obj.log = log
        core_obj.cfg = cfg
        core_obj.tasks = ArloTaskManager(log)
        core_obj.st = ArloStorage(cfg, log)
        core_obj.be = ArloBackEnd(cfg, log, core_obj.tasks)
        return core_obj
    return _create

@pytest.fixture
def objs():
    return ArloObjects()

@pytest.mark.asyncio
async def test_doorbell_01(core_factory, objs):
    core = core_factory()
    # Build minimal globals.
    objs.base_stations = [ArloBaseStation("Test Door Bell", core, objs, DOOR_BELL_01)]

    # Create and test device.
    db = ArloDoorBell("Door Bell 01", core, objs, DOOR_BELL_01)

    assert db.name == "Door Bell 01"
    assert db.device_id == "DOOR-BELL-01-ID"
    assert db.device_type == "doorbell"
    assert db.entity_id == "door_bell_01"
    assert db.unique_id == "DOOR-BELL-01-UNIQUE-ID"

    assert db.resource_id == "doorbells/DOOR-BELL-01-ID"
    assert db.resource_type == "doorbells"
    assert db.serial_number == "DOOR-BELL-01-ID"
    assert db.model_id == "AVD2001A"
    assert db.hw_version == "AVD2001Aer1.4"
    assert db.timezone == "America/Bogota"
    assert db.user_id == "USER-ID"
    assert db.user_role == "ADMIN"
    assert db.xcloud_id == "DOOR-BELL-01-XCLOUD-ID"
    assert db.is_own_parent is True
    assert db.is_unavailable is False
    assert db.battery_level == 51
    assert db.battery_tech == "Rechargeable"
    assert db.has_batteries is True
    assert db.charger_type == "None"
    assert db.has_charger is False
    assert db.is_charging is False
    assert db.is_charger_only is False
    assert db.is_corded is False
    assert db.using_wifi is True
    assert db.signal_strength == 3

    assert db.too_cold is False
    assert db.state == "idle"

    assert db.is_video_doorbell is True
    assert db.is_silenced is False
    assert db.calls_are_silenced is True
    assert db.chimes_are_silenced is True
    assert db.siren_state == 'off'

    # Clear out globals.
    objs.base_stations = []

@pytest.mark.asyncio
async def test_doorbell_02(core_factory, objs):
    core = core_factory()
    # Build minimal globals.
    objs.base_stations = [ArloBaseStation("Rear Base Station", core, objs, BASE_STATION_02)]

    # Create and test device.
    db = ArloDoorBell("Door Bell 02", core, objs, DOOR_BELL_02)
    db.update_resources(DOOR_BELL_02_UPDATES)

    assert db.name == "Door Bell 02"
    assert db.device_id == "DOOR-BELL-02-ID"
    assert db.device_type == "doorbell"
    assert db.entity_id == "door_bell_02"
    assert db.unique_id == "DOOR-BELL-02-UNIQUE-ID"

    assert db.resource_id == "doorbells/DOOR-BELL-02-ID"
    assert db.resource_type == "doorbells"
    assert db.serial_number == "DOOR-BELL-02-ID"
    assert db.model_id == "AAD1001"
    assert db.hw_version is None
    assert db.timezone is None
    assert db.user_id == "USER-ID"
    assert db.user_role == "ADMIN"
    assert db.xcloud_id == "BASE-STATION-02-XCLOUD-ID"
    assert db.is_own_parent is False
    assert db.is_unavailable is False
    assert db.battery_level == 50
    assert db.battery_tech == "None"
    assert db.has_batteries is False
    assert db.charger_type == "None"
    assert db.has_charger is False
    assert db.is_charging is False
    assert db.is_charger_only is False
    assert db.is_corded is True
    assert db.using_wifi is False
    assert db.signal_strength == 3

    assert db.too_cold is False
    assert db.state == "idle"

    assert db.is_video_doorbell is False
    assert db.is_silenced is False
    assert db.calls_are_silenced is False
    assert db.chimes_are_silenced is False
    assert db.siren_state == 'off'

    # Clear out globals.
    objs.base_stations = []

@pytest.mark.asyncio
async def test_wired_floodlight_flw2001(core_factory, objs):
    core = core_factory()
    camera_device = {
        "deviceId": "FLOODLIGHT-01-ID",
        "deviceName": "Driveway Floodlight",
        "deviceType": "camera",
        "modelId": "FLW2001",
        "parentId": "FLOODLIGHT-01-ID",
        "uniqueId": "FLOODLIGHT-01-UID",
        "state": "provisioned",
        "properties": {
            "activityState": "idle",
            "batteryLevel": 100,
            "signalStrength": 4,
        },
    }
    cam = ArloCamera("Driveway Floodlight", core, objs, camera_device)
    assert cam.model_id == "FLW2001"
    assert ArloTypes.can_be_own_base_station("FLW2001") is True
    assert cam.has_capability("floodlight") is True
    assert cam.has_capability("sirenState") is True
    assert cam.siren_state == "off"

@pytest.mark.asyncio
async def test_extra_device_states_filtering(core_factory, objs):
    devices = [
        {"deviceId": "CAM-01", "deviceName": "Active Cam", "deviceType": "camera", "modelId": "VMC4040", "state": "provisioned"},
        {"deviceId": "CAM-02", "deviceName": "Deactivated Cam", "deviceType": "camera", "modelId": "VMC4040", "state": "deactivated"},
    ]

    # 1. Without extra_device_states: CAM-02 is skipped
    pyarlo_default = PyArlo.__new__(PyArlo)
    pyarlo_default._core = core_factory()
    pyarlo_default._devices = devices
    pyarlo_default._objs = ArloObjects()
    pyarlo_default.info = lambda *args: None
    pyarlo_default._build_objects()
    assert len(pyarlo_default._objs.cameras) == 1
    assert pyarlo_default._objs.cameras[0].name == "Active Cam"

    # 2. With extra_device_states=["deactivated"]: CAM-02 is accepted
    pyarlo_extra = PyArlo.__new__(PyArlo)
    pyarlo_extra._core = core_factory()
    pyarlo_extra._core.cfg = ArloCfg(pyarlo_extra._core.log, extra_device_states=["deactivated"])
    pyarlo_extra._devices = devices
    pyarlo_extra._objs = ArloObjects()
    pyarlo_extra.info = lambda *args: None
    pyarlo_extra._build_objects()
    assert len(pyarlo_extra._objs.cameras) == 2
