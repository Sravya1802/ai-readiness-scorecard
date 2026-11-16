"""adapter -> DatasetProfile -> checks -> verdict -> outputs."""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scorecard import __version__
from scorecard.adapters import get_adapter
from scorecard.checks import Check, CheckResult, Severity, Status, get_check, list_checks
from scorecard.packs import Pack, load_pack
from scorecard.population import Cohort, select
from scorecard.privacy import redact
from scorecard.profile import DatasetProfile
from scorecard.tasks import Task, load_task
from scorecard.verdict import AxisScore, Verdict, decide, radar


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Run:
    profile: DatasetProfile
    task: Task
    pack: Pack
    results: list[CheckResult]
    verdict: Verdict
    axes: list[AxisScore]
    started_at: str
    finished_at: str
    command: str = "python -m scorecard profile"
    tool_version: str = __version__
    outputs: list[str] = field(default_factory=list)
    cohort: Cohort | None = None


def checks_for(task: Task) -> list[Check]:
    """The checks a task runs: its own `checks:` list, or every check that is not opt-in.

    Listing checks per task keeps placeholder checks a question does not need
    from making its verdict provisional.
    """
    if task.checks is None:
        return [c() for c in list_checks() if not c.opt_in]
    wanted = [get_check(check_id) for check_id in task.checks]  # raises on an unknown id
    order = [c.id for c in list_checks()]
    return sorted(wanted, key=lambda c: order.index(c.id))


def assess(profile: DatasetProfile, task: Task, *, command: str | None = None) -> Run:
    """Run the task's checks on an already-built profile."""
    started = _now()
    results = []
    for check in checks_for(task):
        try:
            result = check.run(profile, task)
        except Exception as exc:  # a broken check must not hide the others
            # Blocking: a check that could not run has not shown the data is fine,
            # so it must never leave the verdict at READY.
            detail = f": {exc}" if profile.privacy.patient_level_output else ""
            result = check.result(
                Status.FAIL,
                f"Check crashed: {type(exc).__name__}{detail}",
                severity=Severity.BLOCKING,
                metrics={"traceback": traceback.format_exc(limit=5)},
                label="check error",
                remediation="Fix the check or the input it could not read, then rerun.",
            )
        results.append(redact(result, profile.privacy))
    run = Run(
        profile=profile,
        task=task,
        pack=load_pack(task.pack),
        results=results,
        verdict=decide(results),
        axes=radar(results),
        started_at=started,
        finished_at=_now(),
        cohort=select(profile, task.population) if task.population else None,
    )
    if command:
        run.command = command
    return run


def run(
    *,
    adapter: str,
    task: str,
    dataset: str | None = None,
    snapshot: str | Path | None = None,
    limit: int | None = None,
    refresh: bool = False,
    cache_dir: Path | None = None,
    command: str | None = None,
    supplement: str | Path | None = None,
    reference: str | Path | None = None,
) -> Run:
    """Load a dataset (live, cached, or from a snapshot file) and assess it for a task.

    supplement  local folder of extra source files the adapter can join (GDC only)
    reference   reference.json written by `scorecard reference`, for representativeness
    """
    source = get_adapter(adapter)
    if supplement is not None:
        source.supplement_dir = Path(supplement)
    if snapshot is not None:
        profile = source.load_snapshot(snapshot)
    elif dataset is not None:
        profile = source.load(dataset, cache_dir=cache_dir, refresh=refresh, limit=limit)
    else:
        raise ValueError("give a dataset to fetch or a snapshot file to load")
    if reference is not None:
        profile.reference = json.loads(Path(reference).read_text())
    return assess(profile, load_task(task), command=command)
