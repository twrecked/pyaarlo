"""Compatibility shim for pyaarlo.backend."""
from .core.backend import ArloBackEnd, _flatten_intelligence_events

__all__ = ["ArloBackEnd", "_flatten_intelligence_events"]
