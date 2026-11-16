"""Helpers shared by the task-fit checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from scorecard.checks.base import Severity, Status
from scorecard.profile import DAYS_PER_YEAR, DatasetProfile
from scorecard.rules import normalize_value

if TYPE_CHECKING:
    from scorecard.tasks import Endpoint, Task


def severity_for(status: Status, *, blocking: bool) -> Severity | None:
    if status is Status.FAIL:
        return Severity.BLOCKING if blocking else Severity.DEGRADING
    return Severity.DEGRADING if status is Status.WARN else None


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


@dataclass
class Outcome:
    """What the eligible cohort offers as an outcome for the task."""

    kind: str  # "time_to_event" | "label" | "none"
    name: str | None = None
    label: str | None = None
    is_proxy: bool = False
    # Per eligible patient: event (nullable bool) and, for time-to-event, time in days.
    frame: pd.DataFrame | None = None
    unavailable: list[str] | None = None

    @property
    def usable(self) -> pd.Series:
        return self.frame["event"].notna()

    @property
    def n_usable(self) -> int:
        return 0 if self.frame is None else int(self.usable.sum())

    @property
    def n_events(self) -> int:
        return 0 if self.frame is None else int((self.frame["event"] == True).sum())  # noqa: E712

    @property
    def n_non_events(self) -> int:
        return 0 if self.frame is None else int((self.frame["event"] == False).sum())  # noqa: E712

    @property
    def median_followup_years(self) -> float | None:
        """Median follow-up among patients who have not had the event.

        Using everyone would make follow-up look shorter in a cohort with many
        early events, because an event ends a patient's observed time.
        """
        if self.frame is None or "time" not in self.frame:
            return None
        censored = self.frame.loc[self.frame["event"] == False, "time"].dropna()  # noqa: E712
        return None if censored.empty else float(censored.median()) / DAYS_PER_YEAR


def find_outcome(profile: DatasetProfile, task: Task, eligible: pd.Series) -> Outcome:
    """The best outcome the dataset carries for the task: primary, else the first proxy."""
    from scorecard.tasks import LabelTarget

    target = task.target
    if target is None:
        return Outcome(kind="none")
    if isinstance(target, LabelTarget):
        if not profile.carries(target.column):
            return Outcome(
                kind="label", name=target.column, label=target.title, unavailable=[target.column]
            )
        answer = target.positive.evaluate(profile.features)[eligible]
        return Outcome(
            kind="label",
            name=target.column,
            label=target.title,
            frame=pd.DataFrame({"event": answer}),
        )
    unavailable = []
    endpoints: list[Endpoint] = task.endpoints()
    for position, endpoint in enumerate(endpoints):
        if not task.endpoint_available(profile, endpoint):
            unavailable.append(endpoint.label)
            continue
        frame = task.endpoint_frame(profile, endpoint)[eligible]
        if frame["event"].notna().any():
            return Outcome(
                kind="time_to_event",
                name=endpoint.name,
                label=endpoint.label,
                is_proxy=position > 0,
                frame=frame,
                unavailable=unavailable,
            )
        unavailable.append(f"{endpoint.label} (carried, but empty for these patients)")
    return Outcome(kind="time_to_event", unavailable=unavailable)


def harmonize(values: pd.Series, mapping: dict | None) -> pd.Series:
    """Lower-case category values and fold them through a task-supplied map."""
    lookup = {normalize_value(k): normalize_value(v) for k, v in (mapping or {}).items()}
    known = values.notna()
    out = pd.Series(None, index=values.index, dtype=object)
    text = values[known].map(normalize_value)
    out[known] = text.map(lambda v: lookup.get(v, v))
    return out
