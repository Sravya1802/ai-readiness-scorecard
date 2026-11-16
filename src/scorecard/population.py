"""Population filter: who a question is about.

Every patient gets one of three labels. "unknown" means a rule could not be
decided because the value is missing; those patients are counted and reported,
never dropped silently. A patient who fails a rule that can be decided is not
eligible even when other rules are unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from pydantic import BaseModel, Field

from scorecard.profile import DatasetProfile
from scorecard.rules import Rule, all_of, any_of

ELIGIBLE = "eligible"
NOT_ELIGIBLE = "not_eligible"
UNKNOWN = "unknown"


class Population(BaseModel):
    description: str | None = None
    include: list[Rule] = Field(default_factory=list)
    exclude: list[Rule] = Field(default_factory=list)

    @property
    def rules(self) -> list[tuple[str, Rule]]:
        return [("include", r) for r in self.include] + [("exclude", r) for r in self.exclude]


@dataclass
class Cohort:
    label: pd.Series
    # One row per rule: how many patients it decided and how many unknowns it causes.
    rule_table: list[dict] = field(default_factory=list)

    @property
    def eligible(self) -> pd.Series:
        return self.label == ELIGIBLE

    @property
    def n(self) -> int:
        return len(self.label)

    @property
    def n_eligible(self) -> int:
        return int((self.label == ELIGIBLE).sum())

    @property
    def n_not_eligible(self) -> int:
        return int((self.label == NOT_ELIGIBLE).sum())

    @property
    def n_unknown(self) -> int:
        return int((self.label == UNKNOWN).sum())

    @property
    def decided_fraction(self) -> float | None:
        return None if self.n == 0 else (self.n_eligible + self.n_not_eligible) / self.n


def select(profile: DatasetProfile, population: Population | None) -> Cohort:
    features = profile.features
    if population is None or not population.rules:
        return Cohort(label=pd.Series(ELIGIBLE, index=features.index, dtype=object))

    included = all_of(population.include, features)
    excluded = any_of(population.exclude, features)
    eligible = included & ~excluded

    label = pd.Series(UNKNOWN, index=features.index, dtype=object)
    label[eligible.fillna(False).astype(bool)] = ELIGIBLE
    label[(~eligible).fillna(False).astype(bool)] = NOT_ELIGIBLE
    unknown = label == UNKNOWN

    table = []
    for kind, rule in population.rules:
        answer = rule.evaluate(features)
        table.append(
            {
                "rule": f"{kind}: {rule.describe()}",
                "column": rule.column,
                "in_dataset": profile.carries(rule.column),
                "met": int((answer == True).sum()),  # noqa: E712  (nullable boolean)
                "not_met": int((answer == False).sum()),  # noqa: E712
                "undecided": int(answer.isna().sum()),
                "undecided_among_unknown": int((answer.isna() & unknown).sum()),
            }
        )
    return Cohort(label=label, rule_table=table)
