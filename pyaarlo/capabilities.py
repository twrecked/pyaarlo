from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
    MODEL_PRO_4,
    MODEL_PRO_5,
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
)


class ArloCapabilities:
    """Arlo device capabilities.

    These methods are used by instances of objects to determine their
    capabilities.

    They have been moved into this umbrella class to:
     - move the knowledge into one place, hopefully making it easier to edit
     - reduce some of the clutter in the object clases
    """

    @staticmethod
    def _device_has(_device: ArloDevice, cap: str) -> bool:
        if cap in (CONNECTION_KEY,):
            return True
        return False

    @staticmethod
    def _child_device_has(child_device: ArloChildDevice, cap: str) -> bool:
        return ArloCapabilities._device_has(child_device, cap)

    @staticmethod
    def base_station_has(base_station: ArloBaseStation, cap: str):
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
                    MODEL_PRO_4,
                    MODEL_PRO_5,
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
        return ArloCapabilities._device_has(base_station, cap)

    @staticmethod
    def check_camera_supports(camera: ArloCamera, cap: str) -> bool:
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
                    MODEL_PRO_4,
                    MODEL_PRO_5,
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
                    MODEL_PRO_4,
                    MODEL_PRO_5,
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
            if camera.model_id.startswith(MODEL_PRO_3_FLOODLIGHT):
                return True
        if cap in (CONNECTION_KEY,):
            # These devices are their own base stations so don't re-add connection key.
            if camera.parent_id == camera.device_id and camera.model_id.startswith((
                    MODEL_BABY,
                    MODEL_PRO_3_FLOODLIGHT,
                    MODEL_PRO_4,
                    MODEL_PRO_5,
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
        return ArloCapabilities._child_device_has(camera, cap)

    @staticmethod
    def doorbell_has(doorbell: ArloDoorBell, cap: str):
        # Video Doorbells appear as both ArloCameras and ArloDoorBells, where
        # capabilities double up - eg, motion detection - we provide the
        # capability at the camera level.
        if cap in (MOTION_DETECTED_KEY, BATTERY_KEY, SIGNAL_STR_KEY, CONNECTION_KEY):
            return not doorbell.is_video_doorbell
        if cap in (BUTTON_PRESSED_KEY, SILENT_MODE_KEY):
            return True
        return ArloCapabilities._child_device_has(doorbell, cap)

    @staticmethod
    def sensor_has(_sensor: ArloSensor, cap: str):
        if cap in (ALS_STATE_KEY, BATTERY_KEY, CONTACT_STATE_KEY, MOTION_DETECTED_KEY,
                   TAMPER_STATE_KEY, TEMPERATURE_KEY):
            return True
        return False

    @staticmethod
    def light_has(light: ArloLight, cap: str ):
        if cap in (MOTION_DETECTED_KEY, BATTERY_KEY):
            return True
        return ArloCapabilities._child_device_has(light, cap)
