"""Check registry. Decorate a Check subclass with @register_check to make the pipeline run it."""

from __future__ import annotations

from scorecard.checks.base import Check, Family

_REGISTRY: dict[str, type[Check]] = {}


def register_check(cls: type[Check]) -> type[Check]:
    if cls.id in _REGISTRY:
        raise ValueError(f"check {cls.id!r} is already registered by {_REGISTRY[cls.id].__name__}")
    _REGISTRY[cls.id] = cls
    return cls


def get_check(check_id: str) -> Check:
    try:
        return _REGISTRY[check_id]()
    except KeyError:
        raise KeyError(f"unknown check {check_id!r}; available: {sorted(_REGISTRY)}") from None


def list_checks(family: Family | None = None) -> list[type[Check]]:
    """Registered checks in display order, optionally limited to one family."""
    checks = [c for c in _REGISTRY.values() if family is None or c.family is family]
    return sorted(checks, key=lambda c: (c.family.value != "integrity", c.order))
