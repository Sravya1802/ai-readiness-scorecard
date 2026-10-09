"""Task specs: what a given AI task needs from a dataset.

The same dataset can be ready for one task and not another, so every check
reads its thresholds, and the verdict reads its severities, from the task.
A task is a YAML file in this directory; see survival_prediction.yaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, Field

from scorecard.checks.base import Severity
from scorecard.profile import DatasetProfile

TASK_DIR = Path(__file__).parent


class SurvivalTarget(BaseModel):
    kind: Literal["survival"] = "survival"
    status_column: str
    event_values: list[str]
    censored_values: list[str]
    event_time_column: str
    censored_time_column: str
    # Horizon used for the binary view of the target (for example 5-year mortality).
    horizon_days: int


class CompletenessRequirement(BaseModel):
    """How much one completeness criterion matters for this task."""

    severity: Severity
    # Pack variable names that count toward the score. None means all of them.
    required_variables: list[str] | None = None
    pass_at: float = 0.9
    warn_at: float = 0.5


class Task(BaseModel):
    id: str
    title: str
    description: str
    pack: str
    target: SurvivalTarget
    completeness: dict[str, CompletenessRequirement]
    # Per-check thresholds, keyed by the check id's last part (for example "missingness").
    integrity: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def param(self, check: str, key: str, default: Any) -> Any:
        return self.integrity.get(check, {}).get(key, default)

    def survival_target(self, profile: DatasetProfile) -> pd.DataFrame:
        """Per-patient target: event (bool), time (days), and why a row is unusable, if it is.

        Columns: event, time, horizon_label, unusable_reason.
        horizon_label is 1 for an event within the horizon, 0 for follow-up past the
        horizon, and NaN when the patient was censored before the horizon.
        """
        t = self.target
        f = profile.features
        status = f[t.status_column]
        event = status.isin(t.event_values)
        censored = status.isin(t.censored_values)
        time = pd.Series(np.nan, index=f.index, dtype=float)
        time[event] = pd.to_numeric(f.loc[event, t.event_time_column], errors="coerce")
        time[censored] = pd.to_numeric(f.loc[censored, t.censored_time_column], errors="coerce")

        reason = pd.Series(None, index=f.index, dtype=object)
        reason[~event & ~censored] = f"no usable {t.status_column}"
        reason[event & time.isna()] = f"event without {t.event_time_column}"
        reason[censored & time.isna()] = f"censored without {t.censored_time_column}"
        reason[time < 0] = "negative time"

        usable = reason.isna()
        horizon_label = pd.Series(np.nan, index=f.index, dtype=float)
        horizon_label[usable & event & (time <= t.horizon_days)] = 1.0
        horizon_label[usable & (time > t.horizon_days)] = 0.0

        return pd.DataFrame(
            {
                "event": event.where(usable),
                "time": time.where(usable),
                "horizon_label": horizon_label,
                "unusable_reason": reason,
            }
        )


def task_path(task_id: str) -> Path:
    return TASK_DIR / f"{task_id.replace('-', '_')}.yaml"


def load_task(task_id_or_path: str) -> Task:
    path = Path(task_id_or_path)
    if not path.suffix:
        path = task_path(task_id_or_path)
    if not path.exists():
        raise FileNotFoundError(f"no task spec {task_id_or_path!r}; available: {list_tasks()}")
    return Task.model_validate(yaml.safe_load(path.read_text()))


def list_tasks() -> list[str]:
    return sorted(p.stem.replace("_", "-") for p in TASK_DIR.glob("*.yaml"))
