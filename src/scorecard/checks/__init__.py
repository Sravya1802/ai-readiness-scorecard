"""Checks. Importing this package registers every check, in the order the data card shows them."""

from scorecard.checks import completeness, integrity  # noqa: F401  (registration side effect)
from scorecard.checks.base import (
    Check,
    CheckResult,
    Criterion,
    Evidence,
    Family,
    Severity,
    Status,
    StubCheck,
)
from scorecard.checks.registry import get_check, list_checks, register_check

__all__ = [
    "Check",
    "CheckResult",
    "Criterion",
    "Evidence",
    "Family",
    "Severity",
    "Status",
    "StubCheck",
    "get_check",
    "list_checks",
    "register_check",
]
