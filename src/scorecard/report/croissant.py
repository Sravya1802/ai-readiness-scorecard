"""Croissant metadata (stub). Owner: member-4.

Croissant (MLCommons, https://mlcommons.org/croissant/) is JSON-LD that ML
frameworks can load a dataset from directly.

What build_croissant should return
  - Dataset-level: name, description, url (the GDC project page), license
    (GDC open access: NIH GDS policy), citeAs, version (data release),
    datePublished (retrieved_at).
  - distribution: one FileObject per source the profile was built from (for
    GDC: the API query in provenance.query, plus file ids for modalities).
  - recordSet "patients": one field per column of profile.features, typed from
    the pandas dtype, with the FeatureMeta description and source_field.
  - The RAI extension (http://mlcommons.org/croissant/RAI/) is where the
    scorecard's findings belong: dataBiases from site effects and confounding,
    dataLimitations from completeness gaps, each pointing to the data card.
  - Validate with the `mlcroissant` package before calling it done.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scorecard.pipeline import Run

IMPLEMENTED = False


def build_croissant(run: Run) -> dict:
    raise NotImplementedError("Croissant export is not implemented yet (owner: member-4)")
