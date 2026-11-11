import asyncio
import unittest
from unittest.mock import AsyncMock

from pyaarlo.capabilities import (
    FALLBACK_SIP_STREAMING_MODELS,
    ArloCapabilities,
    eval_doc_audio_detection,
    eval_doc_battery,
    eval_doc_floodlight,
    eval_doc_full_duplex_talk,
    eval_doc_motion_detection,
    eval_doc_sip_push_to_talk,
    eval_doc_sip_streaming,
    eval_doc_siren,
    eval_doc_spotlight,
    get_capabilities,
    get_cached_capabilities,
    has_full_duplex_push_to_talk,
    static_camera_supports,
    supports_audio_detection,
    supports_battery,
    supports_floodlight,
    supports_motion_detection,
    supports_sip_push_to_talk,
    supports_sip_streaming,
    supports_siren,
    supports_spotlight,
    is_resource,
    eval_doc_resource,
    static_is_resource,
    ArloTypes,
)
from pyaarlo.constant import (
    BATTERY_KEY,
    MOTION_DETECTED_KEY,
    AUDIO_DETECTED_KEY,
    SIREN_STATE_KEY,
    SPOTLIGHT_KEY,
    SIP_STREAMING_KEY,
)


class _FakeStorage:
    def __init__(self):
        self.db = {}

    def get(self, key, default=None):
        k = "/".join(key) if isinstance(key, list) else key
        return self.db.get(k, default)

    def set(self, key, value, prefix=""):
        k = "/".join(key) if isinstance(key, list) else key
        self.db[k] = value
        return value


class _FakeLog:
    def debug(self, msg):
        pass

    def vdebug(self, msg):
        pass


class _FakeBackend:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    async def get(self, path, raw=False):
        self.calls.append({"path": path, "raw": raw})
        return self.response


class _FakeCore:
    def __init__(self, response=None):
        self.log = _FakeLog()
        self.st = _FakeStorage()
        self.be = _FakeBackend(response)


class _FakeCamera:
    def __init__(self, core, model_id, interface_version="i001", device_type="camera", parent_id="dev1", device_id="dev1"):
        self._core = core
        self.model_id = model_id
        self.interface_version = interface_version
        self.device_type = device_type
        self.parent_id = parent_id
        self.device_id = device_id


class TestCapabilities(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from pyaarlo.capabilities import _memory_cache
        _memory_cache.clear()

    def test_fallback_models_detected(self):
        core = _FakeCore()
        for model in FALLBACK_SIP_STREAMING_MODELS:
            self.assertTrue(supports_sip_streaming(core, model, 1))

    def test_non_sip_fallback_returns_false(self):
        core = _FakeCore()
        self.assertFalse(supports_sip_streaming(core, "VMC3030", 1))

    async def test_get_capabilities_fetches_and_caches(self):
        doc = {
            "Capabilities": {
                "Streaming": {"SIPStreaming": True},
                "PushToTalk": {"signal": ["sip"], "fullDuplex": True},
            }
        }
        core = _FakeCore(doc)
        res = await get_capabilities(core, "VMC4040", 2)
        self.assertEqual(res, doc)
        self.assertEqual(len(core.be.calls), 1)

        # Second call hits cache
        res2 = await get_capabilities(core, "VMC4040", 2)
        self.assertEqual(res2, doc)
        self.assertEqual(len(core.be.calls), 1)

        # Synchronous check uses cached capabilities
        self.assertTrue(supports_sip_streaming(core, "VMC4040", 2))
        self.assertTrue(supports_sip_push_to_talk(core, "VMC4040", 2))
        self.assertTrue(has_full_duplex_push_to_talk(core, "VMC4040", 2))

    async def test_capability_document_false_overrides_fallback(self):
        doc = {
            "Capabilities": {
                "Streaming": {"SIPStreaming": False},
            }
        }
        core = _FakeCore(doc)
        model = FALLBACK_SIP_STREAMING_MODELS[0]
        await get_capabilities(core, model, 1)
        self.assertFalse(supports_sip_streaming(core, model, 1))

    def test_eval_doc_motion_detection(self):
        # Automation 3.0 trigger
        doc1 = {"Capabilities": {"Automation3.0": {"AutomationTriggers": {"motionStart": {}}}}}
        self.assertTrue(eval_doc_motion_detection(doc1))

        # Automation 1.0/2.0 PIR trigger
        doc2 = {"Capabilities": {"Automation": {"AutomationTriggers": {"PIRMotionDetectionTrigger": {}}}}}
        self.assertTrue(eval_doc_motion_detection(doc2))

        # In-video trigger (Arlo Baby)
        doc3 = {"Capabilities": {"Automation": {"AutomationTriggers": {"IVMotionDetectionTrigger": {}}}}}
        self.assertTrue(eval_doc_motion_detection(doc3))

        # MotionDetectionTest flag
        doc4 = {"Capabilities": {"MotionDetectionTest": {"default": True}}}
        self.assertTrue(eval_doc_motion_detection(doc4))

        # ActivityZones
        doc5 = {"Capabilities": {"ActivityZones": {"ZoneTypes": []}}}
        self.assertTrue(eval_doc_motion_detection(doc5))

        # Chime / non-motion device
        doc_nomotion = {
            "Capabilities": {
                "ResourceTypes": ["Chime"],
                "Automation3.0": {"AutomationActions": {"playTrack": {}}},
            }
        }
        self.assertFalse(eval_doc_motion_detection(doc_nomotion))

    def test_eval_doc_audio_and_siren(self):
        doc_audio = {
            "Capabilities": {
                "Automation3.0": {"AutomationTriggers": {"audioStart": {}}},
                "ResourceTypes": ["Siren", "Camera"],
            }
        }
        self.assertTrue(eval_doc_audio_detection(doc_audio))
        self.assertTrue(eval_doc_siren(doc_audio))

        doc_no_audio_or_siren = {
            "Capabilities": {
                "ResourceTypes": ["Camera"],
            }
        }
        self.assertFalse(eval_doc_audio_detection(doc_no_audio_or_siren))
        self.assertFalse(eval_doc_siren(doc_no_audio_or_siren))

    def test_eval_doc_battery_and_spotlight(self):
        doc_battery = {
            "Capabilities": {
                "PowerSource": {
                    "Battery": {"level": {"max": 100}, "batteryTech": ["Primary", "Rechargeable"]},
                },
                "Spotlight": {"spotLightMode": {"default": "auto"}},
            }
        }
        self.assertTrue(eval_doc_battery(doc_battery))
        self.assertTrue(eval_doc_spotlight(doc_battery))

        # AC only (indoor camera)
        doc_ac_only = {
            "Capabilities": {
                "PowerSource": {"AC": {}},
            }
        }
        self.assertFalse(eval_doc_battery(doc_ac_only))
        self.assertFalse(eval_doc_spotlight(doc_ac_only))

    async def test_dynamic_camera_supports_with_cache(self):
        doc = {
            "Capabilities": {
                "Automation3.0": {
                    "AutomationTriggers": {"motionStart": {}},
                    "AutomationActions": {"sirenOn": {}},
                },
                "PowerSource": {
                    "Battery": {"batteryTech": ["Rechargeable"]},
                },
                "Spotlight": {},
            }
        }
        core = _FakeCore(doc)
        await get_capabilities(core, "CUSTOM_CAM", "i001")

        cam = _FakeCamera(core, "CUSTOM_CAM", "i001")
        self.assertTrue(ArloCapabilities.check_camera_supports(cam, MOTION_DETECTED_KEY))
        self.assertTrue(ArloCapabilities.check_camera_supports(cam, SIREN_STATE_KEY))
        self.assertTrue(ArloCapabilities.check_camera_supports(cam, SPOTLIGHT_KEY))
        self.assertTrue(ArloCapabilities.check_camera_supports(cam, BATTERY_KEY))

    def test_static_camera_supports_fallback_when_uncached(self):
        core = _FakeCore()
        cam = _FakeCamera(core, "VMC3030", "i005")
        # Uncached VMC3030 has no spotlight, no siren, has battery
        self.assertTrue(ArloCapabilities.check_camera_supports(cam, MOTION_DETECTED_KEY))
        self.assertTrue(ArloCapabilities.check_camera_supports(cam, BATTERY_KEY))
        self.assertFalse(ArloCapabilities.check_camera_supports(cam, SIREN_STATE_KEY))
        self.assertFalse(ArloCapabilities.check_camera_supports(cam, SPOTLIGHT_KEY))

        # Essential indoor has no battery in static rules
        indoor_cam = _FakeCamera(core, "VMC2040", "i001")
        self.assertFalse(ArloCapabilities.check_camera_supports(indoor_cam, BATTERY_KEY))

    def test_eval_doc_resource(self):
        # Multi-role device (e.g. AVD2001A video doorbell)
        doc_doorbell = {
            "Capabilities": {
                "ResourceTypes": ["Gateway", "Camera", "AudioDoorbell", "Siren"]
            }
        }
        self.assertTrue(eval_doc_resource(doc_doorbell, "camera"))
        self.assertTrue(eval_doc_resource(doc_doorbell, "gateway"))
        self.assertTrue(eval_doc_resource(doc_doorbell, "doorbell"))
        self.assertTrue(eval_doc_resource(doc_doorbell, "siren"))
        self.assertFalse(eval_doc_resource(doc_doorbell, "light"))
        self.assertFalse(eval_doc_resource(doc_doorbell, "chime"))

        # Light device
        doc_light = {
            "Capabilities": {
                "ResourceTypes": ["Light"]
            }
        }
        self.assertTrue(eval_doc_resource(doc_light, "light"))
        self.assertFalse(eval_doc_resource(doc_light, "camera"))

        # Chime device
        doc_chime = {
            "Capabilities": {
                "ResourceTypes": ["Chime"]
            }
        }
        self.assertTrue(eval_doc_resource(doc_chime, "chime"))
        self.assertFalse(eval_doc_resource(doc_chime, "doorbell"))

    async def test_is_resource_dynamic_vs_static(self):
        doc = {
            "Capabilities": {
                "ResourceTypes": ["Gateway", "Camera", "Siren"]
            }
        }
        core = _FakeCore(doc)
        await get_capabilities(core, "VMC2050A", "i011")

        # Dynamic via cache
        self.assertTrue(is_resource(core, "VMC2050A", "i011", "camera"))
        self.assertTrue(is_resource(core, "VMC2050A", "i011", "gateway"))
        self.assertTrue(is_resource(core, "VMC2050A", "i011", "siren"))
        self.assertFalse(is_resource(core, "VMC2050A", "i011", "doorbell"))

        # Static fallback when uncached
        empty_core = _FakeCore()
        self.assertTrue(is_resource(empty_core, "VMC4030", "i011", "camera", device_type="camera"))
        self.assertFalse(is_resource(empty_core, "VMC4030", "i011", "gateway"))
        self.assertTrue(is_resource(empty_core, "VMC4041", "i001", "gateway"))

    def test_arlo_types_compatibility(self):
        from pyaarlo.types import ArloTypes as ShimTypes
        self.assertTrue(ArloTypes.is_a_camera("camera", "VMC3030"))
        self.assertTrue(ShimTypes.is_a_camera("camera", "VMC3030"))
        self.assertTrue(ArloTypes.can_be_own_base_station("VMC4041"))
        self.assertTrue(ShimTypes.can_be_own_base_station("VMC4041"))
        self.assertFalse(ArloTypes.can_be_own_base_station("VMC4030"))
