"""SEER adapter (stub): population-level registry extracts.

Owner: unassigned. Optional in the Jamboree plan.

SEER has no public API for case-level data. The input is a SEER*Stat case
listing exported by someone with a signed SEER research data agreement, so
fetch_raw here should read a local file path rather than call a service.
Do not commit SEER extracts to this repository.

SEER patients cannot be joined to GDC, IDC or PDC patients, so this
adapter is marked not linkable and never appears in the linkage matrix.
"""

from __future__ import annotations

from scorecard.adapters.base import Adapter, register_adapter
from scorecard.profile import DatasetProfile


@register_adapter
class SEERAdapter(Adapter):
    name = "seer"
    repository = "SEER"
    modalities = ("registry",)
    implemented = False
    linkable = False
    owner = "unassigned"

    def fetch_raw(self, dataset: str, *, limit: int | None = None) -> dict:
        raise NotImplementedError("SEER adapter is not implemented yet (owner: unassigned)")

    def build_profile(self, raw: dict) -> DatasetProfile:
        raise NotImplementedError("SEER adapter is not implemented yet (owner: unassigned)")
