"""Provenance record: which checks ran, on what data, with which pack and task versions."""

from __future__ import annotations

import hashlib
import platform
from importlib import metadata
from typing import TYPE_CHECKING

from scorecard.checks import Status, list_checks
from scorecard.profile import IR_VERSION
from scorecard.tasks import task_path

if TYPE_CHECKING:
    from scorecard.pipeline import Run

_DEPENDENCIES = (
    "pandas",
    "numpy",
    "scipy",
    "scikit-learn",
    "pydantic",
    "pyyaml",
    "requests",
    "jinja2",
)


def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def build_provenance(run: Run) -> dict:
    spec = task_path(run.task.id)
    implemented = {c.id: c.implemented for c in list_checks()}
    return {
        "tool": {
            "name": "ai-readiness-scorecard",
            "version": run.tool_version,
            "ir_version": IR_VERSION,
        },
        "command": run.command,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {p: _version(p) for p in _DEPENDENCIES},
        },
        "task": {
            "id": run.task.id,
            "spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest() if spec.exists() else None,
        },
        "pack": {"id": run.pack.id, "version": run.pack.version},
        "data": run.profile.provenance.model_dump(mode="json"),
        "checks": [
            {
                "id": r.check_id,
                "owner": r.owner,
                "implemented": implemented.get(r.check_id, True),
                "status": r.status.value,
                "ran": r.status is not Status.NOT_IMPLEMENTED,
            }
            for r in run.results
        ],
    }
