import pprint

from .constant import (
    BATTERY_KEY,
    BRIGHTNESS_KEY,
    LAMP_STATE_KEY,
    MOTION_DETECTED_KEY
)
from .capabilities import ArloCapabilities
from .core import ArloCore
from .child_device import ArloChildDevice
from .objects import ArloObjects


class ArloLight(ArloChildDevice):
    def __init__(self, name: str, core: ArloCore, objs: ArloObjects, attrs):
        """An Arlo Light.

        :param name: name of light
        :param attrs: initial attributes give by Arlo
        """
        super().__init__(name, core, objs, attrs)

    @property
    def resource_type(self):
        return "lights"

    def _event_handler(self, resource, event):
        self.debug(self.name + " LIGHT got one " + resource)

        # pass on to lower layer
        super()._event_handler(resource, event)

    @property
    def is_on(self):
        return self._load(LAMP_STATE_KEY, "off") == "on"

    def turn_on(self, brightness=None, rgb=None):
        """Turn the light on.

        :param brightness: how bright to make the light
        :param rgb: what color to make the light
        """
        properties = {LAMP_STATE_KEY: "on"}
        if brightness is not None:
            properties[BRIGHTNESS_KEY] = brightness
        if rgb is not None:
            # properties["single"] = rgb_to_hex(rgb)
            pass

        self.debug("{} sending {}".format(self._name, pprint.pformat(properties)))
        self._core.be.notify(
            device_id=self.base_station.device_id,
            xcloud_id=self.base_station.xcloud_id,
            body={
                "action": "set",
                "properties": properties,
                "publishResponse": True,
                "resource": self.resource_id,
            },
        )
        return True

    def turn_off(self):
        """Turn the light off."""
        self._core.be.notify(
            device_id=self.base_station.device_id,
            xcloud_id=self.base_station.xcloud_id,
            body={
                "action": "set",
                "properties": {LAMP_STATE_KEY: "off"},
                "publishResponse": True,
                "resource": self.resource_id,
            },
        )
        return True

    def set_brightness(self, brightness):
        """Set the light brightness.

        :param brightness: brightness to use (0-255)
        """
        self._core.be.notify(
            device_id=self.base_station.device_id,
            xcloud_id=self.base_station.xcloud_id,
            body={
                "action": "set",
                "properties": {BRIGHTNESS_KEY: brightness},
                "publishResponse": True,
                "resource": self.resource_id,
            },
        )
        return True

    def has_capability(self, cap) -> bool:
        supports = ArloCapabilities.check_light_supports(self, cap)
        self.debug(f"supports {cap} is {supports}")
        return supports
