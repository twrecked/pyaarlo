"""Deprecated module: types functionality has been consolidated into pyaarlo.capabilities."""
from .capabilities import ArloTypes, is_resource, eval_doc_resource, static_is_resource

__all__ = ["ArloTypes", "is_resource", "eval_doc_resource", "static_is_resource"]
