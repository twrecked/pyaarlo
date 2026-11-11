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
    MODEL_GO_2,
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

FALLBACK_OWN_BASE_STATION_MODELS = (
    MODEL_WIRED_VIDEO_DOORBELL,
    MODEL_PRO_3_FLOODLIGHT,
    MODEL_WIRED_FLOODLIGHT,
    MODEL_PRO_4,
    MODEL_PRO_5,
    MODEL_PRO_6,
    MODEL_PRO_6_XL,
    MODEL_ESSENTIAL_SPOTLIGHT,
    MODEL_ESSENTIAL_XL_SPOTLIGHT,
    MODEL_ESSENTIAL_INDOOR,
    MODEL_ESSENTIAL_INDOOR_GEN2_2K,
    MODEL_ESSENTIAL_INDOOR_GEN2_HD,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
    MODEL_ESSENTIAL_VIDEO_DOORBELL,
    MODEL_GO_2,
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


def eval_doc_motion_detection(doc: dict[str, Any]) -> bool:
    """Returns True if the capability document declares motion detection support."""
    caps = doc.get("Capabilities", {})
    auto3 = caps.get("Automation3.0", {})
    if "motionStart" in auto3.get("AutomationTriggers", {}):
        return True
    if "motion" in auto3.get("AutomationSettings", {}):
        return True
    auto = caps.get("Automation", {})
    auto_triggers = auto.get("AutomationTriggers", {})
    if any(k in auto_triggers for k in ("PIRMotionDetectionTrigger", "IVMotionDetectionTrigger")):
        return True
    if caps.get("MotionDetectionTest", {}).get("default") is True:
        return True
    if "MotionDetectionTest" in caps and isinstance(caps.get("MotionDetectionTest"), dict):
        return True
    if "ActivityZones" in caps or "PIRZones" in caps:
        return True
    return False


def eval_doc_audio_detection(doc: dict[str, Any]) -> bool:
    """Returns True if the capability document declares audio detection support."""
    caps = doc.get("Capabilities", {})
    auto3 = caps.get("Automation3.0", {})
    if "audioStart" in auto3.get("AutomationTriggers", {}):
        return True
    if "audio" in auto3.get("AutomationSettings", {}):
        return True
    auto = caps.get("Automation", {})
    if "AudioDetectionTrigger" in auto.get("AutomationTriggers", {}):
        return True
    return False


def eval_doc_siren(doc: dict[str, Any]) -> bool:
    """Returns True if the capability document declares a built-in siren."""
    caps = doc.get("Capabilities", {})
    res_types = caps.get("ResourceTypes", [])
    if isinstance(res_types, list) and "Siren" in res_types:
        return True
    auto3 = caps.get("Automation3.0", {})
    auto3_actions = auto3.get("AutomationActions", {})
    if "sirenOn" in auto3_actions or "sirenOff" in auto3_actions:
        return True
    auto = caps.get("Automation", {})
    auto_actions = auto.get("AutomationActions", {})
    if any(k in auto_actions for k in ("SirenAction", "SoftSirenAction", "SirenOnCamera")):
        return True
    return False


def eval_doc_spotlight(doc: dict[str, Any]) -> bool:
    """Returns True if the capability document declares a physical spotlight."""
    caps = doc.get("Capabilities", {})
    sp = caps.get("Spotlight")
    if not isinstance(sp, dict) or sp.get("proxy", False) is True:
        return False
    return True


def eval_doc_floodlight(doc: dict[str, Any]) -> bool:
    """Returns True if the capability document declares floodlight support."""
    caps = doc.get("Capabilities", {})
    fl = caps.get("Floodlight")
    if not isinstance(fl, dict) or fl.get("proxy", False) is True:
        return False
    return True


def eval_doc_battery(doc: dict[str, Any]) -> bool:
    """Returns True if the device has a battery power source."""
    caps = doc.get("Capabilities", {})
    power = caps.get("PowerSource", {})
    if "Battery" not in power:
        return False
    battery = power.get("Battery")
    if not isinstance(battery, dict):
        return bool(battery)
    tech = battery.get("batteryTech", [])
    if isinstance(tech, list) and tech and all(t in ("None", "Not Supported") for t in tech):
        return False
    return True


def eval_doc_sip_streaming(doc: dict[str, Any]) -> bool:
    """Returns True if SIP streaming is supported in document."""
    caps = doc.get("Capabilities", {})
    return bool(caps.get("Streaming", {}).get("SIPStreaming", False))


def eval_doc_sip_push_to_talk(doc: dict[str, Any]) -> bool:
    """Returns True if SIP push-to-talk is supported in document."""
    caps = doc.get("Capabilities", {})
    return "sip" in caps.get("PushToTalk", {}).get("signal", [])


def eval_doc_full_duplex_talk(doc: dict[str, Any]) -> bool:
    """Returns True if full-duplex push-to-talk is supported in document."""
    caps = doc.get("Capabilities", {})
    return bool(caps.get("PushToTalk", {}).get("fullDuplex", False))


def eval_doc_temperature(doc: dict[str, Any]) -> bool:
    """Returns True if device has ambient temperature sensor."""
    caps = doc.get("Capabilities", {})
    return "TemperatureSensor" in caps.get("AmbientSensors", {})


def eval_doc_humidity(doc: dict[str, Any]) -> bool:
    """Returns True if device has ambient humidity sensor."""
    caps = doc.get("Capabilities", {})
    return "HumiditySensor" in caps.get("AmbientSensors", {})


def eval_doc_air_quality(doc: dict[str, Any]) -> bool:
    """Returns True if device has air quality sensor."""
    caps = doc.get("Capabilities", {})
    return "AirQualitySensor" in caps.get("AmbientSensors", {})


def eval_doc_nightlight(doc: dict[str, Any]) -> bool:
    """Returns True if device has nightlight."""
    caps = doc.get("Capabilities", {})
    return "NightLight" in caps or "Nightlight" in caps


def eval_doc_media_player(doc: dict[str, Any]) -> bool:
    """Returns True if device has audio playback or melodies."""
    caps = doc.get("Capabilities", {})
    return "AudioPlayback" in caps or "Melody" in caps


def supports_sip_streaming(core: Any | None, model_id: str | None, interface_version: int | str | None) -> bool:
    """Returns True if the device supports live SIP/WebRTC streaming.

    Checks cache/storage first. If no capability document is cached,
    falls back to the hardcoded model list.
    """
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is not None and "Capabilities" in cached:
        return eval_doc_sip_streaming(cached)
    return model_id is not None and model_id.upper().startswith(
        tuple(model.upper() for model in FALLBACK_SIP_STREAMING_MODELS)
    )


def supports_sip_push_to_talk(core: Any | None, model_id: str | None, interface_version: int | str | None) -> bool:
    """Returns True if the device signals push-to-talk over SIP."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is None or "Capabilities" not in cached:
        return False
    return eval_doc_sip_push_to_talk(cached)


def has_full_duplex_push_to_talk(core: Any | None, model_id: str | None, interface_version: int | str | None) -> bool:
    """Returns True if the device supports simultaneous talk/listen push-to-talk."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is None or "Capabilities" not in cached:
        return False
    return eval_doc_full_duplex_talk(cached)


def supports_motion_detection(core: Any | None, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    """Returns True if the device supports motion detection."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is not None and "Capabilities" in cached:
        return eval_doc_motion_detection(cached)
    return static_camera_supports(model_id, MOTION_DETECTED_KEY, device_type=device_type)


def supports_audio_detection(core: Any | None, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    """Returns True if the device supports audio detection."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is not None and "Capabilities" in cached:
        return eval_doc_audio_detection(cached)
    return static_camera_supports(model_id, AUDIO_DETECTED_KEY, device_type=device_type)


def supports_siren(core: Any | None, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    """Returns True if the device supports a siren."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is not None and "Capabilities" in cached:
        return eval_doc_siren(cached)
    return static_camera_supports(model_id, SIREN_STATE_KEY, device_type=device_type)


def supports_battery(core: Any | None, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    """Returns True if the device has a battery."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is not None and "Capabilities" in cached:
        return eval_doc_battery(cached)
    return static_camera_supports(model_id, BATTERY_KEY, device_type=device_type)


def supports_spotlight(core: Any | None, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    """Returns True if the device supports a spotlight."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is not None and "Capabilities" in cached:
        return eval_doc_spotlight(cached)
    return static_camera_supports(model_id, SPOTLIGHT_KEY, device_type=device_type)


def supports_floodlight(core: Any | None, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    """Returns True if the device supports a floodlight."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is not None and "Capabilities" in cached:
        return eval_doc_floodlight(cached)
    return static_camera_supports(model_id, FLOODLIGHT_KEY, device_type=device_type)


async def async_supports_sip_streaming(core: ArloCore, model_id: str | None, interface_version: int | str | None) -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    if doc and "Capabilities" in doc:
        return eval_doc_sip_streaming(doc)
    return model_id is not None and model_id.upper().startswith(
        tuple(model.upper() for model in FALLBACK_SIP_STREAMING_MODELS)
    )


async def async_supports_sip_push_to_talk(core: ArloCore, model_id: str | None, interface_version: int | str | None) -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    if not doc or "Capabilities" not in doc:
        return False
    return eval_doc_sip_push_to_talk(doc)


async def async_has_full_duplex_push_to_talk(core: ArloCore, model_id: str | None, interface_version: int | str | None) -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    if not doc or "Capabilities" not in doc:
        return False
    return eval_doc_full_duplex_talk(doc)


async def async_supports_motion_detection(core: ArloCore, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    if doc and "Capabilities" in doc:
        return eval_doc_motion_detection(doc)
    return static_camera_supports(model_id, MOTION_DETECTED_KEY, device_type=device_type)


async def async_supports_audio_detection(core: ArloCore, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    if doc and "Capabilities" in doc:
        return eval_doc_audio_detection(doc)
    return static_camera_supports(model_id, AUDIO_DETECTED_KEY, device_type=device_type)


async def async_supports_siren(core: ArloCore, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    if doc and "Capabilities" in doc:
        return eval_doc_siren(doc)
    return static_camera_supports(model_id, SIREN_STATE_KEY, device_type=device_type)


async def async_supports_battery(core: ArloCore, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    if doc and "Capabilities" in doc:
        return eval_doc_battery(doc)
    return static_camera_supports(model_id, BATTERY_KEY, device_type=device_type)


async def async_supports_spotlight(core: ArloCore, model_id: str | None, interface_version: int | str | None, device_type: str = "camera") -> bool:
    doc = await get_capabilities(core, model_id, interface_version)
    if doc and "Capabilities" in doc:
        return eval_doc_spotlight(doc)
    return static_camera_supports(model_id, SPOTLIGHT_KEY, device_type=device_type)


def dynamic_camera_supports(doc: dict[str, Any], cap: str) -> bool | None:
    """Evaluate whether capability doc indicates support for cap.

    Returns True or False if determined from the document schema.
    Returns None if this capability is not represented in the document
    (in which case caller should fall back to static rules).
    """
    if not doc or "Capabilities" not in doc:
        return None

    if cap == MOTION_DETECTED_KEY:
        return eval_doc_motion_detection(doc)
    if cap == AUDIO_DETECTED_KEY:
        return eval_doc_audio_detection(doc)
    if cap == SIREN_STATE_KEY:
        return eval_doc_siren(doc)
    if cap == SPOTLIGHT_KEY:
        return eval_doc_spotlight(doc)
    if cap == FLOODLIGHT_KEY:
        return eval_doc_floodlight(doc)
    if cap == BATTERY_KEY:
        return eval_doc_battery(doc)
    if cap == SIP_STREAMING_KEY:
        return eval_doc_sip_streaming(doc)
    if cap == SIP_PUSH_TO_TALK_KEY:
        return eval_doc_sip_push_to_talk(doc)
    if cap in (TEMPERATURE_KEY,):
        return eval_doc_temperature(doc)
    if cap in (HUMIDITY_KEY,):
        return eval_doc_humidity(doc)
    if cap in (AIR_QUALITY_KEY,):
        return eval_doc_air_quality(doc)
    if cap in (NIGHTLIGHT_KEY,):
        return eval_doc_nightlight(doc)
    if cap in (MEDIA_PLAYER_KEY,):
        return eval_doc_media_player(doc)

    return None


def static_camera_supports(
    model_id: str | None,
    cap: str,
    device_type: str = "camera",
    parent_id: str | None = None,
    device_id: str | None = None,
) -> bool:
    """Legacy hardcoded model list checks for camera capabilities."""
    if model_id is None:
        return False
    if cap in (SIP_STREAMING_KEY,):
        return model_id.upper().startswith(
            tuple(m.upper() for m in FALLBACK_SIP_STREAMING_MODELS)
        )
    if cap in (SIP_PUSH_TO_TALK_KEY,):
        return False
    if cap in (BATTERY_KEY,):
        if model_id.startswith((
            MODEL_ESSENTIAL_INDOOR,
            MODEL_ESSENTIAL_INDOOR_GEN2_2K,
            MODEL_ESSENTIAL_INDOOR_GEN2_HD,
        )):
            return False
        return True
    if cap in (MOTION_DETECTED_KEY, SIGNAL_STR_KEY):
        return True
    if cap in (LAST_CAPTURE_KEY, CAPTURED_TODAY_KEY, RECENT_ACTIVITY_KEY):
        return True
    if cap in (AUDIO_DETECTED_KEY,):
        if model_id.startswith((
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
        if device_type.startswith("arloq"):
            return True
        return False
    if cap in (SIREN_STATE_KEY,):
        if model_id.startswith((
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
        return False
    if cap in (SPOTLIGHT_KEY,):
        if model_id.startswith((
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
            MODEL_ULTRA,
        )):
            return True
        return False
    if cap in (TEMPERATURE_KEY, HUMIDITY_KEY, AIR_QUALITY_KEY):
        return model_id.startswith(MODEL_BABY)
    if cap in (MEDIA_PLAYER_KEY, NIGHTLIGHT_KEY, CRY_DETECTION_KEY):
        return model_id.startswith(MODEL_BABY)
    if cap in (FLOODLIGHT_KEY,):
        return model_id.startswith((MODEL_PRO_3_FLOODLIGHT, MODEL_WIRED_FLOODLIGHT))
    if cap in (CONNECTION_KEY,):
        if parent_id is not None and device_id is not None and parent_id == device_id:
            if model_id.startswith((
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
        if device_type in ("arloq", "arloqs"):
            return False
        return True
    return False


def eval_doc_resource(doc: dict[str, Any], resource: str) -> bool:
    """Check if the capability document includes the specified resource role."""
    caps = doc.get("Capabilities", {})
    res_types = caps.get("ResourceTypes", [])
    if not isinstance(res_types, list):
        return False

    res_set = {str(r).lower() for r in res_types}
    target = resource.lower().strip()

    if target in ("camera",):
        return "camera" in res_set
    if target in ("gateway", "can_be_own_base_station", "own_base_station"):
        return "gateway" in res_set
    if target in ("basestation", "base_station", "hub"):
        return "gateway" in res_set
    if target in ("doorbell", "audiodoorbell", "audio_doorbell"):
        return "audiodoorbell" in res_set or "doorbell" in res_set
    if target in ("light", "lights"):
        return "light" in res_set or "lights" in res_set
    if target in ("siren",):
        return "siren" in res_set
    if target in ("chime",):
        return "chime" in res_set
    if target in ("sensor", "sensors"):
        return "sensor" in res_set or "sensors" in res_set

    return target in res_set


def static_is_resource(model_id: str | None, resource: str, device_type: str = "") -> bool:
    """Legacy hardcoded rules for determining device resource roles."""
    res = resource.lower().strip()
    mid = model_id or ""
    dtype = device_type.lower().strip()

    if res in ("camera",):
        return (
            dtype in ("camera", "arloq", "arloqs")
            or mid.startswith((
                MODEL_GO,
                MODEL_WIRED_VIDEO_DOORBELL,
                MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
                MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
                MODEL_ESSENTIAL_VIDEO_DOORBELL,
            ))
        )

    if res in ("gateway", "can_be_own_base_station", "own_base_station"):
        return mid.startswith(FALLBACK_OWN_BASE_STATION_MODELS)

    if res in ("basestation", "base_station", "hub"):
        return (
            dtype in ("basestation", "arlobridge", "arloq", "arloqs")
            or dtype == "hub"
            or mid.startswith(MODEL_BABY)
            or mid.startswith(MODEL_GO)
        )

    if res in ("doorbell", "audiodoorbell", "audio_doorbell"):
        return (
            dtype == "doorbell"
            or mid.startswith((
                MODEL_WIRED_VIDEO_DOORBELL,
                MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
                MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
                MODEL_ESSENTIAL_VIDEO_DOORBELL,
            ))
        )

    if res in ("light", "lights"):
        return (
            dtype in ("lights", "light")
            or mid.startswith((MODEL_PRO_3_FLOODLIGHT, MODEL_WIRED_FLOODLIGHT))
        )

    if res in ("sensor", "sensors"):
        return dtype in ("sensors", "sensor")

    if res == "chime":
        return dtype in ("chime", "chimes")

    if res == "siren":
        return (
            dtype == "siren"
            or mid.startswith(("VMB400", "VMB450"))
            or mid == MODEL_GO
            or static_camera_supports(model_id, SIREN_STATE_KEY, device_type=device_type)
        )

    return False


def is_resource(
    core: Any | None,
    model_id: str | None,
    interface_version: int | str | None,
    resource: str,
    device_type: str = "",
) -> bool:
    """Returns True if the device supports the specified resource role."""
    cached = get_cached_capabilities(core, model_id, interface_version)
    if cached is not None and "Capabilities" in cached:
        caps = cached.get("Capabilities", {})
        if "ResourceTypes" in caps and isinstance(caps.get("ResourceTypes"), list):
            return eval_doc_resource(cached, resource)
    return static_is_resource(model_id, resource, device_type=device_type)


class ArloTypes:
    """Arlo device types.

    Delegates to is_resource() with static fallbacks.
    Maintained for backwards compatibility.
    """

    @staticmethod
    def is_a_base_station(device_type: str, model_id: str, core: Any | None = None, interface_version: Any | None = None) -> bool:
        return is_resource(core, model_id, interface_version, "basestation", device_type=device_type)

    @staticmethod
    def can_be_own_base_station(model_id: str, core: Any | None = None, interface_version: Any | None = None) -> bool:
        return is_resource(core, model_id, interface_version, "gateway")

    @staticmethod
    def is_a_camera(device_type: str, model_id: str, core: Any | None = None, interface_version: Any | None = None) -> bool:
        return is_resource(core, model_id, interface_version, "camera", device_type=device_type)


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
        core = getattr(base_station, "_core", None)
        model_id = getattr(base_station, "model_id", None)
        interface_version = getattr(base_station, "interface_version", None)
        doc = get_cached_capabilities(core, model_id, interface_version)
        if doc and "Capabilities" in doc:
            if cap in (TEMPERATURE_KEY, HUMIDITY_KEY, AIR_QUALITY_KEY):
                val = dynamic_camera_supports(doc, cap)
                if val is not None:
                    return val
            if cap in (SIREN_STATE_KEY,):
                return eval_doc_siren(doc)

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
        core = getattr(camera, "_core", None)
        model_id = getattr(camera, "model_id", None)
        interface_version = getattr(camera, "interface_version", None)
        doc = get_cached_capabilities(core, model_id, interface_version)
        if doc and "Capabilities" in doc:
            dyn = dynamic_camera_supports(doc, cap)
            if dyn is not None:
                return dyn
        return static_camera_supports(
            model_id,
            cap,
            device_type=getattr(camera, "device_type", "camera"),
            parent_id=getattr(camera, "parent_id", None),
            device_id=getattr(camera, "device_id", None),
        )

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
        core = getattr(light, "_core", None)
        model_id = getattr(light, "model_id", None)
        interface_version = getattr(light, "interface_version", None)
        doc = get_cached_capabilities(core, model_id, interface_version)
        if doc and "Capabilities" in doc:
            if cap == MOTION_DETECTED_KEY:
                return eval_doc_motion_detection(doc)
            if cap == BATTERY_KEY:
                return eval_doc_battery(doc)
            if cap == SPOTLIGHT_KEY:
                return True
        if cap in (MOTION_DETECTED_KEY, BATTERY_KEY):
            return True
        return ArloCapabilities._check_child_supports(light, cap)
