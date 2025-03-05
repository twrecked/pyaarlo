from unittest import TestCase

from tests.devices import *
from pyaarlo import (
    ArloBackEnd,
    ArloBackground,
    ArloBaseStation,
    ArloCfg,
    ArloCore,
    ArloDoorBell,
    ArloLogger,
    ArloObjects,
    ArloStorage,
)


# Build core components.
_core = ArloCore()
_core.log = ArloLogger(False)
_core.cfg = ArloCfg(_core.log,
                    username="testing123"
                    )
_core.bg = ArloBackground(_core.log)
_core.st = ArloStorage(_core.cfg, _core.log)
_core.be = ArloBackEnd(_core.cfg, _core.log, _core.bg)

# Create empty objects.
_objs = ArloObjects()


class TestArloCfg(TestCase):

    def test_doorbell_01(self):
        # Build minimal globals.
        _objs.base_stations = [ArloBaseStation("Test Door Bell", _core, _objs, DOOR_BELL_01)]

        # Create and test device.
        db = ArloDoorBell("Door Bell 01", _core, _objs, DOOR_BELL_01)

        self.assertEqual(db.name, "Door Bell 01")
        self.assertEqual(db.device_id, "DOOR-BELL-01-ID")
        self.assertEqual(db.device_type, "doorbell")
        self.assertEqual(db.entity_id, "door_bell_01")
        self.assertEqual(db.unique_id, "DOOR-BELL-01-UNIQUE-ID")

        self.assertEqual(db.resource_id, "doorbells/DOOR-BELL-01-ID")
        self.assertEqual(db.resource_type, "doorbells")
        self.assertEqual(db.serial_number, "DOOR-BELL-01-ID")
        self.assertEqual(db.model_id, "AVD2001A")
        self.assertEqual(db.hw_version, "AVD2001Aer1.4")
        self.assertEqual(db.timezone, "America/Bogota")
        self.assertEqual(db.user_id, "USER-ID")
        self.assertEqual(db.user_role, "ADMIN")
        self.assertEqual(db.xcloud_id, "DOOR-BELL-01-XCLOUD-ID")
        self.assertEqual(db.is_own_parent, True)
        self.assertEqual(db.is_unavailable, False)
        self.assertEqual(db.battery_level, 51)
        self.assertEqual(db.battery_tech, "Rechargeable")
        self.assertEqual(db.has_batteries, True)
        self.assertEqual(db.charger_type, "None")
        self.assertEqual(db.has_charger, False)
        self.assertEqual(db.is_charging, False)
        self.assertEqual(db.is_charger_only, False)
        self.assertEqual(db.is_corded, False)
        self.assertEqual(db.using_wifi, True)
        self.assertEqual(db.signal_strength, 3)

        self.assertEqual(db.too_cold, False)
        self.assertEqual(db.state, "idle")

        self.assertEqual(db.is_video_doorbell, True)
        self.assertEqual(db.is_silenced, False)
        self.assertEqual(db.calls_are_silenced, True)
        self.assertEqual(db.chimes_are_silenced, True)
        self.assertEqual(db.siren_state, 'off')

        # Clear out globals.
        _objs.base_stations = []

    def test_doorbell_02(self):
        # Build minimal globals.
        _objs.base_stations = [ArloBaseStation("Rear Base Station", _core, _objs, BASE_STATION_02)]

        # Create and test device.
        db = ArloDoorBell("Door Bell 02", _core, _objs, DOOR_BELL_02)
        db.update_resources(DOOR_BELL_02_UPDATES)

        self.assertEqual(db.name, "Door Bell 02")
        self.assertEqual(db.device_id, "DOOR-BELL-02-ID")
        self.assertEqual(db.device_type, "doorbell")
        self.assertEqual(db.entity_id, "door_bell_02")
        self.assertEqual(db.unique_id, "DOOR-BELL-02-UNIQUE-ID")

        self.assertEqual(db.resource_id, "doorbells/DOOR-BELL-02-ID")
        self.assertEqual(db.resource_type, "doorbells")
        self.assertEqual(db.serial_number, "DOOR-BELL-02-ID")
        self.assertEqual(db.model_id, "AAD1001")
        self.assertEqual(db.hw_version, None)
        self.assertEqual(db.timezone, None)
        self.assertEqual(db.user_id, "USER-ID")
        self.assertEqual(db.user_role, "ADMIN")
        self.assertEqual(db.xcloud_id, "BASE-STATION-02-XCLOUD-ID")
        self.assertEqual(db.is_own_parent, False)
        self.assertEqual(db.is_unavailable, False)
        self.assertEqual(db.battery_level, 50)
        self.assertEqual(db.battery_tech, "None")
        self.assertEqual(db.has_batteries, False)
        self.assertEqual(db.charger_type, "None")
        self.assertEqual(db.has_charger, False)
        self.assertEqual(db.is_charging, False)
        self.assertEqual(db.is_charger_only, False)
        self.assertEqual(db.is_corded, True)
        self.assertEqual(db.using_wifi, False)
        self.assertEqual(db.signal_strength, 3)

        self.assertEqual(db.too_cold, False)
        self.assertEqual(db.state, "idle")

        self.assertEqual(db.is_video_doorbell, False)
        self.assertEqual(db.is_silenced, False)
        self.assertEqual(db.calls_are_silenced, False)
        self.assertEqual(db.chimes_are_silenced, False)
        self.assertEqual(db.siren_state, 'off')

        # Clear out globals.
        _objs.base_stations = []
