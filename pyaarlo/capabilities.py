"""Capability detection for Arlo devices.

Arlo publishes a per-model, per-interface-version document declaring which
streaming and talk protocols a device actually supports:

    GET https://myapi.arlo.com/resources/capabilities/<model>/<model>_<interfaceVersion>.json

This document is the source of truth. The hardcoded model-prefix list below
is a fallback only, used when the document can't be fetched - it is
transcribed from a third-party project and is known to be incomplete (it
does not, for example, include every hub-less Pro-series camera).

A lookup failure here must never block RTSPS streaming, so every function in
this module fails soft: no exceptions escape, and "unknown" always resolves
to `{}` / `False` rather than raising.
"""

import time

from .constant import (
    CAPABILITIES_PATH_FORMAT,
    MODEL_ESSENTIAL_INDOOR_GEN2_2K,
    MODEL_ESSENTIAL_INDOOR_GEN2_HD,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
    MODEL_ESSENTIAL_VIDEO_DOORBELL,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
    MODEL_WIRED_VIDEO_DOORBELL,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
)

CACHE_TTL = 24 * 60 * 60  # seconds

FALLBACK_SIP_STREAMING_MODELS = (
    MODEL_WIRED_VIDEO_DOORBELL,
    MODEL_ESSENTIAL_VIDEO_DOORBELL,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_HD,
    MODEL_WIRED_VIDEO_DOORBELL_GEN2_2K,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_HD,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_HD,
    MODEL_ESSENTIAL_INDOOR_GEN2_HD,
    MODEL_ESSENTIAL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_XL_OUTDOOR_GEN2_2K,
    MODEL_ESSENTIAL_INDOOR_GEN2_2K,
)

# Tier 1 of the cache: process-local, keyed by "<model>_<interfaceVersion>".
# Tier 2 is ArloStorage, so the document survives a restart (see arlo.st).
_memory_cache = {}


def _cache_key(model_id, interface_version):
    return f"{model_id.lower()}_{interface_version}"


def _storage_key(cache_key):
    return ["ArloCapabilities", cache_key]


def _fetch(arlo, model_id, interface_version):
    path = CAPABILITIES_PATH_FORMAT.format(model_id.lower(), interface_version)
    response = arlo.be.get(path, raw=True)
    if not isinstance(response, dict):
        arlo.debug(f"capabilities: no document for {model_id}/{interface_version}")
        return {}
    return response


def get_capabilities(arlo, model_id, interface_version):
    """Return the Arlo-published capability document for a model/interface-version pair.

    Cached in memory and in `arlo.st` for `CACHE_TTL` seconds. Always
    returns a dict, `{}` on any failure, so callers can chain `.get()`
    lookups without special-casing errors.
    """
    if not model_id or not interface_version:
        return {}

    cache_key = _cache_key(model_id, interface_version)
    now = time.time()

    cached = _memory_cache.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1]

    stored = arlo.st.get(_storage_key(cache_key))
    if stored is not None and stored.get("expires", 0) > now:
        _memory_cache[cache_key] = (stored["expires"], stored["data"])
        return stored["data"]

    data = _fetch(arlo, model_id, interface_version)
    expires = now + CACHE_TTL
    _memory_cache[cache_key] = (expires, data)
    arlo.st.set(_storage_key(cache_key), {"expires": expires, "data": data})
    return data


def supports_sip_streaming(arlo, model_id, interface_version):
    """Returns `True` if the device supports live SIP/WebRTC streaming.

    Trusts the capability document fully when it's available - including
    when it explicitly says `False`. Only falls back to the (incomplete)
    hardcoded model list when the document itself couldn't be obtained.
    """
    capabilities = get_capabilities(arlo, model_id, interface_version).get("Capabilities")
    if capabilities is not None:
        return bool(capabilities.get("Streaming", {}).get("SIPStreaming", False))
    return model_id is not None and model_id.upper().startswith(
        tuple(model.upper() for model in FALLBACK_SIP_STREAMING_MODELS)
    )


def supports_sip_push_to_talk(arlo, model_id, interface_version):
    """Returns `True` if the device signals push-to-talk over SIP (vs. the notify/MQTT path)."""
    capabilities = get_capabilities(arlo, model_id, interface_version).get("Capabilities")
    if capabilities is None:
        return False
    return "sip" in capabilities.get("PushToTalk", {}).get("signal", [])


def has_full_duplex_push_to_talk(arlo, model_id, interface_version):
    """Returns `True` if the device supports simultaneous talk/listen push-to-talk."""
    capabilities = get_capabilities(arlo, model_id, interface_version).get("Capabilities")
    if capabilities is None:
        return False
    return bool(capabilities.get("PushToTalk", {}).get("fullDuplex", False))
