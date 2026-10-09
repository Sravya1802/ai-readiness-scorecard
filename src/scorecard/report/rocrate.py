"""RO-Crate packaging (stub). Owner: member-4.

An RO-Crate (https://www.researchobject.org/ro-crate/) is a folder with an
ro-crate-metadata.json that describes everything in it.

What write_rocrate should produce, in <out>/ro-crate/
  - ro-crate-metadata.json (RO-Crate 1.1) whose root Dataset has parts:
    data_card.html, scorecard.json, provenance.json, croissant.json.
  - A CreateAction entity for the scorecard run: instrument = this tool and
    version, object = the source dataset (GDC project URL and data release),
    result = the files above, startTime / endTime from the run.
  - The `rocrate` package (ro-crate-py) builds this with little code.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scorecard.pipeline import Run

IMPLEMENTED = False


def write_rocrate(run: Run, out_dir: Path) -> Path:
    raise NotImplementedError("RO-Crate packaging is not implemented yet (owner: member-4)")
