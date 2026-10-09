"""PDC adapter (stub): CPTAC proteomics from the Proteomic Data Commons.

Owner: unassigned. Optional in the Jamboree plan.

What it needs to do
  - fetch_raw: query the PDC GraphQL API for one study's cases and its
    protein abundance matrix.
  - build_profile: one row per patient, a boolean "proteomics" modality
    column, protein abundance features.

Linking to GDC is not automatic: CPTAC and TCGA cohorts overlap only
partly, so check identifier compatibility before promising a join.
"""

from __future__ import annotations

from scorecard.adapters.base import Adapter, register_adapter
from scorecard.profile import DatasetProfile


@register_adapter
class PDCAdapter(Adapter):
    name = "pdc"
    repository = "PDC"
    modalities = ("proteomics",)
    implemented = False
    owner = "unassigned"

    def fetch_raw(self, dataset: str, *, limit: int | None = None) -> dict:
        raise NotImplementedError("PDC adapter is not implemented yet (owner: unassigned)")

    def build_profile(self, raw: dict) -> DatasetProfile:
        raise NotImplementedError("PDC adapter is not implemented yet (owner: unassigned)")
