import asyncio
import unittest
from unittest.mock import AsyncMock

from pyaarlo.capabilities import (
    FALLBACK_SIP_STREAMING_MODELS,
    get_capabilities,
    get_cached_capabilities,
    supports_sip_push_to_talk,
    supports_sip_streaming,
    has_full_duplex_push_to_talk,
)


class _FakeStorage:
    def __init__(self):
        self.db = {}

    def get(self, key, default=None):
        k = "/".join(key) if isinstance(key, list) else key
        return self.db.get(k, default)

    def set(self, key, value, prefix=""):
        k = "/".join(key) if isinstance(key, list) else key
        self.db[k] = value
        return value


class _FakeLog:
    def debug(self, msg):
        pass

    def vdebug(self, msg):
        pass


class _FakeBackend:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    async def get(self, path, raw=False):
        self.calls.append({"path": path, "raw": raw})
        return self.response


class _FakeCore:
    def __init__(self, response=None):
        self.log = _FakeLog()
        self.st = _FakeStorage()
        self.be = _FakeBackend(response)


class TestCapabilities(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from pyaarlo.capabilities import _memory_cache
        _memory_cache.clear()
    def test_fallback_models_detected(self):
        core = _FakeCore()
        for model in FALLBACK_SIP_STREAMING_MODELS:
            self.assertTrue(supports_sip_streaming(core, model, 1))

    def test_non_sip_fallback_returns_false(self):
        core = _FakeCore()
        self.assertFalse(supports_sip_streaming(core, "VMC3030", 1))

    async def test_get_capabilities_fetches_and_caches(self):
        doc = {
            "Capabilities": {
                "Streaming": {"SIPStreaming": True},
                "PushToTalk": {"signal": ["sip"], "fullDuplex": True},
            }
        }
        core = _FakeCore(doc)
        res = await get_capabilities(core, "VMC4040", 2)
        self.assertEqual(res, doc)
        self.assertEqual(len(core.be.calls), 1)

        # Second call hits cache
        res2 = await get_capabilities(core, "VMC4040", 2)
        self.assertEqual(res2, doc)
        self.assertEqual(len(core.be.calls), 1)

        # Synchronous check uses cached capabilities
        self.assertTrue(supports_sip_streaming(core, "VMC4040", 2))
        self.assertTrue(supports_sip_push_to_talk(core, "VMC4040", 2))
        self.assertTrue(has_full_duplex_push_to_talk(core, "VMC4040", 2))

    async def test_capability_document_false_overrides_fallback(self):
        # Even if model is in fallback list, an explicit False in doc is honored
        doc = {
            "Capabilities": {
                "Streaming": {"SIPStreaming": False},
            }
        }
        core = _FakeCore(doc)
        model = FALLBACK_SIP_STREAMING_MODELS[0]
        await get_capabilities(core, model, 1)
        self.assertFalse(supports_sip_streaming(core, model, 1))
