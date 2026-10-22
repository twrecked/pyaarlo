
from .constant import (
    ALS_STATE_KEY,
    CONTACT_STATE_KEY,
    MOTION_STATE_KEY,
    TAMPER_STATE_KEY,
    TEMPERATURE_KEY,
    WATER_STATE_KEY,
)
from .capabilities import ArloCapabilities
from .core import ArloCore
from .child_device import ArloChildDevice
from .objects import ArloObjects


class ArloSensor(ArloChildDevice):
    def __init__(self, name: str, core: ArloCore, objs: ArloObjects, attrs):
        """An Arlo All-in-One Sensor.

        Currently we handle light level, battery, open/close, motion,
        tamper, temperature and water states.

        :param name: name of sensor
        :param attrs: initial attributes give by Arlo
        """
        super().__init__(name, core, objs, attrs)

    @property
    def resource_type(self):
        return "sensors"

    def _event_handler(self, resource, event):
        self.debug(self.name + " SENSOR got one " + resource)

        # pass on to lower layer
        super()._event_handler(resource, event)

    @property
    def has_motion(self):
        """Returns True if motion is currently detected by the sensor."""
        return self._load(MOTION_STATE_KEY, False)

    @property
    def is_open(self):
        """Returns True if sensor contact is open (e.g. door/window open)."""
        return self._load(CONTACT_STATE_KEY, False)

    @property
    def is_wet(self):
        """Returns True if water or leak is detected by the sensor."""
        return self._load(WATER_STATE_KEY, False)

    @property
    def is_low_light(self):
        """Returns True if ambient light sensor reports low light."""
        return self._load(ALS_STATE_KEY, False)

    @property
    def is_being_tampered_with(self):
        """Returns True if the sensor tamper switch has been activated."""
        return self._load(TAMPER_STATE_KEY, False)

    @property
    def temperature(self):
        """Returns the current ambient temperature reading, or None if unavailable."""
        return self._load(TEMPERATURE_KEY, None)

    def has_capability(self, cap) -> bool:
        supports = ArloCapabilities.check_sensor_supports(self, cap)
        self.vdebug(f"supports {cap} is {supports}")
        return supports
