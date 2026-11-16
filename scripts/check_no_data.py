"""Fail when something that looks like patient-level data is tracked by git.

Run in CI and before every push:  python scripts/check_no_data.py

Allowed: the open-tier GDC fixture and invented rows under tests/fixtures/.
Everything else that is tabular, large, or lives under data/ is refused.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_DIRS = ("tests/fixtures/",)
BLOCKED_DIRS = ("data/", "out/")
BLOCKED_SUFFIXES = (".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".sas7bdat", ".dic", ".slm")
MAX_BYTES = 2_000_000


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def problems(files: list[str]) -> list[str]:
    found = []
    for name in files:
        if name.startswith(ALLOWED_DIRS):
            if "seer" in name.lower() and "synthetic" not in name.lower():
                found.append(f"{name}: SEER fixtures must be invented rows named *synthetic*")
            continue
        if name.startswith(BLOCKED_DIRS):
            found.append(f"{name}: files under data/ and out/ must not be committed")
        elif name.lower().endswith(BLOCKED_SUFFIXES):
            found.append(f"{name}: tabular data file outside tests/fixtures/")
        elif (ROOT / name).exists() and (ROOT / name).stat().st_size > MAX_BYTES:
            found.append(f"{name}: larger than {MAX_BYTES:,} bytes")
    return found


def main() -> int:
    found = problems(tracked_files())
    for line in found:
        print(f"BLOCKED  {line}")
    if found:
        print("Remove these from the commit. Patient-level data stays in the local data/ folder.")
        return 1
    print("No data files tracked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
