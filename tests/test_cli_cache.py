import time
from pathlib import Path

from pyaarlo.cli.cache import (
    clear_cache,
    is_cache_stale,
    load_cache,
    save_cache,
)


def test_cli_cache_save_load_clear(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    data = {
        "version": 1,
        "timestamp": time.time(),
        "devices": [{"id": "DEV1", "name": "Garage Light", "type": "light"}],
        "locations": [{"id": "LOC1", "name": "Home", "mode": "disarmed"}],
    }

    save_cache(data, cache_file)
    assert cache_file.is_file()

    loaded = load_cache(cache_file)
    assert loaded is not None
    assert loaded["version"] == 1
    assert len(loaded["devices"]) == 1
    assert loaded["devices"][0]["name"] == "Garage Light"

    assert clear_cache(cache_file) is True
    assert not cache_file.exists()
    assert load_cache(cache_file) is None


def test_cli_cache_stale_detection():
    assert is_cache_stale(None) is True
    assert is_cache_stale({}) is True

    fresh = {"timestamp": time.time() - 100}
    assert is_cache_stale(fresh, ttl_seconds=300) is False

    stale = {"timestamp": time.time() - 400}
    assert is_cache_stale(stale, ttl_seconds=300) is True
