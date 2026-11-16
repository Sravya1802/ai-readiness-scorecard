"""Checks. Importing this package registers every check, in the order the data card shows them."""

from scorecard.checks import completeness, integrity, task_fit  # noqa: F401  (registration)
from scorecard.checks.base import (
    Check,
    CheckResult,
    Criterion,
    Evidence,
    Family,
    Severity,
    Status,
    StubCheck,
    grade,
    worst,
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
    "grade",
    "list_checks",
    "register_check",
    "worst",
]
