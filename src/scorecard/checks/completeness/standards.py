"""Standards conformance (stub). Owner: member-3.

Coverage asks "is a value there?". Conformance asks "is the value a valid code
in the standard it claims?". A dataset can be complete and still unusable
across repositories if its codes do not conform.
"""

from __future__ import annotations

from scorecard.checks.base import Criterion, Family, StubCheck
from scorecard.checks.registry import register_check


@register_check
class StandardsConformance(StubCheck):
    """Do present values conform to AJCC, ICD-O-3, ICD-10 and mCODE?

    Spec
      - ajcc_pathologic_stage / _t / _n / _m: value in the AJCC vocabulary for the
        edition in ajcc_staging_system_edition (GDC permissible values are a good
        starting list).
      - morphology: ICD-O-3 morphology, regex ^\\d{4}/[0-3]$.
      - icd_10_code: ICD-10 neoplasm code, regex ^C\\d{2}(\\.\\d{1,2})?$ (and D codes
        for in situ), checked against primary_site where possible.
      - mCODE: report which mCODE profiles (CancerConditionParent, TNMStageGroup,
        TumorMarkerTest, CancerRelatedMedicationStatement, ...) the profile has
        enough fields to populate. Report as partial / full, not pass/fail.
      - Score: share of present values that conform. Evidence: invalid values with
        counts and example patient ids.
      - Put vocabularies in packs/ as data files, not in code.
    """

    id = "completeness.standards_conformance"
    title = "Standards conformance"
    family = Family.COMPLETENESS
    criteria = (Criterion.FAIRNESS,)
    owner = "member-3"
    order = 50
    description = "AJCC staging, ICD-O, ICD-10, mCODE"
