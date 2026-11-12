from __future__ import annotations

import pprint
from typing import TYPE_CHECKING, Any

from .constant import (
    BRIGHTNESS_KEY,
    CONNECTION_KEY,
    FLOODLIGHT_BRIGHTNESS1_KEY,
    FLOODLIGHT_BRIGHTNESS2_KEY,
    FLOODLIGHT_KEY,
    LAMP_STATE_KEY,
    SPOTLIGHT_BRIGHTNESS_KEY,
    SPOTLIGHT_KEY,
)
from .capabilities import ArloCapabilities
from .child_device import ArloChildDevice

if TYPE_CHECKING:
    from .core import ArloCore
    from .objects import ArloObjects


class ArloLight(ArloChildDevice):
    def __init__(
        self,
        name: str,
        core: ArloCore,
        objs: ArloObjects,
        attrs: dict[str, Any],
        parent_name: str | None = None,
        light_type: str = "light",
    ) -> None:
        """An Arlo Light (standalone light, camera spotlight, or camera floodlight).

        :param name: name of light
        :param core: ArloCore instance
        :param objs: ArloObjects instance
        :param attrs: initial attributes given by Arlo
        :param parent_name: optional friendly name of parent device
        :param light_type: 'light', 'spotlight', or 'floodlight'
        """
        self._light_type = light_type
        self.parent_name = parent_name or attrs.get("deviceName", name)
        super().__init__(name, core, objs, attrs)

        # Initialise state from attributes if available
        props = attrs.get("properties", {})
        if isinstance(props, dict):
            if SPOTLIGHT_KEY in props:
                sp = props[SPOTLIGHT_KEY]
                if isinstance(sp, dict):
                    enabled = sp.get("enabled", False)
                    self._save(SPOTLIGHT_KEY, "on" if enabled else "off")
                    self._save(LAMP_STATE_KEY, "on" if enabled else "off")
                    intensity = sp.get("intensity")
                    if intensity is not None:
                        self._save(SPOTLIGHT_BRIGHTNESS_KEY, intensity)
                        self._save(BRIGHTNESS_KEY, int(intensity / 100 * 255))
            if FLOODLIGHT_KEY in props:
                fl = props[FLOODLIGHT_KEY]
                if isinstance(fl, dict):
                    self._save(FLOODLIGHT_KEY, fl)
                    on_val = fl.get("on", False)
                    self._save(LAMP_STATE_KEY, "on" if on_val else "off")
                    b_val = fl.get(FLOODLIGHT_BRIGHTNESS1_KEY)
                    if b_val is not None:
                        self._save(BRIGHTNESS_KEY, int(b_val / 100 * 255))

    @property
    def resource_type(self) -> str:
        lt = getattr(self, "_light_type", "light")
        if lt in ("spotlight", "floodlight") or getattr(self, "device_type", "") == "camera":
            return "cameras"
        return "lights"

    @property
    def _notify_device_id(self) -> str:
        if self.base_station:
            return self.base_station.device_id
        return self.device_id

    @property
    def _notify_xcloud_id(self) -> str:
        if self.base_station:
            return self.base_station.xcloud_id
        return self.xcloud_id

    @property
    def is_spotlight(self) -> bool:
        return self._light_type == "spotlight"

    @property
    def is_floodlight(self) -> bool:
        return self._light_type == "floodlight"

    def _event_handler(self, resource: str, event: dict[str, Any]) -> None:
        self.debug(self.name + " LIGHT got one " + resource)
        props = event.get("properties", event)
        if isinstance(props, dict):
            spotlight = props.get(SPOTLIGHT_KEY, None)
            if spotlight is not None and isinstance(spotlight, dict):
                enabled = spotlight.get("enabled", False)
                self._save_and_do_callbacks(SPOTLIGHT_KEY, "on" if enabled else "off")
                self._save_and_do_callbacks(LAMP_STATE_KEY, "on" if enabled else "off")
                intensity = spotlight.get("intensity")
                if intensity is not None:
                    self._save_and_do_callbacks(SPOTLIGHT_BRIGHTNESS_KEY, intensity)
                    self._save_and_do_callbacks(BRIGHTNESS_KEY, int(intensity / 100 * 255))

            floodlight = props.get(FLOODLIGHT_KEY, None)
            if floodlight is not None and isinstance(floodlight, dict):
                self._save_and_do_callbacks(FLOODLIGHT_KEY, floodlight)
                on_val = floodlight.get("on", False)
                self._save_and_do_callbacks(LAMP_STATE_KEY, "on" if on_val else "off")
                b_val = floodlight.get(FLOODLIGHT_BRIGHTNESS1_KEY)
                if b_val is not None:
                    self._save_and_do_callbacks(BRIGHTNESS_KEY, int(b_val / 100 * 255))

        # pass on to lower layer
        super()._event_handler(resource, event)

    @property
    def is_on(self) -> bool:
        if self.is_floodlight:
            fl = self._load(FLOODLIGHT_KEY, {})
            if isinstance(fl, dict) and "on" in fl:
                return bool(fl.get("on", False))
        if self.is_spotlight:
            return self._load(SPOTLIGHT_KEY, "off") == "on"
        return self._load(LAMP_STATE_KEY, "off") == "on"

    @is_on.setter
    def is_on(self, value: bool) -> None:
        self._core.tasks.run_now(self.set_is_on, value=value)

    async def set_is_on(self, value: bool) -> None:
        """Set the light on/off state."""
        if value:
            await self.turn_on()
        else:
            await self.turn_off()

    @property
    def brightness(self) -> int | None:
        """Returns the light brightness (0-255)."""
        if self.is_floodlight:
            fl = self._load(FLOODLIGHT_KEY, {})
            if isinstance(fl, dict):
                b = fl.get(FLOODLIGHT_BRIGHTNESS1_KEY)
                if b is not None:
                    return int(b / 100 * 255)
        if self.is_spotlight:
            intensity = self._load(SPOTLIGHT_BRIGHTNESS_KEY, None)
            if intensity is not None:
                return int(intensity / 100 * 255)
        return self._load(BRIGHTNESS_KEY, None)

    @brightness.setter
    def brightness(self, value: int) -> None:
        """Set the light brightness (sync wrapper)."""
        self._core.tasks.run_now(self.set_brightness, brightness=value)

    async def turn_on(self, brightness: int | None = None, rgb: Any | None = None) -> bool:
        """Turn the light on.

        :param brightness: how bright to make the light (0-255)
        :param rgb: what color to make the light
        """
        if self.is_spotlight:
            props: dict[str, Any] = {"enabled": True}
            if brightness is not None:
                props["intensity"] = int(brightness / 255 * 100)
            self.debug(f"{self._name} sending spotlight {props}")
            await self._core.be.notify(
                device_id=self._notify_device_id,
                xcloud_id=self._notify_xcloud_id,
                body={
                    "action": "set",
                    "properties": {SPOTLIGHT_KEY: props},
                    "publishResponse": True,
                    "resource": self.resource_id,
                },
            )
            return True

        if self.is_floodlight:
            fl_props: dict[str, Any] = {"on": True}
            if brightness is not None:
                pct = int(brightness / 255 * 100)
                fl_props[FLOODLIGHT_BRIGHTNESS1_KEY] = pct
                fl_props[FLOODLIGHT_BRIGHTNESS2_KEY] = pct
            self.debug(f"{self._name} sending floodlight {fl_props}")
            await self._core.be.notify(
                device_id=self._notify_device_id,
                xcloud_id=self._notify_xcloud_id,
                body={
                    "action": "set",
                    "properties": {FLOODLIGHT_KEY: fl_props},
                    "publishResponse": True,
                    "resource": self.resource_id,
                },
            )
            return True

        properties: dict[str, Any] = {LAMP_STATE_KEY: "on"}
        if brightness is not None:
            properties[BRIGHTNESS_KEY] = brightness
        if rgb is not None:
            # properties["single"] = rgb_to_hex(rgb)
            pass

        self.debug("{} sending {}".format(self._name, pprint.pformat(properties)))
        await self._core.be.notify(
            device_id=self._notify_device_id,
            xcloud_id=self._notify_xcloud_id,
            body={
                "action": "set",
                "properties": properties,
                "publishResponse": True,
                "resource": self.resource_id,
            },
        )
        return True

    async def turn_off(self) -> bool:
        """Turn the light off."""
        if self.is_spotlight:
            self.debug(f"{self._name} turning spotlight off")
            await self._core.be.notify(
                device_id=self._notify_device_id,
                xcloud_id=self._notify_xcloud_id,
                body={
                    "action": "set",
                    "properties": {SPOTLIGHT_KEY: {"enabled": False}},
                    "publishResponse": True,
                    "resource": self.resource_id,
                },
            )
            return True

        if self.is_floodlight:
            self.debug(f"{self._name} turning floodlight off")
            await self._core.be.notify(
                device_id=self._notify_device_id,
                xcloud_id=self._notify_xcloud_id,
                body={
                    "action": "set",
                    "properties": {FLOODLIGHT_KEY: {"on": False}},
                    "publishResponse": True,
                    "resource": self.resource_id,
                },
            )
            return True

        await self._core.be.notify(
            device_id=self._notify_device_id,
            xcloud_id=self._notify_xcloud_id,
            body={
                "action": "set",
                "properties": {LAMP_STATE_KEY: "off"},
                "publishResponse": True,
                "resource": self.resource_id,
            },
        )
        return True

    async def set_brightness(self, brightness: int) -> bool:
        """Set the light brightness.

        :param brightness: brightness to use (0-255)
        """
        if self.is_spotlight:
            intensity = int(brightness / 255 * 100)
            self.debug(f"{self._name} setting spotlight brightness {intensity}%")
            await self._core.be.notify(
                device_id=self._notify_device_id,
                xcloud_id=self._notify_xcloud_id,
                body={
                    "action": "set",
                    "properties": {SPOTLIGHT_KEY: {"intensity": intensity}},
                    "publishResponse": True,
                    "resource": self.resource_id,
                },
            )
            return True

        if self.is_floodlight:
            pct = int(brightness / 255 * 100)
            self.debug(f"{self._name} setting floodlight brightness {pct}%")
            await self._core.be.notify(
                device_id=self._notify_device_id,
                xcloud_id=self._notify_xcloud_id,
                body={
                    "action": "set",
                    "properties": {
                        FLOODLIGHT_KEY: {
                            FLOODLIGHT_BRIGHTNESS1_KEY: pct,
                            FLOODLIGHT_BRIGHTNESS2_KEY: pct,
                        }
                    },
                    "publishResponse": True,
                    "resource": self.resource_id,
                },
            )
            return True

        await self._core.be.notify(
            device_id=self._notify_device_id,
            xcloud_id=self._notify_xcloud_id,
            body={
                "action": "set",
                "properties": {BRIGHTNESS_KEY: brightness},
                "publishResponse": True,
                "resource": self.resource_id,
            },
        )
        return True

    def has_capability(self, cap: str) -> bool:
        if self.is_spotlight and cap in (
            LAMP_STATE_KEY,
            BRIGHTNESS_KEY,
            SPOTLIGHT_KEY,
            SPOTLIGHT_BRIGHTNESS_KEY,
            CONNECTION_KEY,
        ):
            return True
        if self.is_floodlight and cap in (
            LAMP_STATE_KEY,
            BRIGHTNESS_KEY,
            FLOODLIGHT_KEY,
            FLOODLIGHT_BRIGHTNESS1_KEY,
            FLOODLIGHT_BRIGHTNESS2_KEY,
            CONNECTION_KEY,
        ):
            return True
        supports = ArloCapabilities.check_light_supports(self, cap)
        self.vdebug(f"supports {cap} is {supports}")
        return supports
