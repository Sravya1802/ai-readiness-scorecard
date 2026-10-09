"""adapter -> DatasetProfile -> checks -> verdict -> outputs."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scorecard import __version__
from scorecard.adapters import get_adapter
from scorecard.checks import CheckResult, Status, list_checks
from scorecard.packs import Pack, load_pack
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


def assess(profile: DatasetProfile, task: Task, *, command: str | None = None) -> Run:
    """Run every registered check on an already-built profile."""
    started = _now()
    results = []
    for check_cls in list_checks():
        check = check_cls()
        try:
            results.append(check.run(profile, task))
        except Exception as exc:  # a broken check must not hide the others
            results.append(
                check.result(
                    Status.FAIL,
                    f"Check crashed: {type(exc).__name__}: {exc}",
                    metrics={"traceback": traceback.format_exc(limit=5)},
                    label="check error",
                )
            )
    run = Run(
        profile=profile,
        task=task,
        pack=load_pack(task.pack),
        results=results,
        verdict=decide(results),
        axes=radar(results),
        started_at=started,
        finished_at=_now(),
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
) -> Run:
    """Load a dataset (live, cached, or from a snapshot file) and assess it for a task."""
    source = get_adapter(adapter)
    if snapshot is not None:
        profile = source.load_snapshot(snapshot)
    elif dataset is not None:
        profile = source.load(dataset, cache_dir=cache_dir, refresh=refresh, limit=limit)
    else:
        raise ValueError("give a dataset to fetch or a snapshot file to load")
    return assess(profile, load_task(task), command=command)
