"""Rules over patient columns with three answers: true, false, or cannot tell.

A rule cannot be decided for a patient when the value it reads is missing or
the dataset has no such column. Callers decide what "cannot tell" means:
the population filter counts the patient as unknown, and `expected_when`
treats the variable as expected, so missing data never hides more missing data.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field, model_validator

Op = Literal["in", "not_in", "between", "gte", "lte"]


def normalize_value(value: Any) -> str:
    """Text form used to compare category values: case-insensitive, 1.0 equals 1."""
    if isinstance(value, bool):
        # Unquoted yes/no in YAML arrive as booleans; treat them as the words.
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip().lower()


class Rule(BaseModel):
    column: str
    op: Op = "in"
    values: list[Any] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def _arity(self) -> Rule:
        need = {"between": 2, "gte": 1, "lte": 1}.get(self.op)
        if need is not None and len(self.values) != need:
            raise ValueError(f"rule on {self.column!r}: op {self.op!r} needs {need} value(s)")
        if need is None and not self.values:
            raise ValueError(f"rule on {self.column!r}: op {self.op!r} needs at least one value")
        return self

    def describe(self) -> str:
        v = self.values
        if self.op == "in":
            return f"{self.column} is {' or '.join(map(str, v))}"
        if self.op == "not_in":
            return f"{self.column} is not {' or '.join(map(str, v))}"
        if self.op == "between":
            return f"{self.column} between {v[0]} and {v[1]}"
        return f"{self.column} {'>=' if self.op == 'gte' else '<='} {v[0]}"

    def evaluate(self, features: pd.DataFrame) -> pd.Series:
        """Nullable boolean per patient; <NA> where the rule cannot be decided."""
        result = pd.Series(pd.NA, index=features.index, dtype="boolean")
        if self.column not in features.columns:
            return result
        column = features[self.column]
        if self.op in ("in", "not_in"):
            known = column.notna()
            wanted = {normalize_value(v) for v in self.values}
            hit = column[known].map(normalize_value).isin(wanted)
            result[known] = hit if self.op == "in" else ~hit
            return result
        numeric = pd.to_numeric(column, errors="coerce")
        known = numeric.notna()
        x = numeric[known]
        if self.op == "between":
            low, high = float(self.values[0]), float(self.values[1])
            result[known] = (x >= low) & (x <= high)
        elif self.op == "gte":
            result[known] = x >= float(self.values[0])
        else:
            result[known] = x <= float(self.values[0])
        return result


def all_of(rules: list[Rule], features: pd.DataFrame) -> pd.Series:
    """Three-valued AND: false if any rule is false, unknown if none is false but one is unknown."""
    result = pd.Series(True, index=features.index, dtype="boolean")
    for rule in rules:
        result = result & rule.evaluate(features)
    return result


def any_of(rules: list[Rule], features: pd.DataFrame) -> pd.Series:
    """Three-valued OR: true if any rule is true, unknown if none is true but one is unknown."""
    result = pd.Series(False, index=features.index, dtype="boolean")
    for rule in rules:
        result = result | rule.evaluate(features)
    return result
