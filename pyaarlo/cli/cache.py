from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .config import get_default_cache_path

if TYPE_CHECKING:
    from pyaarlo import PyArlo


def load_cache(cache_path: Path | str | None = None) -> dict[str, Any] | None:
    """Load cached device and location data from JSON file."""
    path = Path(cache_path) if cache_path is not None else get_default_cache_path()
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        return None
    return None


def save_cache(cache_data: dict[str, Any], cache_path: Path | str | None = None) -> Path:
    """Save cache data to JSON file."""
    path = Path(cache_path) if cache_path is not None else get_default_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2)
    return path


def clear_cache(cache_path: Path | str | None = None) -> bool:
    """Delete the cache file if it exists."""
    path = Path(cache_path) if cache_path is not None else get_default_cache_path()
    if path.is_file():
        try:
            path.unlink()
            return True
        except Exception:
            return False
    return False


def is_cache_stale(cache_data: dict[str, Any] | None, ttl_seconds: float = 86400.0) -> bool:
    """Check if cache data is None, empty, or older than ttl_seconds."""
    if not cache_data or not isinstance(cache_data, dict):
        return True
    timestamp = cache_data.get("timestamp", 0)
    if not isinstance(timestamp, (int, float)):
        return True
    return (time.time() - timestamp) > ttl_seconds


def fill_cache(arlo: PyArlo, cache_path: Path | str | None = None) -> dict[str, Any]:
    """Extract devices and locations from an initialized PyArlo instance and save to cache."""
    devices: list[dict[str, Any]] = []

    def _extract_base_info(device: Any) -> tuple[str | None, str | None]:
        bs = getattr(device, "base_station", None)
        if bs is not None:
            return getattr(bs, "device_id", None), getattr(bs, "xcloud_id", None)
        return None, getattr(device, "xcloud_id", None)

    for b in arlo.base_stations:
        devices.append({
            "name": b.name,
            "id": b.device_id,
            "type": "base_station",
            "model_id": getattr(b, "model_id", None),
            "hw_version": getattr(b, "hw_version", None),
            "serial_number": getattr(b, "serial_number", None),
            "xcloud_id": getattr(b, "xcloud_id", None),
        })

    for c in arlo.cameras:
        bs_id, xcloud_id = _extract_base_info(c)
        devices.append({
            "name": c.name,
            "id": c.device_id,
            "type": "camera",
            "model_id": getattr(c, "model_id", None),
            "hw_version": getattr(c, "hw_version", None),
            "serial_number": getattr(c, "serial_number", None),
            "base_station_id": bs_id,
            "xcloud_id": xcloud_id,
        })

    for l in arlo.lights:
        bs_id, xcloud_id = _extract_base_info(l)
        devices.append({
            "name": l.name,
            "id": l.device_id,
            "type": "light",
            "model_id": getattr(l, "model_id", None),
            "hw_version": getattr(l, "hw_version", None),
            "serial_number": getattr(l, "serial_number", None),
            "base_station_id": bs_id,
            "xcloud_id": xcloud_id,
        })

    for d in arlo.doorbells:
        bs_id, xcloud_id = _extract_base_info(d)
        devices.append({
            "name": d.name,
            "id": d.device_id,
            "type": "doorbell",
            "model_id": getattr(d, "model_id", None),
            "hw_version": getattr(d, "hw_version", None),
            "serial_number": getattr(d, "serial_number", None),
            "base_station_id": bs_id,
            "xcloud_id": xcloud_id,
        })

    for s in arlo.sensors:
        bs_id, xcloud_id = _extract_base_info(s)
        devices.append({
            "name": s.name,
            "id": s.device_id,
            "type": "sensor",
            "model_id": getattr(s, "model_id", None),
            "hw_version": getattr(s, "hw_version", None),
            "serial_number": getattr(s, "serial_number", None),
            "base_station_id": bs_id,
            "xcloud_id": xcloud_id,
        })

    locations: list[dict[str, Any]] = []
    for loc in arlo.locations:
        locations.append({
            "name": loc.name,
            "id": loc.device_id,
            "mode": getattr(loc, "mode", "unknown"),
            "available_modes": getattr(loc, "available_modes_with_ids", {}),
        })

    cache_data: dict[str, Any] = {
        "version": 1,
        "timestamp": time.time(),
        "devices": devices,
        "locations": locations,
    }

    save_cache(cache_data, cache_path)
    return cache_data
