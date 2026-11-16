"""Outputs of a run: data card, scorecard.json, provenance.json; later Croissant and RO-Crate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from scorecard.report import croissant, rocrate
from scorecard.report.data_card import render_data_card
from scorecard.report.provenance import build_provenance
from scorecard.report.summary import (
    cohort_summary,
    main_reason,
    narrower_questions,
    what_is_missing,
)

if TYPE_CHECKING:
    from scorecard.pipeline import Run

# Every output the data card's Outputs panel lists, in display order.
OUTPUTS = [
    ("data_card.html", "Evidence-linked report", True),
    ("scorecard.json", "Machine-readable results", True),
    ("provenance.json", "Checks, data and pack versions", True),
    ("croissant.json", "ML-framework loadable", croissant.IMPLEMENTED),
    ("ro-crate/", "Packaged research object", rocrate.IMPLEMENTED),
]


def scorecard_json(run: Run) -> dict:
    return {
        "dataset": run.profile.summary().model_dump(mode="json"),
        "task": run.task.model_dump(mode="json"),
        "pack": {"id": run.pack.id, "version": run.pack.version},
        "verdict": run.verdict.model_dump(mode="json"),
        "headline": main_reason(run),
        "cohort": cohort_summary(run),
        "what_is_missing": what_is_missing(run),
        "narrower_questions": narrower_questions(run),
        "bridge2ai_profile": [a.model_dump(mode="json") for a in run.axes],
        "results": [r.model_dump(mode="json") for r in run.results],
    }


def write_outputs(run: Run, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run.outputs = [name for name, _, implemented in OUTPUTS if implemented]

    written = []
    for name, payload in [
        ("scorecard.json", scorecard_json(run)),
        ("provenance.json", build_provenance(run)),
    ]:
        path = out / name
        path.write_text(json.dumps(payload, indent=2, default=str))
        written.append(path)
    if croissant.IMPLEMENTED:
        path = out / "croissant.json"
        path.write_text(json.dumps(croissant.build_croissant(run), indent=2))
        written.append(path)
    if rocrate.IMPLEMENTED:
        written.append(rocrate.write_rocrate(run, out))

    path = out / "data_card.html"
    path.write_text(render_data_card(run))
    written.append(path)
    return written
