"""Task specs: what a given AI task needs from a dataset.

The same dataset can be ready for one task and not another, so every check
reads its thresholds, and the verdict reads its severities, from the task.
A task is a YAML file in this directory. survival_prediction.yaml is the
original prediction task; the five clinical questions (chemo_benefit.yaml and
the others) add a population, an optional treatment, a target, a variable list
with conditions, and the list of checks to run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, Field

from scorecard.checks.base import Severity
from scorecard.packs import PackVariable
from scorecard.population import Population
from scorecard.profile import DAYS_PER_YEAR, DatasetProfile
from scorecard.rules import Rule, normalize_value

TASK_DIR = Path(__file__).parent
__all__ = ["DAYS_PER_YEAR", "Task", "list_tasks", "load_task", "task_path"]


class SurvivalTarget(BaseModel):
    kind: Literal["survival"] = "survival"
    status_column: str
    event_values: list[str]
    censored_values: list[str]
    event_time_column: str
    censored_time_column: str
    # Horizon used for the binary view of the target (for example 5-year mortality).
    horizon_days: int


class Endpoint(BaseModel):
    """One time-to-event outcome: an event flag column and a time column in days."""

    name: str
    title: str | None = None
    event_column: str
    time_column: str
    event_values: list[Any] = Field(default_factory=lambda: [1])
    censored_values: list[Any] = Field(default_factory=lambda: [0])

    @property
    def label(self) -> str:
        return self.title or self.name.replace("_", " ")


class TimeToEventTarget(BaseModel):
    kind: Literal["time_to_event"] = "time_to_event"
    primary: Endpoint
    # Stand-ins, best first, used only when the primary endpoint is unavailable.
    proxies: list[Endpoint] = Field(default_factory=list)

    @property
    def endpoints(self) -> list[Endpoint]:
        return [self.primary, *self.proxies]


class LabelTarget(BaseModel):
    """A per-patient label, for example an HRD score at or above a cutoff."""

    kind: Literal["label"] = "label"
    title: str
    positive: Rule

    @property
    def column(self) -> str:
        return self.positive.column


Target = Annotated[SurvivalTarget | TimeToEventTarget | LabelTarget, Field(discriminator="kind")]


class Treatment(BaseModel):
    column: str
    title: str | None = None
    treated: list[Any] = Field(default_factory=lambda: ["yes"])
    untreated: list[Any] = Field(default_factory=lambda: ["no"])
    # Columns that drive who gets treated; the treatment check wants them recorded.
    confounders: list[str] = Field(default_factory=list)

    def arms(self, features: pd.DataFrame) -> pd.Series:
        """ "treated", "untreated", or missing when the column does not say."""
        arm = pd.Series(None, index=features.index, dtype=object)
        if self.column not in features.columns:
            return arm
        known = features[self.column].notna()
        text = features.loc[known, self.column].map(normalize_value)
        arm[text[text.isin({normalize_value(v) for v in self.treated})].index] = "treated"
        arm[text[text.isin({normalize_value(v) for v in self.untreated})].index] = "untreated"
        return arm


class TaskVariable(PackVariable):
    """A variable the question needs, optionally only under a condition."""

    need: Literal["required", "recommended"] = "required"
    role: Literal["cohort", "treatment", "outcome", "predictor", "confounder"] = "predictor"
    # Columns or "modality:<name>" entries that can stand in for the variable.
    # A stand-in counts as present with a caution, never as a full pass.
    substitutes: list[str] = Field(default_factory=list)
    note: str | None = None


class CompletenessRequirement(BaseModel):
    """How much one completeness criterion matters for this task."""

    severity: Severity
    # Pack variable names that count toward the score. None means all of them.
    required_variables: list[str] | None = None
    pass_at: float = 0.9
    warn_at: float = 0.5


class ClinicalReview(BaseModel):
    """Who signed off the cutoffs. Every cutoff is a draft until this is filled in."""

    status: Literal["draft", "reviewed"] = "draft"
    reviewer: str | None = None
    review_date: str | None = None
    open_questions: list[str] = Field(default_factory=list)


class Fallback(BaseModel):
    """A narrower question the dataset may still support when some checks fail."""

    question: str
    if_not_passed: list[str]


class Task(BaseModel):
    id: str
    title: str
    description: str
    pack: str
    # Position in the results grid (Dr. Gadi's question number), if it has one.
    number: int | None = None
    question: str | None = None
    clinical_review: ClinicalReview | None = None
    population: Population | None = None
    treatment: Treatment | None = None
    target: Target | None = None
    variables: list[TaskVariable] = Field(default_factory=list)
    # Check ids to run. None runs every check that is not opt-in.
    checks: list[str] | None = None
    completeness: dict[str, CompletenessRequirement] = Field(default_factory=dict)
    # Per-check thresholds, keyed by the check id's last part (for example "missingness").
    # `params` is the name used by the question tasks; `integrity` is the original one.
    integrity: dict[str, dict[str, Any]] = Field(default_factory=dict)
    params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    fallbacks: list[Fallback] = Field(default_factory=list)

    def param(self, check: str, key: str, default: Any) -> Any:
        for source in (self.params, self.integrity):
            if key in source.get(check, {}):
                return source[check][key]
        return default

    def cutoffs(self, check: str, metric: str) -> tuple[float, float] | None:
        """(pass_at, warn_at) for one metric of one check, or None when the task sets none."""
        value = self.param(check, metric, None)
        if not isinstance(value, dict) or "pass" not in value or "warn" not in value:
            return None
        return float(value["pass"]), float(value["warn"])

    @property
    def survival(self) -> SurvivalTarget | None:
        return self.target if isinstance(self.target, SurvivalTarget) else None

    def survival_target(self, profile: DatasetProfile) -> pd.DataFrame:
        """Per-patient target: event (bool), time (days), and why a row is unusable, if it is.

        Columns: event, time, horizon_label, unusable_reason.
        horizon_label is 1 for an event within the horizon, 0 for follow-up past the
        horizon, and NaN when the patient was censored before the horizon.
        """
        t = self.survival
        if t is None:
            raise ValueError(f"task {self.id!r} has no survival target")
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

    def endpoints(self) -> list[Endpoint]:
        """Time-to-event endpoints of the task, primary first. Empty for label tasks."""
        if isinstance(self.target, TimeToEventTarget):
            return self.target.endpoints
        if isinstance(self.target, SurvivalTarget):
            return [Endpoint(name="overall_survival", event_column="", time_column="")]
        return []

    def endpoint_frame(self, profile: DatasetProfile, endpoint: Endpoint) -> pd.DataFrame:
        """Per-patient `event` (True/False) and `time` in days; both missing when unusable."""
        f = profile.features
        if isinstance(self.target, SurvivalTarget):
            target = self.survival_target(profile)
            return pd.DataFrame(
                {"event": target["event"].astype("boolean"), "time": target["time"]}
            )
        event = pd.Series(pd.NA, index=f.index, dtype="boolean")
        time = pd.Series(np.nan, index=f.index, dtype=float)
        if endpoint.event_column in f.columns and endpoint.time_column in f.columns:
            flag = f[endpoint.event_column]
            known = flag.notna()
            text = flag[known].map(normalize_value)
            event[text[text.isin({normalize_value(v) for v in endpoint.event_values})].index] = True
            event[text[text.isin({normalize_value(v) for v in endpoint.censored_values})].index] = (
                False
            )
            time = pd.to_numeric(f[endpoint.time_column], errors="coerce")
        usable = event.notna() & time.notna() & (time >= 0)
        return pd.DataFrame({"event": event.where(usable), "time": time.where(usable)})

    def endpoint_available(self, profile: DatasetProfile, endpoint: Endpoint) -> bool:
        if isinstance(self.target, SurvivalTarget):
            return True
        return profile.carries(endpoint.event_column) and profile.carries(endpoint.time_column)


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
