from unittest import TestCase

from tests.devices import (
    DOORBELL_DEVICE_01
)
from pyaarlo import (
    ArloCfg,
    ArloBackEnd,
    ArloBackground,
    ArloDoorBell,
    ArloLogger,
    ArloStorage,
    ArloCore,
    ArloObjects, ArloBaseStation,
)


_core = ArloCore()
_objs = ArloObjects()

_core.log = ArloLogger(False)
_core.cfg = ArloCfg(_core.log,
                    username="testing123"
                    )
_core.bg = ArloBackground(_core.log)
_core.st = ArloStorage(_core.cfg, _core.log)
_core.be = ArloBackEnd(_core.cfg, _core.log, _core.bg)


class TestArloCfg(TestCase):

    def test_doorbell(self):
        # Build minimal globals.
        _objs.base_stations = [ArloBaseStation("Test Door Bell", _core, _objs, DOORBELL_DEVICE_01)]

        # Create and test device.
        db = ArloDoorBell("Test Door Bell", _core, _objs, DOORBELL_DEVICE_01)

        self.assertEqual(db.name, "Test Door Bell")
        self.assertEqual(db.device_id, "YYYYYYYYYYYYY")
        self.assertEqual(db.device_type, "doorbell")
        self.assertEqual(db.entity_id, "test_door_bell")
        self.assertEqual(db.unique_id, "IIIIIII-III-IIIIIII_IIIIIIIIIIIII")

        self.assertEqual(db.resource_id, "doorbells/YYYYYYYYYYYYY")
        self.assertEqual(db.resource_type, "doorbells")
        self.assertEqual(db.serial_number, "YYYYYYYYYYYYY")
        self.assertEqual(db.model_id, "AVD2001A")
        self.assertEqual(db.hw_version, "AVD2001Aer1.4")
        self.assertEqual(db.timezone, "America/Bogota")
        self.assertEqual(db.user_id, "UUUU-UUU-UUUUUUUU")
        self.assertEqual(db.user_role, "ADMIN")
        self.assertEqual(db.xcloud_id, "XXXXXX-XXXX-XXX-XXXXXXXXX")
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
