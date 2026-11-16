"""Reference population summaries: counts and shares only, never patient rows.

`scorecard reference` builds one from a registry profile (SEER) for a task.
The representativeness check then compares a cohort against it. Because the
summary is aggregate, it can be kept next to the run outputs, but it is still
derived from data under a use agreement: read that agreement before sharing it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from scorecard.checks.task_fit.common import harmonize
from scorecard.population import Population, select
from scorecard.profile import DatasetProfile

if TYPE_CHECKING:
    from scorecard.tasks import Task

KEY = "representativeness"
SUPPRESSED = "other (small groups combined)"


def summarize(
    profile: DatasetProfile, task: Task, mask: pd.Series, *, suppress: bool = True
) -> dict[str, dict]:
    """Per compared variable: mean and SD for numbers, shares per level for categories."""
    columns = task.param(KEY, "compare_on", [])
    maps = task.param(KEY, "category_maps", {})
    out: dict[str, dict] = {}
    for column in columns:
        if not profile.carries(column):
            continue
        values = profile.features.loc[mask, column]
        if pd.api.types.is_numeric_dtype(values):
            x = values.dropna().astype(float)
            if len(x) < 2:
                continue
            out[column] = {
                "kind": "numeric",
                "n": int(len(x)),
                "mean": round(float(x.mean()), 4),
                "sd": round(float(x.std(ddof=1)), 4),
            }
            continue
        levels = harmonize(values, maps.get(column)).dropna()
        if levels.empty:
            continue
        counts = levels.value_counts()
        if suppress and profile.privacy.min_cell_count:
            small = counts[counts < profile.privacy.min_cell_count]
            if len(small):
                counts = counts.drop(small.index)
                if small.sum() >= profile.privacy.min_cell_count:
                    counts[SUPPRESSED] = small.sum()
        total = int(counts.sum())
        out[column] = {
            "kind": "categorical",
            "n": total,
            "shares": {str(k): round(float(v) / total, 6) for k, v in counts.items()},
        }
    return out


def build_reference(profile: DatasetProfile, task: Task) -> dict:
    """Summarize the reference population for a task, using the rules the source can decide."""
    applied, skipped = Population(), []
    if task.population is not None:
        for kind, rule in task.population.rules:
            if profile.carries(rule.column):
                getattr(applied, kind).append(rule)
            else:
                skipped.append(f"{kind}: {rule.describe()}")
    cohort = select(profile, applied)
    return {
        "kind": "scorecard-reference",
        "dataset_id": profile.dataset_id,
        "title": profile.title,
        "task": task.id,
        "data_release": profile.provenance.data_release,
        "content_sha256": profile.provenance.content_sha256,
        "n_total": cohort.n,
        "n_eligible": cohort.n_eligible,
        "n_unknown": cohort.n_unknown,
        "rules_applied": [f"{kind}: {rule.describe()}" for kind, rule in applied.rules],
        "rules_skipped_not_in_source": skipped,
        "min_cell_count": profile.privacy.min_cell_count,
        "variables": summarize(profile, task, cohort.eligible),
    }
