from __future__ import annotations


# noinspection PyUnresolvedReferences
class ArloObjects:
    """The list of objects we know about.

    This relies on the future annotations to work. It allows us to break
    the linkage.
    """
    bases: list[ArloBase] = []
    cameras: list[ArloCamera] = []
    locations: list[ArloLocation] = []
    lights: list[ArloLight] = []
    doorbells: list[ArloDoorBell] = []
    sensors: list[ArloSensor] = []

    ml: ArloMediaLibrary | None = None

    # Will never exist...
    # XXX remove after testing...
    _roygbivs: list[ArloRoygbivs] = []
