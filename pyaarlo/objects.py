from __future__ import annotations

from typing import List, Union, TYPE_CHECKING

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
    def __init__(self):
        self.base_stations: List[ArloBaseStation] = []
        self.cameras: List[ArloCamera] = []
        self.locations: List[ArloLocation] = []
        self.lights: List[ArloLight] = []
        self.doorbells: List[ArloDoorBell] = []
        self.sensors: List[ArloSensor] = []
    
        self.ml: Union[ArloMediaLibrary, None] = None
