from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base_station import ArloBaseStation
    from .camera import ArloCamera
    from .doorbell import ArloDoorBell
    from .light import ArloLight
    from .location import ArloLocation
    from .media import ArloMediaLibrary
    from .sensor import ArloSensor


class ArloObjects:
    """The list of objects we know about.

    XXX This introduces a circular dependency because some objects need to
        know about other objects.  I'll think of a way to break this.
    """
    base_stations: list[ArloBaseStation] = []
    cameras: list[ArloCamera] = []
    locations: list[ArloLocation] = []
    lights: list[ArloLight] = []
    doorbells: list[ArloDoorBell] = []
    sensors: list[ArloSensor] = []

    ml: ArloMediaLibrary | None = None
