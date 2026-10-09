"""Repository adapters. Importing this package registers every adapter."""

from scorecard.adapters import gdc, idc, pdc, seer  # noqa: F401  (registration side effect)
from scorecard.adapters.base import Adapter, get_adapter, list_adapters, register_adapter

__all__ = ["Adapter", "get_adapter", "list_adapters", "register_adapter"]
