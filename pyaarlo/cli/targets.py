from __future__ import annotations

from typing import Any


def parse_targets(target_args: tuple[str, ...] | list[str]) -> list[str]:
    """Parse multiple target arguments and comma-separated target strings.

    Example: ("garage light, porch light", "patio") -> ["garage light", "porch light", "patio"]
    """
    targets: list[str] = []
    for arg in target_args:
        if not arg:
            continue
        # Split on commas
        parts = arg.split(",")
        for part in parts:
            cleaned = part.strip()
            if cleaned and cleaned not in targets:
                targets.append(cleaned)
    return targets


def match_device(device: Any, identifier: str) -> bool:
    """Check if device matches given identifier (by device_id, serial_number, or name)."""
    id_lower = identifier.lower().strip()

    # If dict from cache
    if isinstance(device, dict):
        dev_id = str(device.get("id", "")).lower()
        dev_name = str(device.get("name", "")).lower()
        dev_sn = str(device.get("serial_number", "")).lower()
        return id_lower in (dev_id, dev_name, dev_sn)

    # If PyArlo device object
    dev_id = str(getattr(device, "device_id", "")).lower()
    dev_name = str(getattr(device, "name", "")).lower()
    dev_sn = str(getattr(device, "serial_number", "")).lower()
    return id_lower in (dev_id, dev_name, dev_sn)


def resolve_devices(candidates: list[Any], targets: list[str]) -> tuple[list[Any], list[str]]:
    """Resolve a list of target names or IDs against candidates.

    Returns:
        (matched_devices, missing_targets)
    """
    matched: list[Any] = []
    missing: list[str] = []

    for target in targets:
        found = False
        for dev in candidates:
            if match_device(dev, target):
                if dev not in matched:
                    matched.append(dev)
                found = True
        if not found:
            missing.append(target)

    return matched, missing


def match_location(location: Any, identifier: str) -> bool:
    """Check if location matches identifier (by id or name)."""
    id_lower = identifier.lower().strip()
    if isinstance(location, dict):
        loc_id = str(location.get("id", "")).lower()
        loc_name = str(location.get("name", "")).lower()
        return id_lower in (loc_id, loc_name)

    loc_id = str(getattr(location, "device_id", getattr(location, "id", ""))).lower()
    loc_name = str(getattr(location, "name", "")).lower()
    return id_lower in (loc_id, loc_name)


def resolve_location(locations: list[Any], target: str | None = None) -> Any | None:
    """Resolve a location from available locations.

    If target is None, returns the single location if exactly one exists.
    """
    if not locations:
        return None
    if target is None:
        if len(locations) == 1:
            return locations[0]
        return None

    for loc in locations:
        if match_location(loc, target):
            return loc
    return None
