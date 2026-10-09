"""Human-readable data card, laid out like the prototype on slide 7 of the project deck.

Panels whose inputs are not built yet stay on the page and say so, so the card
keeps the prototype's shape while the team fills it in. Owner: member-4.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scorecard.adapters import list_adapters
from scorecard.checks import Family, Status, list_checks
from scorecard.checks.base import Criterion

if TYPE_CHECKING:
    from scorecard.pipeline import Run

AXIS_SHORT = {
    Criterion.FAIRNESS: "FAIRNESS",
    Criterion.PROVENANCE: "PROVENANCE",
    Criterion.CHARACTERIZATION: "CHARACT.",
    Criterion.ETHICS: "ETHICS",
    Criterion.EXPLAINABILITY: "EXPLAIN.",
    Criterion.SUSTAINABILITY: "SUSTAIN.",
    Criterion.COMPUTABILITY: "COMPUT.",
}

MODALITY_LABELS = {
    "clinical": "Clinical",
    "gene_expression": "Gene expression",
    "somatic_mutation": "Somatic mutation",
    "imaging": "Imaging (IDC)",
    "proteomics": "Proteomics (PDC)",
}

RADAR_SIZE = 260
RADAR_RADIUS = 78


def _radar(run: Run) -> dict:
    """Geometry for the inline SVG radar. Unassessed axes get a spoke but no point."""
    cx = cy = RADAR_SIZE / 2
    n = len(run.axes)
    axes, points = [], []
    for i, axis in enumerate(run.axes):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        dx, dy = math.cos(angle), math.sin(angle)
        label_r = RADAR_RADIUS + 18
        anchor = "middle" if abs(dx) < 0.3 else ("start" if dx > 0 else "end")
        entry = {
            "name": axis.criterion.value,
            "short": AXIS_SHORT[axis.criterion],
            "score": axis.score,
            "x2": round(cx + RADAR_RADIUS * dx, 1),
            "y2": round(cy + RADAR_RADIUS * dy, 1),
            "lx": round(cx + label_r * dx, 1),
            "ly": round(cy + label_r * dy + (4 if dy >= -0.3 else 0), 1),
            "anchor": anchor,
        }
        if axis.score is not None:
            r = RADAR_RADIUS * max(axis.score, 0.04)
            entry["px"], entry["py"] = round(cx + r * dx, 1), round(cy + r * dy, 1)
            points.append(f"{entry['px']},{entry['py']}")
        axes.append(entry)
    rings = []
    for frac in (0.25, 0.5, 0.75, 1.0):
        ring = []
        for i in range(n):
            angle = -math.pi / 2 + 2 * math.pi * i / n
            ring.append(
                f"{round(cx + RADAR_RADIUS * frac * math.cos(angle), 1)},"
                f"{round(cy + RADAR_RADIUS * frac * math.sin(angle), 1)}"
            )
        rings.append(" ".join(ring))
    assessed = [a for a in run.axes if a.score is not None]
    weakest = min(assessed, key=lambda a: a.score) if assessed else None
    return {
        "size": RADAR_SIZE,
        "cx": cx,
        "cy": cy,
        "axes": axes,
        "rings": rings,
        "polygon": " ".join(points) if len(points) >= 3 else None,
        "weakest": weakest.criterion.value if weakest else None,
        "n_assessed": len(assessed),
    }


def _linkage(run: Run) -> dict:
    profile = run.profile
    n = max(profile.n_patients, 1)
    rows = [
        {
            "label": MODALITY_LABELS.get(c.modality, c.modality.replace("_", " ").capitalize()),
            "n": c.n_patients,
            "pct": c.fraction,
            "available": True,
        }
        for c in profile.modality_coverage()
    ]
    present = set(profile.modalities.columns)
    for adapter in list_adapters():
        if not adapter.linkable:
            continue
        for modality in adapter.modalities:
            if modality in present:
                continue
            rows.append(
                {
                    "label": MODALITY_LABELS.get(modality, modality),
                    "n": None,
                    "pct": None,
                    "available": False,
                    "note": "adapter not implemented" if not adapter.implemented else "not loaded",
                }
            )
    return {
        "title": f"{profile.provenance.repository} ↔ IDC",
        "rows": rows,
        "all_present": int(profile.modalities.all(axis=1).sum()),
        "n_loaded": len(profile.modalities.columns),
        "n": n,
    }


def _row(result) -> dict:
    return {
        "id": result.check_id,
        "anchor": "ev-" + result.check_id.replace(".", "-"),
        "title": result.title,
        "status": result.status.value,
        "status_class": result.status.value.lower().replace("_", "-"),
        "status_text": {
            Status.NOT_IMPLEMENTED: "—",
            Status.NOT_APPLICABLE: "N/A",
        }.get(result.status, result.status.value),
        "summary": result.summary,
        "blocking": result.is_blocking_failure,
        "severity": result.severity.value if result.severity else None,
        "score": result.score,
        "label": result.label,
        "owner": result.owner,
        "assessed": result.status not in (Status.NOT_IMPLEMENTED,),
        "remediation": result.remediation,
        "metrics": {k: v for k, v in result.metrics.items() if k != "traceback"},
        "evidence": [e.model_dump() for e in result.evidence],
    }


def context(run: Run) -> dict:
    from scorecard.report import OUTPUTS

    profile = run.profile
    rows = [_row(r) for r in run.results]
    by_id = {r["id"]: r for r in rows}
    integrity = [by_id[r.check_id] for r in run.results if r.family is Family.INTEGRITY]
    completeness = [by_id[r.check_id] for r in run.results if r.family is Family.COMPLETENESS]
    descriptions = {c.id: c.description for c in list_checks()}
    for row in rows:
        row["description"] = descriptions.get(row["id"], "")
    n_files = sum(profile.provenance.source_files.values())
    return {
        "run": run,
        "profile": profile,
        "summary": profile.summary(),
        "verdict": run.verdict,
        "verdict_class": run.verdict.label.value.lower().replace("_", "-"),
        "integrity": integrity,
        "completeness": completeness,
        "radar": _radar(run),
        "linkage": _linkage(run),
        "n_files": n_files,
        "n_evidence": sum(len(r["evidence"]) for r in rows),
        "outputs": [
            {"name": name, "caption": caption, "written": implemented}
            for name, caption, implemented in OUTPUTS
        ],
        "rows": rows,
    }


def render_data_card(run: Run) -> str:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["thousands"] = lambda v: f"{v:,}"
    env.filters["pct"] = lambda v, digits=0: f"{v:.{digits}%}"
    return env.get_template("template.html.j2").render(**context(run))
