"""Keep patient-level detail out of reports when the source does not allow it.

Checks should already avoid it (use `profile.privacy.count(n)` in summaries and
leave `patient_ids` empty), but the pipeline runs every result through
`redact` as a second line of defence, so one careless check cannot leak rows.

What this does not do: complementary suppression. A small count can sometimes
be worked out from a total and the other cells. Someone has to read a report
built on restricted data before it is shared.
"""

from __future__ import annotations

import re
from typing import Any

from scorecard.checks.base import CheckResult, Evidence
from scorecard.profile import PrivacyPolicy

# Table and metric keys that hold a number of patients.
_COUNT_KEY = re.compile(
    r"(^n$|^n_|_n$|patients|events|count|deaths|eligible|unknown|undecided|treated|"
    r"^met$|^not_met$|^positive$|^negative$|^indeterminate$|^unusable$|^size$)",
    re.IGNORECASE,
)
_ID_KEY = re.compile(r"(patient_id|example)", re.IGNORECASE)


def _is_count(key: str, value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and bool(_COUNT_KEY.search(key))


def _redact_row(row: dict[str, Any], policy: PrivacyPolicy) -> dict[str, Any]:
    out = {}
    suppressed = False
    for key, value in row.items():
        if not policy.patient_level_output and _ID_KEY.search(key):
            continue
        if _is_count(key, value) and policy.is_small(value):
            out[key] = policy.count(value)
            suppressed = True
        else:
            out[key] = value
    if suppressed:
        # A share next to a suppressed count would give the count away.
        out = {k: ("suppressed" if isinstance(v, float) else v) for k, v in out.items()}
    return out


def _redact_evidence(evidence: Evidence, policy: PrivacyPolicy) -> Evidence:
    update: dict[str, Any] = {}
    if not policy.patient_level_output and evidence.patient_ids:
        update["patient_ids"] = []
    if evidence.table:
        update["table"] = [_redact_row(row, policy) for row in evidence.table]
    if isinstance(evidence.value, int) and not isinstance(evidence.value, bool):
        if policy.is_small(evidence.value):
            update["value"] = policy.count(evidence.value)
    return evidence.model_copy(update=update) if update else evidence


def redact(result: CheckResult, policy: PrivacyPolicy) -> CheckResult:
    if policy.patient_level_output and not policy.min_cell_count:
        return result
    metrics = {}
    for key, value in result.metrics.items():
        if key == "traceback" and not policy.patient_level_output:
            continue  # a traceback can quote data values
        metrics[key] = policy.count(value) if _is_count(key, value) else value
    return result.model_copy(
        update={
            "metrics": metrics,
            "evidence": [_redact_evidence(e, policy) for e in result.evidence],
        }
    )
