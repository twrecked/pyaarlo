
from .constant import (
    CONNECTION_KEY,
)
from .device import ArloDevice


class ArloChildDevice(ArloDevice):
    """Base class for all Arlo devices that attach to a base station."""

    def __init__(self, name, arlo, attrs):
        super().__init__(name, arlo, attrs)

        self.debug("parent is {}".format(self._parent_id))
        self.vdebug("resource is {}".format(self.resource_id))

    def _event_handler(self, resource, event):
        self.vdebug("{}: child got {} event **".format(self.name, resource))

        if resource.endswith("/states"):
            self._arlo.bg.run(self.base_station.update_mode)
            return

        # Pass event to lower level.
        super()._event_handler(resource, event)

    @property
    def resource_type(self):
        """Return the resource type this child device describes.

        Currently limited to `camera`, `doorbell` and `light`.
        """
        return "child"

    @property
    def resource_id(self):
        """Returns the child device resource id.

        Some devices - certain cameras - can provide other types.
        """
        return self.resource_type + "/" + self.device_id

    @property
    def parent_id(self):
        """Returns the parent device id.

        **Note:** Some devices - ArloBaby for example - are their own parents.
        """
        if self._parent_id is not None:
            return self._parent_id
        return self.device_id

    @property
    def timezone(self):
        """Returns the timezone.

        Tries to be clever. If it doesn't have a timezone it will try its
        basestation.
        """
        time_zone = super().timezone
        if time_zone is None:
            return self.base_station.timezone
        return time_zone

    @property
    def base_station(self):
        """Returns the base station controlling this device.

        Some devices - ArloBaby for example - are their own parents. If we
        can't find a basestation, this returns the first one (if any exist).
        """
        # look for real parents
        for base in self._arlo.base_stations:
            if base.device_id == self.parent_id:
                return base

        # some cameras don't have base stations... it's its own base station...
        for base in self._arlo.base_stations:
            if base.device_id == self.device_id:
                return base

        # no idea!
        if len(self._arlo.base_stations) > 0:
            return self._arlo.base_stations[0]

        self._arlo.error("Could not find any base stations for device " + self._name)
        return None

    @property
    def is_unavailable(self):
        if not self.base_station:
            return True

        return (
                self.base_station.is_unavailable
                or self._load(CONNECTION_KEY, "unknown") == "unavailable"
        )

    @property
    def too_cold(self):
        """Returns `True` if the device too cold to operate, `False` otherwise."""
        return self._load(CONNECTION_KEY, "unknown") == "thermalShutdownCold"

    @property
    def state(self):
        if self.is_unavailable:
            return "unavailable"
        if not self.is_on:
            return "off"
        if self.too_cold:
            return "offline, too cold"
        return "idle"
