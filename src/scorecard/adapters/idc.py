"""IDC adapter (stub): imaging collections from the Imaging Data Commons.

Owner: member-4. Stretch goal in the Jamboree plan.

What it needs to do
  - fetch_raw: list the series in one IDC collection with their PatientID.
    The `idc-index` Python package gives this without BigQuery credentials.
  - build_profile: one row per patient, a boolean "imaging" modality column,
    and a small set of imaging metadata features (modality, body part, series
    count). No pixel data.

Linking to GDC
  For TCGA collections the DICOM PatientID is the TCGA submitter id
  (for example TCGA-A8-A08S), which is the patient index the GDC adapter
  uses. Verify this on the chosen collection before relying on it. The join
  itself belongs in a separate linkage step, not in this adapter.
"""

from __future__ import annotations

from scorecard.adapters.base import Adapter, register_adapter
from scorecard.profile import DatasetProfile


@register_adapter
class IDCAdapter(Adapter):
    name = "idc"
    repository = "IDC"
    modalities = ("imaging",)
    implemented = False
    owner = "member-4"

    def fetch_raw(self, dataset: str, *, limit: int | None = None) -> dict:
        raise NotImplementedError("IDC adapter is not implemented yet (owner: member-4)")

    def build_profile(self, raw: dict) -> DatasetProfile:
        raise NotImplementedError("IDC adapter is not implemented yet (owner: member-4)")
