
from .constant import (
    MODEL_BABY,
    MODEL_ESSENTIAL_SPOTLIGHT,
    MODEL_ESSENTIAL_XL_SPOTLIGHT,
    MODEL_ESSENTIAL_INDOOR,
    MODEL_ESSENTIAL_INDOOR_GEN2_2K,
    MODEL_ESSENTIAL_INDOOR_GEN2_HD,
    MODEL_PRO_3_FLOODLIGHT,
    MODEL_PRO_4,
    MODEL_PRO_5,
    MODEL_WIRED_VIDEO_DOORBELL,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
    MODEL_ESSENTIAL_VIDEO_DOORBELL,
    MODEL_GO,
    MODEL_GO_2,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
)


class ArloTypes:
    """Arlo device types.

    These methods are used at start up to determine what objec type to create
    for devices we read from the Arlo servers.

    These were moved here to remove some of code clutter in __init__.py.
    """

    @staticmethod
    def is_a_base_station(device_type: str, model_id: str) -> bool:
        """Is the device a base station.
        """
        return (
                device_type == "basestation" or
                device_type == "arlobridge" or
                device_type.lower() == 'hub' or
                device_type == "arloq" or
                device_type == "arloqs" or
                model_id.startswith(MODEL_BABY) or
                model_id.startswith(MODEL_GO)
        )

    @staticmethod
    def can_be_own_base_station(model_id: str) -> bool:
        """Can the device be a base station.

        Some cameras can be their own base stations. We still need to run extra tests
        but this tell is if we should bother or not.
        """
        return model_id.startswith((
            MODEL_WIRED_VIDEO_DOORBELL,
            MODEL_PRO_3_FLOODLIGHT,
            MODEL_PRO_4,
            MODEL_PRO_5,
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
            MODEL_GO_2
        ))

    @staticmethod
    def is_a_camera(device_type: str, model_id: str) -> bool:
        """Is the device a camera.
        """
        return (
                device_type == "camera" or
                device_type == "arloq" or
                device_type == "arloqs" or
                model_id.startswith((
                    MODEL_GO,
                    MODEL_WIRED_VIDEO_DOORBELL,
                    MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
                    MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
                    MODEL_ESSENTIAL_VIDEO_DOORBELL
                ))
        )
