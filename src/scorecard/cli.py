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
        supplement=args.supplement,
        reference=args.reference,
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

    adapter = get_adapter(args.adapter)
    if not adapter.allow_snapshot:
        print(
            f"Refused: {adapter.repository} rows are covered by a data use agreement, so this "
            "tool never copies them. Point `scorecard profile --snapshot` at your export instead.",
            file=sys.stderr,
        )
        return 2
    raw = adapter.fetch_raw(args.dataset, limit=args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(raw, indent=1))
    print(f"Wrote {len(raw.get('cases', []))} records to {out}")
    return 0


def _cmd_reference(args: argparse.Namespace) -> int:
    from scorecard.adapters import get_adapter
    from scorecard.reference import build_reference
    from scorecard.tasks import load_task

    adapter = get_adapter(args.adapter)
    profile = adapter.load_snapshot(args.snapshot) if args.snapshot else adapter.load(args.dataset)
    reference = build_reference(profile, load_task(args.task))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reference, indent=2))
    show = profile.privacy.count
    print(
        f"Reference for {reference['task']}: {show(reference['n_eligible'])} eligible of "
        f"{reference['n_total']:,} in {profile.title}; {len(reference['variables'])} variables."
    )
    if reference["rules_skipped_not_in_source"]:
        print(
            "Rules the source cannot apply: " + "; ".join(reference["rules_skipped_not_in_source"])
        )
    print(f"Wrote {out} (counts and shares only)")
    return 0


def _cmd_grid(args: argparse.Namespace) -> int:
    from scorecard.report.grid import write_grid

    written = write_grid(args.runs, args.out)
    print("Wrote: " + ", ".join(str(p) for p in written))
    return 0


def _cmd_checks(args: argparse.Namespace) -> int:
    from scorecard.checks import list_checks

    print(f"{'ID':<38} {'FAMILY':<13} {'OWNER':<10} {'STATE':<6} CRITERIA")
    for c in list_checks():
        state = ("opt-in" if c.opt_in else "real") if c.implemented else "stub"
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
        number = f"Q{task.number} " if task.number else "   "
        print(f"{number}{task.id:<22} {task.title} (pack: {task.pack})")
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
    source.add_argument(
        "--snapshot",
        help="load a saved snapshot JSON instead of fetching (for seer: the SEER*Stat export)",
    )
    p.add_argument(
        "--supplement",
        help="local folder of extra source files to join (GDC: Biotab, TCGA-CDR, published tables)",
    )
    p.add_argument(
        "--reference", help="reference.json from `scorecard reference`, for representativeness"
    )
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

    r = sub.add_parser(
        "reference", help="summarize a reference population for a task (counts and shares only)"
    )
    r.add_argument("--adapter", default="seer")
    r_source = r.add_mutually_exclusive_group(required=True)
    r_source.add_argument("--snapshot", help="local export or snapshot file")
    r_source.add_argument("--dataset")
    r.add_argument("--task", required=True)
    r.add_argument("--out", required=True)
    r.set_defaults(func=_cmd_reference)

    g = sub.add_parser("grid", help="lay out every run under a folder as questions by datasets")
    g.add_argument("--runs", default="out", help="folder holding the run outputs (default: out)")
    g.add_argument("--out", default="out/grid.html")
    g.set_defaults(func=_cmd_grid)

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
