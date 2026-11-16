"""Results grid: questions down the side, datasets across, a verdict in each cell.

Reads the scorecard.json of every run under a folder. It never opens a dataset,
so the grid holds only what the run reports already hold.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

VERDICT_CLASS = {"READY": "ready", "CONDITIONAL": "conditional", "NOT_READY": "not-ready"}


def collect(runs_dir: str | Path) -> dict:
    cells = []
    for path in sorted(Path(runs_dir).rglob("scorecard.json")):
        data = json.loads(path.read_text())
        task, verdict = data["task"], data["verdict"]
        cells.append(
            {
                "task": task["id"],
                "number": task.get("number"),
                "question": task.get("question") or task["title"],
                "dataset": data["dataset"]["dataset_id"],
                "dataset_title": data["dataset"]["title"],
                "n_patients": data["dataset"]["n_patients"],
                "verdict": verdict["label"],
                "provisional": verdict["provisional"],
                "reason": data.get("headline") or verdict["reason"],
                "draft_cutoffs": (task.get("clinical_review") or {}).get("status") != "reviewed",
                "run": str(path.parent),
            }
        )
    tasks: dict[str, dict] = {}
    for cell in cells:
        tasks.setdefault(cell["task"], {"number": cell["number"], "question": cell["question"]})
    order = sorted(tasks, key=lambda t: (tasks[t]["number"] is None, tasks[t]["number"] or 0, t))
    datasets = sorted({c["dataset"]: c["dataset_title"] for c in cells}.items())
    return {
        "tasks": [{"id": t, **tasks[t]} for t in order],
        "datasets": [{"id": d, "title": title} for d, title in datasets],
        "cells": cells,
    }


def render(grid: dict) -> str:
    esc = html.escape
    by_key = {(c["task"], c["dataset"]): c for c in grid["cells"]}
    head = "".join(f"<th>{esc(d['title'])}</th>" for d in grid["datasets"])
    rows = []
    for task in grid["tasks"]:
        label = f"{task['number']}. " if task["number"] else ""
        cells = []
        for dataset in grid["datasets"]:
            cell = by_key.get((task["id"], dataset["id"]))
            if cell is None:
                cells.append('<td class="none">not run</td>')
                continue
            tag = ' <span class="tag">PROVISIONAL</span>' if cell["provisional"] else ""
            cells.append(
                f'<td class="{VERDICT_CLASS.get(cell["verdict"], "none")}">'
                f"<b>{esc(cell['verdict'].replace('_', ' '))}</b>{tag}"
                f"<p>{esc(cell['reason'])}</p></td>"
            )
        rows.append(
            f"<tr><th class='q'>{esc(label + task['question'])}"
            f"<span>{esc(task['id'])}</span></th>{''.join(cells)}</tr>"
        )
    draft = any(c["draft_cutoffs"] for c in grid["cells"])
    note = (
        "<p class='note'>Cutoffs are drafts until a clinician reviews them. Verdicts say "
        "whether a dataset can support a question; they are not clinical findings.</p>"
        if draft
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI-Readiness Scorecard · results grid</title>
<style>
body {{ margin: 0; padding: 28px 20px; background: #e9e7e1; color: #1d2422;
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1100px; margin: 0 auto; }}
h1 {{ font-size: 24px; margin: 0 0 4px; }}
.wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; background: #f8f7f4; margin-top: 16px; }}
th, td {{ border: 1px solid #dcd9d1; padding: 12px 14px; text-align: left; vertical-align: top; }}
thead th {{ font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: #6b716e; }}
th.q {{ width: 30%; font-weight: 600; }}
th.q span {{ display: block; font: 400 11px ui-monospace, Menlo, monospace; color: #6b716e; }}
td b {{ display: inline-block; font-size: 13px; letter-spacing: .04em; }}
td p {{ margin: 4px 0 0; font-size: 12.5px; color: #3c4441; }}
td.ready b {{ color: #1f6b57; }} td.conditional b {{ color: #b0731a; }}
td.not-ready b {{ color: #a8382b; }} td.not-ready {{ background: #f6e9e5; }}
td.none {{ color: #9a9e9b; font-style: italic; }}
.tag {{ font: 600 10px ui-monospace, Menlo, monospace; border: 1px solid #9a9e9b;
  border-radius: 3px; padding: 1px 5px; color: #6b716e; }}
.note {{ color: #6b716e; font-size: 12.5px; }}
</style></head><body><main>
<h1>Can each dataset support each question?</h1>
<div>AI-Readiness Scorecard · {len(grid["cells"])} runs</div>
<div class="wrap"><table><thead><tr><th>Question</th>{head}</tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
{note}
</main></body></html>
"""


def write_grid(runs_dir: str | Path, out: str | Path) -> list[Path]:
    grid = collect(runs_dir)
    if not grid["cells"]:
        raise FileNotFoundError(f"no scorecard.json found under {runs_dir}")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(grid))
    json_path = out.with_suffix(".json")
    json_path.write_text(json.dumps(grid, indent=2))
    return [out, json_path]
