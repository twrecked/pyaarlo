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
)

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
