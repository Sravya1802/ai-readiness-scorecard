"""Oncology completeness checks, one per pack criterion. Owner: member-3.

The variable lists live in packs/oncology.yaml; these classes only give each
criterion an identity on the data card.
"""

from __future__ import annotations

from scorecard.checks.base import Criterion
from scorecard.checks.completeness.engine import PackCriterionCheck
from scorecard.checks.registry import register_check


@register_check
class StageHistologyGrade(PackCriterionCheck):
    id = "completeness.stage_histology_grade"
    criterion_id = "stage_histology_grade"
    title = "Stage, histology & grade"
    criteria = (Criterion.CHARACTERIZATION,)
    order = 10
    description = "TNM staging, tumor grade, primary site"


@register_check
class Treatment(PackCriterionCheck):
    id = "completeness.treatment"
    criterion_id = "treatment"
    title = "Treatment information"
    criteria = (Criterion.CHARACTERIZATION,)
    order = 20
    description = "Surgery, chemotherapy, radiation, immunotherapy"


@register_check
class Outcomes(PackCriterionCheck):
    id = "completeness.outcomes"
    criterion_id = "outcomes"
    title = "Outcomes / survival"
    criteria = (Criterion.COMPUTABILITY,)
    order = 30
    description = "Status, recurrence, follow-up, censoring encoding"


@register_check
class Biomarkers(PackCriterionCheck):
    id = "completeness.biomarkers"
    criterion_id = "biomarkers"
    title = "Actionable biomarkers"
    criteria = (Criterion.CHARACTERIZATION,)
    order = 40
    description = "KRAS, EGFR, HER2, BRAF, MSI, PD-L1"
