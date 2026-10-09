"""The check contract.

A check looks at one DatasetProfile in the light of one Task and returns one
CheckResult. Checks never modify the profile and never fetch data.

Two rules every check follows:
  - Status says how the dataset did; severity says what a failure costs.
    BLOCKING means the task cannot be trained or evaluated soundly until it is
    fixed. DEGRADING means the model will work but be worse or less trustworthy.
  - Every non-PASS result carries evidence: the columns, counts or example
    patient ids a reviewer would need to confirm the finding by hand.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from scorecard.profile import DatasetProfile

if TYPE_CHECKING:
    from scorecard.tasks import Task


class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    # The check cannot run on this profile (for example the task needs a site
    # label and the dataset has none). Never counts as a pass.
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class Severity(str, Enum):
    BLOCKING = "blocking"
    DEGRADING = "degrading"


class Family(str, Enum):
    INTEGRITY = "integrity"
    COMPLETENESS = "completeness"


class Criterion(str, Enum):
    """The seven NIH Bridge2AI AI-readiness criteria (the radar axes)."""

    FAIRNESS = "FAIRness"
    PROVENANCE = "Provenance"
    CHARACTERIZATION = "Characterization"
    ETHICS = "Ethics"
    EXPLAINABILITY = "Pre-model Explainability"
    SUSTAINABILITY = "Sustainability"
    COMPUTABILITY = "Computability"


class Evidence(BaseModel):
    """One piece of support for a finding, rendered in the data card's evidence section."""

    label: str
    value: Any = None
    columns: list[str] = Field(default_factory=list)
    # Example patient ids. Keep short; ten is plenty for a reviewer.
    patient_ids: list[str] = Field(default_factory=list)
    table: list[dict[str, Any]] | None = None


class CheckResult(BaseModel):
    check_id: str
    title: str
    family: Family
    criteria: list[Criterion]
    owner: str
    status: Status
    # Set when status is WARN or FAIL.
    severity: Severity | None = None
    summary: str
    # Fraction of required variables present, for completeness checks (0 to 1).
    score: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    remediation: str | None = None
    # Free-text label, for example "draft mapping, needs domain review".
    label: str | None = None

    @property
    def is_blocking_failure(self) -> bool:
        return self.status is Status.FAIL and self.severity is Severity.BLOCKING


class Check(ABC):
    """Base class for every check. Subclass, fill the class attributes, implement run()."""

    id: ClassVar[str]
    title: ClassVar[str]
    family: ClassVar[Family]
    criteria: ClassVar[tuple[Criterion, ...]]
    owner: ClassVar[str]
    # One line for `scorecard checks list` and the data card's row subtitle.
    description: ClassVar[str] = ""
    # Position within its family on the data card (lower first).
    order: ClassVar[int] = 100
    implemented: ClassVar[bool] = True

    @abstractmethod
    def run(self, profile: DatasetProfile, task: Task) -> CheckResult: ...

    def result(self, status: Status, summary: str, **kwargs: Any) -> CheckResult:
        """Build a CheckResult with this check's identity filled in."""
        return CheckResult(
            check_id=self.id,
            title=self.title,
            family=self.family,
            criteria=list(self.criteria),
            owner=self.owner,
            status=status,
            summary=summary,
            **kwargs,
        )


class StubCheck(Check):
    """A registered placeholder: shows up in listings and the data card, never passes."""

    implemented = False

    def run(self, profile: DatasetProfile, task: Task) -> CheckResult:
        return self.result(
            Status.NOT_IMPLEMENTED,
            f"Not yet assessed. Owner: {self.owner}.",
        )
