import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pyaarlo.core.backend import ArloBackEnd
from pyaarlo.constant import DEFAULT_RESOURCES


class AuthenticationQuerySyntaxTests(unittest.TestCase):
    def test_authentication_queries_do_not_insert_spaces_around_equals(self):
        source = (Path(__file__).parents[1] / "pyaarlo" / "core" / "backend" / "__init__.py").read_text()

        self.assertIn('AUTH_GET_FACTORS}?data={int(time.time())}', source)
        self.assertIn('AUTH_VALIDATE_PATH}?data={int(time.time())}', source)
        self.assertNotIn('AUTH_GET_FACTORS}?data = ', source)
        self.assertNotIn('AUTH_VALIDATE_PATH}?data = ', source)


class BasestationEventDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.backend = ArloBackEnd.__new__(ArloBackEnd)
        self.backend._resource_types = DEFAULT_RESOURCES
        self.backend._callbacks = {}
        self.backend._requests = {}

        self.arlo = MagicMock()
        self.backend._arlo = self.arlo
        self.backend._tasks = MagicMock()
        self.backend._tasks.run_now = lambda cb, *args, **kwargs: cb(*args, **kwargs)
        self.backend._log = MagicMock()
        self.backend._debug = MagicMock()
        self.backend._vdebug = MagicMock()

    def test_basestation_in_default_resources(self):
        self.assertIn("basestation", DEFAULT_RESOURCES)

    def test_basestation_wakeup_dispatches_to_all_devices_and_base(self):
        doorbell_cb = MagicMock()
        cam_cb = MagicMock()
        base_cb = MagicMock()
        self.backend._callbacks = {
            "DOORBELL_1": [doorbell_cb],
            "CAMERA_1": [cam_cb],
            "BASE_1": [base_cb],
        }

        packet = {
            "action": "wakeup",
            "from": "BASE_1",
            "properties": {
                "devices": ["DOORBELL_1", "CAMERA_1"],
                "duration": 15,
            },
            "resource": "basestation",
            "to": "USER_1",
            "transId": "trans-1",
        }

        self.backend._event_run_callbacks(packet)

        doorbell_cb.assert_called_once_with(resource="basestation", event=packet)
        cam_cb.assert_called_once_with(resource="basestation", event=packet)
        base_cb.assert_called_once_with(resource="basestation", event=packet)

    def test_basestation_wakeup_standalone_doorbell_no_duplicates(self):
        doorbell_cb = MagicMock()
        self.backend._callbacks = {
            "DOORBELL_1": [doorbell_cb],
        }

        packet = {
            "action": "wakeup",
            "from": "DOORBELL_1",
            "properties": {
                "devices": ["DOORBELL_1"],
                "duration": 15,
            },
            "resource": "basestation",
            "to": "USER_1",
            "transId": "trans-2",
        }

        self.backend._event_run_callbacks(packet)

        doorbell_cb.assert_called_once_with(resource="basestation", event=packet)

    def test_basestation_is_response_dispatches_to_from_device(self):
        doorbell_cb = MagicMock()
        self.backend._callbacks = {
            "DOORBELL_1": [doorbell_cb],
        }

        packet = {
            "action": "is",
            "from": "DOORBELL_1",
            "properties": {},
            "resource": "basestation",
            "to": "USER_1",
            "transId": "trans-3",
        }

        self.backend._event_run_callbacks(packet)

        doorbell_cb.assert_called_once_with(resource="basestation", event=packet)

    def test_basestation_list_properties_dispatches_by_serial(self):
        dev1_cb = MagicMock()
        dev2_cb = MagicMock()
        self.backend._callbacks = {
            "DEV_1": [dev1_cb],
            "DEV_2": [dev2_cb],
        }

        packet = {
            "action": "is",
            "from": "BASE_1",
            "properties": [
                {"serialNumber": "DEV_1", "batteryLevel": 85},
                {"serialNumber": "DEV_2", "batteryLevel": 90},
            ],
            "resource": "basestation",
            "to": "USER_1",
        }

        self.backend._event_run_callbacks(packet)

        dev1_cb.assert_called_once_with(
            resource="basestation",
            event={"serialNumber": "DEV_1", "batteryLevel": 85},
        )
        dev2_cb.assert_called_once_with(
            resource="basestation",
            event={"serialNumber": "DEV_2", "batteryLevel": 90},
        )

    def test_fallback_dispatches_to_from_when_no_other_id_present(self):
        cam_cb = MagicMock()
        self.backend._callbacks = {
            "CAM_1": [cam_cb],
        }

        packet = {
            "action": "customAction",
            "from": "CAM_1",
            "properties": {"foo": "bar"},
            "resource": "someUnknownResource",
        }

        self.backend._event_run_callbacks(packet)

        cam_cb.assert_called_once_with(
            resource="someUnknownResource",
            event=packet,
        )


class DeviceBasestationEventHandlingTests(unittest.TestCase):
    def test_doorbell_handles_button_press_on_basestation_resource(self):
        from pyaarlo.doorbell import ArloDoorBell
        from pyaarlo.core.storage import ArloStorage

        arlo = MagicMock()
        arlo.cfg.db_ding_time = 10
        arlo.st = ArloStorage(arlo.cfg, arlo.log)
        arlo.tasks.run_in = MagicMock()
        objs = MagicMock()
        objs.cameras = []
        objs.base_stations = []

        doorbell = ArloDoorBell("Front Doorbell", arlo, objs, {
            "deviceId": "DB_1",
            "deviceType": "doorbell",
            "parentId": "DB_1",
            "userId": "user-1",
            "modelId": "AVD2001",
        })

        callback = MagicMock()
        doorbell.add_attr_callback("buttonPressed", callback)

        event = {
            "action": "is",
            "from": "DB_1",
            "resource": "basestation",
            "properties": {"buttonPressed": True},
        }
        doorbell._event_handler("basestation", event)

        callback.assert_called_once_with(doorbell, "buttonPressed", True)

    def test_camera_handles_wakeup_on_basestation_resource(self):
        from pyaarlo.camera import ArloCamera
        from pyaarlo.core.storage import ArloStorage

        arlo = MagicMock()
        arlo.cfg.recent_time = 30
        arlo.st = ArloStorage(arlo.cfg, arlo.log)
        arlo.tasks.run_in = MagicMock()
        objs = MagicMock()
        objs.cameras = []
        objs.base_stations = []

        camera = ArloCamera("Front Camera", arlo, objs, {
            "deviceId": "CAM_1",
            "deviceType": "camera",
            "parentId": "CAM_1",
            "userId": "user-1",
            "modelId": "VMC4041",
        })

        callback = MagicMock()
        camera.add_attr_callback("recentActivity", callback)

        event = {
            "action": "wakeup",
            "from": "CAM_1",
            "resource": "basestation",
            "properties": {"duration": 15, "devices": ["CAM_1"]},
        }
        camera._event_handler("basestation", event)

        callback.assert_called_once_with(camera, "recentActivity", True)


if __name__ == "__main__":
    unittest.main()
