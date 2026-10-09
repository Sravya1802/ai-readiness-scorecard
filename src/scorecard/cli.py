"""Command line: `scorecard profile`, `scorecard snapshot`, and listings."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scorecard import __version__


def _cmd_profile(args: argparse.Namespace) -> int:
    from scorecard.pipeline import run
    from scorecard.report import write_outputs

    command = "python -m scorecard profile " + " ".join(sys.argv[2:])
    result = run(
        adapter=args.adapter,
        task=args.task,
        dataset=args.dataset,
        snapshot=args.snapshot,
        limit=args.limit,
        refresh=args.refresh,
        command=command.strip(),
    )
    written = write_outputs(result, args.out)

    v = result.verdict
    print(f"{result.profile.title}: {result.profile.n_patients:,} patients, task {result.task.id}")
    print(f"Verdict: {v.label.value}{' (PROVISIONAL)' if v.provisional else ''}")
    print(f"  {v.reason}")
    for r in result.results:
        flag = " BLOCKING" if r.is_blocking_failure else ""
        print(f"  {r.status.value:<15} {r.check_id:<38}{flag} {r.summary}")
    print("Wrote: " + ", ".join(str(p) for p in written))
    return 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    from scorecard.adapters import get_adapter

    raw = get_adapter(args.adapter).fetch_raw(args.dataset, limit=args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(raw, indent=1))
    print(f"Wrote {len(raw.get('cases', []))} records to {out}")
    return 0


def _cmd_checks(args: argparse.Namespace) -> int:
    from scorecard.checks import list_checks

    print(f"{'ID':<38} {'FAMILY':<13} {'OWNER':<10} {'STATE':<6} CRITERIA")
    for c in list_checks():
        state = "real" if c.implemented else "stub"
        criteria = ", ".join(x.value for x in c.criteria)
        print(f"{c.id:<38} {c.family.value:<13} {c.owner:<10} {state:<6} {criteria}")
    return 0


def _cmd_adapters(args: argparse.Namespace) -> int:
    from scorecard.adapters import list_adapters

    print(f"{'NAME':<6} {'REPOSITORY':<11} {'OWNER':<11} {'STATE':<6} MODALITIES")
    for a in list_adapters():
        state = "real" if a.implemented else "stub"
        print(f"{a.name:<6} {a.repository:<11} {a.owner:<11} {state:<6} {', '.join(a.modalities)}")
    return 0


def _cmd_tasks(args: argparse.Namespace) -> int:
    from scorecard.tasks import list_tasks, load_task

    for task_id in list_tasks():
        task = load_task(task_id)
        print(f"{task.id:<22} {task.title} (pack: {task.pack})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scorecard",
        description="Does this oncology dataset support this AI task, and if not, what is missing?",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("profile", help="assess a dataset for a task and write the data card")
    p.add_argument("--adapter", default="gdc", help="repository adapter (default: gdc)")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset", help="dataset to fetch, for example TCGA-BRCA")
    source.add_argument("--snapshot", help="load a saved snapshot JSON instead of fetching")
    p.add_argument("--task", default="survival-prediction", help="task spec id or YAML path")
    p.add_argument("--out", default="out", help="output directory (default: out)")
    p.add_argument("--limit", type=int, help="fetch only the first N patients (development)")
    p.add_argument("--refresh", action="store_true", help="ignore the cached snapshot")
    p.set_defaults(func=_cmd_profile)

    s = sub.add_parser(
        "snapshot", help="save a raw repository snapshot (for fixtures or offline runs)"
    )
    s.add_argument("--adapter", default="gdc")
    s.add_argument("--dataset", required=True)
    s.add_argument("--limit", type=int)
    s.add_argument("--out", required=True)
    s.set_defaults(func=_cmd_snapshot)

    for name, func, text in [
        ("checks", _cmd_checks, "list registered checks with owner and state"),
        ("adapters", _cmd_adapters, "list repository adapters"),
        ("tasks", _cmd_tasks, "list task specs"),
    ]:
        sub.add_parser(name, help=text).set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
