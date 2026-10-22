import pprint

from .constant import (
    BRIGHTNESS_KEY,
    LAMP_STATE_KEY,
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

    @is_on.setter
    def is_on(self, value: bool):
        self._core.tasks.run_now(self.set_is_on, value=value)

    async def set_is_on(self, value: bool):
        """Set the light on/off state."""
        if value:
            await self.turn_on()
        else:
            await self.turn_off()

    @property
    def brightness(self):
        """Returns the light brightness."""
        return self._load(BRIGHTNESS_KEY, None)

    @brightness.setter
    def brightness(self, value: int):
        """Set the light brightness (sync wrapper)."""
        self._core.tasks.run_now(self.set_brightness, brightness=value)

    async def turn_on(self, brightness=None, rgb=None):
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
        await self._core.be.notify(
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

    async def turn_off(self):
        """Turn the light off."""
        await self._core.be.notify(
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

    async def set_brightness(self, brightness):
        """Set the light brightness.

        :param brightness: brightness to use (0-255)
        """
        await self._core.be.notify(
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
        self.vdebug(f"supports {cap} is {supports}")
        return supports
