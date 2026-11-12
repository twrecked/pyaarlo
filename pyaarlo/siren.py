from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .constant import (
    CONNECTION_KEY,
    SIREN_STATE_KEY,
)
from .capabilities import ArloCapabilities
from .child_device import ArloChildDevice

if TYPE_CHECKING:
    from .core import ArloCore
    from .objects import ArloObjects


class ArloSiren(ArloChildDevice):
    def __init__(
        self,
        name: str,
        core: ArloCore,
        objs: ArloObjects,
        attrs: dict[str, Any],
        parent_name: str | None = None,
    ) -> None:
        """An Arlo Siren.

        :param name: friendly name of the siren
        :param core: ArloCore instance
        :param objs: ArloObjects instance
        :param attrs: initial attributes given by Arlo
        :param parent_name: optional friendly name of parent camera/base station
        """
        super().__init__(name, core, objs, attrs)
        self.parent_name = parent_name or attrs.get("deviceName", name)

    @property
    def resource_type(self) -> str:
        return "siren"

    @property
    def _siren_resource_id(self) -> str:
        if self.device_type in ("basestation", "arlobridge") or (
            self.model_id and self.model_id.startswith(("VMB", "VZC"))
        ):
            return "siren"
        return f"siren/{self.device_id}"

    @property
    def siren_state(self) -> str:
        """Returns the current siren state ('on' or 'off')."""
        return self._load(SIREN_STATE_KEY, "off")

    @siren_state.setter
    def siren_state(self, state: str | bool) -> None:
        self._core.tasks.run_now(self.set_siren_state, state=state)

    @property
    def is_on(self) -> bool:
        """Returns True if the siren is currently sounding, False otherwise."""
        return self.siren_state == "on"

    @is_on.setter
    def is_on(self, value: bool) -> None:
        self._core.tasks.run_now(self.set_is_on, value=value)

    async def set_is_on(self, value: bool) -> None:
        """Set the siren on/off state."""
        if value:
            await self.turn_on()
        else:
            await self.turn_off()

    async def set_siren_state(self, state: str | bool, duration: int = 300, volume: int = 8) -> None:
        """Set siren state with optional duration and volume."""
        if state in ("on", True):
            await self.turn_on(duration=duration, volume=volume)
        else:
            await self.turn_off()

    async def turn_on(self, duration: int = 300, volume: int = 8) -> bool:
        """Turn the siren on.

        :param duration: duration in seconds (default 300)
        :param volume: volume level from 1 to 8 (default 8)
        """
        body = {
            "action": "set",
            "resource": self._siren_resource_id,
            "publishResponse": True,
            "properties": {
                "sirenState": "on",
                "duration": int(duration),
                "volume": int(volume),
                "pattern": "alarm",
            },
        }
        self.debug(f"Turning siren on: {body}")
        await self._core.be.notify(
            device_id=self.device_id,
            xcloud_id=self.xcloud_id,
            body=body,
        )
        return True

    async def turn_off(self) -> bool:
        """Turn the siren off."""
        body = {
            "action": "set",
            "resource": self._siren_resource_id,
            "publishResponse": True,
            "properties": {"sirenState": "off"},
        }
        self.debug(f"Turning siren off: {body}")
        await self._core.be.notify(
            device_id=self.device_id,
            xcloud_id=self.xcloud_id,
            body=body,
        )
        return True

    def has_capability(self, cap: str) -> bool:
        if cap in (SIREN_STATE_KEY, CONNECTION_KEY):
            return True
        return False
