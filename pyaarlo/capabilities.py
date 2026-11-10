from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import ArloCore
    from .base_station import ArloBaseStation
    from .camera import ArloCamera
    from .child_device import ArloChildDevice
    from .device import ArloDevice
    from .doorbell import ArloDoorBell
    from .light import ArloLight
    from .sensor import ArloSensor

from .constant import (
    AIR_QUALITY_KEY,
    ALS_STATE_KEY,
    AUDIO_DETECTED_KEY,
    BATTERY_KEY,
    BUTTON_PRESSED_KEY,
    CAPTURED_TODAY_KEY,
    CONNECTION_KEY,
    CONTACT_STATE_KEY,
    CRY_DETECTION_KEY,
    FLOODLIGHT_KEY,
    HUMIDITY_KEY,
    LAST_CAPTURE_KEY,
    MEDIA_PLAYER_KEY,
    MODEL_BABY,
    MODEL_ESSENTIAL_INDOOR,
    MODEL_ESSENTIAL_INDOOR_GEN2_2K,
    MODEL_ESSENTIAL_INDOOR_GEN2_HD,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
    MODEL_ESSENTIAL_SPOTLIGHT,
    MODEL_ESSENTIAL_VIDEO_DOORBELL,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
    MODEL_ESSENTIAL_XL_SPOTLIGHT,
    MODEL_GO,
    MODEL_PRO_2,
    MODEL_PRO_3,
    MODEL_PRO_3_FLOODLIGHT,
    MODEL_WIRED_FLOODLIGHT,
    MODEL_PRO_4,
    MODEL_PRO_5,
    MODEL_PRO_6,
    MODEL_PRO_6_XL,
    MODEL_ULTRA,
    MODEL_WIRED_VIDEO_DOORBELL,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
    MOTION_DETECTED_KEY,
    NIGHTLIGHT_KEY,
    PING_CAPABILITY,
    RECENT_ACTIVITY_KEY,
    RESOURCE_CAPABILITY,
    SIGNAL_STR_KEY,
    SILENT_MODE_KEY,
    SIREN_STATE_KEY,
    SPOTLIGHT_KEY,
    TAMPER_STATE_KEY,
    TEMPERATURE_KEY,
    CAPABILITIES_PATH_FORMAT,
    SIP_STREAMING_KEY,
    SIP_PUSH_TO_TALK_KEY,
)



CACHE_TTL = 24 * 60 * 60  # seconds

FALLBACK_SIP_STREAMING_MODELS = (
    MODEL_WIRED_VIDEO_DOORBELL,
    MODEL_ESSENTIAL_VIDEO_DOORBELL,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
    MODEL_ESSENTIAL_INDOOR_GEN2_HD,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_INDOOR_GEN2_2K,
)

_memory_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _cache_key(model_id: str, interface_version: int | str) -> str:
    return f"{model_id.lower()}_{interface_version}"


def _storage_key(cache_key: str) -> list[str]:
    return ["ArloCapabilities", cache_key]


async def fetch_capability_document(core: ArloCore, model_id: str, interface_version: int | str) -> dict[str, Any]:
    path = CAPABILITIES_PATH_FORMAT.format(model_id.lower(), interface_version)
    response = await core.be.get(path, raw=True)
    if not isinstance(response, dict):
        core.log.debug(f"capabilities: no document for {model_id}/{interface_version}")
        return {}
    return response


def get_cached_capabilities(core: Any | None, model_id: str | None, interface_version: int | str | None) -> dict[str, Any] | None:
    if not model_id or interface_version is None:
        return None
    cache_key = _cache_key(model_id, interface_version)
    now = time.time()
    cached = _memory_cache.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1]
    if core is not None and hasattr(core, "st") and core.st is not None:
        stored = core.st.get(_storage_key(cache_key))
        if stored is not None and isinstance(stored, dict) and stored.get("expires", 0) > now:
            data = stored.get("data", {})
            _memory_cache[cache_key] = (stored["expires"], data)
            return data
    return None


async def get_capabilities(core: ArloCore, model_id: str | None, interface_version: int | str | None) -> dict[str, Any]:
    """Return the Arlo-published capability document for a model/interface-version pair.

    Cached in memory and in ArloStorage for CACHE_TTL seconds. Always
    returns a dict, {} on any failure, so callers can chain .get()
    lookups without special-casing errors.
    """
    if not model_id or interface_version is None:
        return {}

    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is not None:
        return cached

    now = time.time()
    data = await fetch_capability_document(core, model_id, interface_version)
    cache_key = _cache_key(model_id, interface_version)
    expires = now + CACHE_TTL
    _memory_cache[cache_key] = (expires, data)
    if core is not None and hasattr(core, "st") and core.st is not None:
        core.st.set(_storage_key(cache_key), {"expires": expires, "data": data})
    return data


def supports_sip_streaming(core: Any | None, model_id: str | None, interface_version: int | str | None) -> bool:
    """Returns True if the device supports live SIP/WebRTC streaming.

    Checks cache/storage first. If no capability document is cached,
    falls back to the hardcoded model list.
    """
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is not None:
        capabilities = cached.get("Capabilities")
        if capabilities is not None:
            return bool(capabilities.get("Streaming", {}).get("SIPStreaming", False))
    return model_id is not None and model_id.upper().startswith(
        tuple(model.upper() for model in FALLBACK_SIP_STREAMING_MODELS)
    )


def supports_sip_push_to_talk(core: Any | None, model_id: str | None, interface_version: int | str | None) -> bool:
    """Returns True if the device signals push-to-talk over SIP."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is None:
        return False
    capabilities = cached.get("Capabilities")
    if capabilities is None:
        return False
    return "sip" in capabilities.get("PushToTalk", {}).get("signal", [])


def has_full_duplex_push_to_talk(core: Any | None, model_id: str | None, interface_version: int | str | None) -> bool:
    """Returns True if the device supports simultaneous talk/listen push-to-talk."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is None:
        return False
    capabilities = cached.get("Capabilities")
    if capabilities is None:
        return False
    return bool(capabilities.get("PushToTalk", {}).get("fullDuplex", False))


async def async_supports_sip_streaming(core: ArloCore, model_id: str | None, interface_version: int | str | None) -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    capabilities = doc.get("Capabilities")
    if capabilities is not None:
        return bool(capabilities.get("Streaming", {}).get("SIPStreaming", False))
    return model_id is not None and model_id.upper().startswith(
        tuple(model.upper() for model in FALLBACK_SIP_STREAMING_MODELS)
    )


async def async_supports_sip_push_to_talk(core: ArloCore, model_id: str | None, interface_version: int | str | None) -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    capabilities = doc.get("Capabilities")
    if capabilities is None:
        return False
    return "sip" in capabilities.get("PushToTalk", {}).get("signal", [])


async def async_has_full_duplex_push_to_talk(core: ArloCore, model_id: str | None, interface_version: int | str | None) -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    capabilities = doc.get("Capabilities")
    if capabilities is None:
        return False
    return bool(capabilities.get("PushToTalk", {}).get("fullDuplex", False))


class ArloCapabilities:
    """Arlo device capabilities.

    These methods are used by instances of objects to determine their
    capabilities.

    They have been moved into this umbrella class to:
     - move the knowledge into one place, hopefully making it easier to edit
     - reduce some of the clutter in the object clases

    XXX This introduces a circular dependency because objects need to know
        capabilites and capabilities need to know about objects. I'll think
        of a way to break this.
    """

    @staticmethod
    def _check_device_supports(_device: ArloDevice, cap: str) -> bool:
        if cap in (CONNECTION_KEY,):
            return True
        return False

    @staticmethod
    def _check_child_supports(child_device: ArloChildDevice, cap: str) -> bool:
        return ArloCapabilities._check_device_supports(child_device, cap)

    @staticmethod
    def check_base_station_supports(base_station: ArloBaseStation, cap: str) -> bool:
        if cap in (TEMPERATURE_KEY, HUMIDITY_KEY, AIR_QUALITY_KEY):
            if base_station.model_id.startswith(MODEL_BABY):
                return True
        if cap in (SIREN_STATE_KEY,):
            if (
                    base_station.model_id.startswith(("VMB400", "VMB450"))
                    or base_station.model_id == MODEL_GO
            ):
                return True

        if cap in (PING_CAPABILITY,):

            # Always true for these devices.
            if base_station.model_id.startswith(MODEL_BABY):
                return True
            if base_station.model_id.startswith(MODEL_WIRED_VIDEO_DOORBELL):
                return True

            # Don't ping these devices ever.
            if base_station.model_id.startswith((
                    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
                    MODEL_ESSENTIAL_SPOTLIGHT,
                    MODEL_ESSENTIAL_VIDEO_DOORBELL,
                    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
                    MODEL_ESSENTIAL_XL_SPOTLIGHT,
                    MODEL_PRO_3_FLOODLIGHT,
                    MODEL_WIRED_FLOODLIGHT,
                    MODEL_PRO_4,
                    MODEL_PRO_5,
                    MODEL_PRO_6,
                    MODEL_PRO_6_XL,
                    MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
                    MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
            )):
                return False

            # We have to be careful pinging some base stations because it can rapidly
            # drain the battery power. Don't ping if:
            # - it is a device that acts as its own base station
            # - it does not have a power supply or charger connected
            # - it is using WiFi directly rather than an Arlo base station
            if base_station.is_own_parent:
                if not base_station.is_corded and not base_station.has_charger:
                    if base_station.using_wifi:
                        return False

            # All others, then ping.
            return True

        if cap in (RESOURCE_CAPABILITY,):
            # Not all devices need (or want) to get their resources queried.
            if base_station.model_id.startswith((
                    MODEL_ESSENTIAL_VIDEO_DOORBELL,
                    MODEL_ESSENTIAL_SPOTLIGHT,
                    MODEL_ESSENTIAL_XL_SPOTLIGHT,
            )):
                return False
            return True
        return ArloCapabilities._check_device_supports(base_station, cap)

    @staticmethod
    def check_camera_supports(camera: ArloCamera, cap: str) -> bool:
        if cap in (SIP_STREAMING_KEY,):
            return supports_sip_streaming(getattr(camera, "_core", None), camera.model_id, camera.interface_version)
        if cap in (SIP_PUSH_TO_TALK_KEY,):
            return supports_sip_push_to_talk(getattr(camera, "_core", None), camera.model_id, camera.interface_version)
        if cap in (BATTERY_KEY,):
            if camera.model_id.startswith((
                    MODEL_ESSENTIAL_INDOOR,
                    MODEL_ESSENTIAL_INDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_INDOOR_GEN2_HD,
            )):
                return False
            else:
                return True
        if cap in (MOTION_DETECTED_KEY, SIGNAL_STR_KEY):
            return True
        if cap in (LAST_CAPTURE_KEY, CAPTURED_TODAY_KEY, RECENT_ACTIVITY_KEY):
            return True
        if cap in (AUDIO_DETECTED_KEY,):
            if camera.model_id.startswith((
                    MODEL_ESSENTIAL_SPOTLIGHT,
                    MODEL_ESSENTIAL_XL_SPOTLIGHT,
                    MODEL_ESSENTIAL_INDOOR,
                    MODEL_ESSENTIAL_INDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_INDOOR_GEN2_HD,
                    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
                    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
                    MODEL_PRO_2,
                    MODEL_PRO_3,
                    MODEL_PRO_3_FLOODLIGHT,
                    MODEL_WIRED_FLOODLIGHT,
                    MODEL_PRO_4,
                    MODEL_PRO_5,
                    MODEL_PRO_6,
                    MODEL_PRO_6_XL,
                    MODEL_ULTRA,
                    MODEL_GO,
                    MODEL_BABY,
            )):
                return True
            if camera.device_type.startswith("arloq"):
                return True
        if cap in (SIREN_STATE_KEY,):
            if camera.model_id.startswith((
                    MODEL_ESSENTIAL_SPOTLIGHT,
                    MODEL_ESSENTIAL_XL_SPOTLIGHT,
                    MODEL_ESSENTIAL_INDOOR,
                    MODEL_ESSENTIAL_INDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_INDOOR_GEN2_HD,
                    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
                    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
                    MODEL_PRO_3,
                    MODEL_PRO_3_FLOODLIGHT,
                    MODEL_WIRED_FLOODLIGHT,
                    MODEL_PRO_4,
                    MODEL_PRO_5,
                    MODEL_PRO_6,
                    MODEL_PRO_6_XL,
                    MODEL_ULTRA,
                    MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
                    MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
                    MODEL_ESSENTIAL_VIDEO_DOORBELL,
            )):
                return True
        if cap in (SPOTLIGHT_KEY,):
            if camera.model_id.startswith((
                    MODEL_ESSENTIAL_SPOTLIGHT,
                    MODEL_ESSENTIAL_XL_SPOTLIGHT,
                    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
                    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
                    MODEL_PRO_3,
                    MODEL_PRO_4,
                    MODEL_PRO_5,
                    MODEL_PRO_6,
                    MODEL_PRO_6_XL,
                    MODEL_ULTRA
            )):
                return True
        if cap in (TEMPERATURE_KEY, HUMIDITY_KEY, AIR_QUALITY_KEY):
            if camera.model_id.startswith(MODEL_BABY):
                return True
        if cap in (MEDIA_PLAYER_KEY, NIGHTLIGHT_KEY, CRY_DETECTION_KEY):
            if camera.model_id.startswith(MODEL_BABY):
                return True
        if cap in (FLOODLIGHT_KEY,):
            if camera.model_id.startswith((MODEL_PRO_3_FLOODLIGHT, MODEL_WIRED_FLOODLIGHT)):
                return True
        if cap in (CONNECTION_KEY,):
            # These devices are their own base stations so don't re-add connection key.
            if camera.parent_id == camera.device_id and camera.model_id.startswith((
                    MODEL_BABY,
                    MODEL_PRO_3_FLOODLIGHT,
                    MODEL_WIRED_FLOODLIGHT,
                    MODEL_PRO_4,
                    MODEL_PRO_5,
                    MODEL_PRO_6,
                    MODEL_PRO_6_XL,
                    MODEL_ESSENTIAL_SPOTLIGHT,
                    MODEL_ESSENTIAL_XL_SPOTLIGHT,
                    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
                    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
                    MODEL_WIRED_VIDEO_DOORBELL,
                    MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
                    MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
                    MODEL_ESSENTIAL_VIDEO_DOORBELL,
                    MODEL_ESSENTIAL_INDOOR,
                    MODEL_ESSENTIAL_INDOOR_GEN2_2K,
                    MODEL_ESSENTIAL_INDOOR_GEN2_HD,
                    MODEL_GO,
            )):
                return False
            if camera.device_type in ("arloq", "arloqs"):
                return False
        return ArloCapabilities._check_child_supports(camera, cap)

    @staticmethod
    def check_doorbell_supports_video(doorbell: ArloDoorBell) -> bool:
        return doorbell.model_id.startswith((
            MODEL_WIRED_VIDEO_DOORBELL,
            MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
            MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
            MODEL_ESSENTIAL_VIDEO_DOORBELL
        ))

    @staticmethod
    def check_doorbell_supports(doorbell: ArloDoorBell, cap: str) -> bool:
        # Video Doorbells appear as both ArloCameras and ArloDoorBells, where
        # capabilities double up - eg, motion detection - we provide the
        # capability at the camera level.
        if cap in (MOTION_DETECTED_KEY, BATTERY_KEY, SIGNAL_STR_KEY, CONNECTION_KEY):
            return not ArloCapabilities.check_doorbell_supports_video(doorbell)
        if cap in (BUTTON_PRESSED_KEY, SILENT_MODE_KEY):
            return True
        return ArloCapabilities._check_child_supports(doorbell, cap)

    @staticmethod
    def check_sensor_supports(_sensor: ArloSensor, cap: str) -> bool:
        if cap in (ALS_STATE_KEY, BATTERY_KEY, CONTACT_STATE_KEY, MOTION_DETECTED_KEY,
                   TAMPER_STATE_KEY, TEMPERATURE_KEY):
            return True
        return False

    @staticmethod
    def check_light_supports(light: ArloLight, cap: str) -> bool:
        if cap in (MOTION_DETECTED_KEY, BATTERY_KEY):
            return True
        return ArloCapabilities._check_child_supports(light, cap)
