"""Integrity checks still to build. Owner: member-2.

Each class is registered so it shows up in `scorecard checks list` and as a
"not yet assessed" row on the data card. To implement one: move it to its own
module (see missingness.py for the pattern), subclass Check instead of
StubCheck, and implement run(). Thresholds are already in the task YAML under
`integrity:`.

The rule for all three: the tool must not leak while measuring leakage. Any
model fitted here is fitted inside cross-validation folds, never on the full
matrix, and preprocessing (imputation, scaling, encoding) happens inside the
fold pipeline too.
"""

from __future__ import annotations

from scorecard.checks.base import Criterion, Family, StubCheck
from scorecard.checks.registry import register_check


@register_check
class SiteEffects(StubCheck):
    """Can a classifier tell which site a patient came from? If so, site is a shortcut.

    Spec
      - X: FEATURE columns, one-hot encoded categoricals, numeric as is, inside an
        sklearn Pipeline with imputation. y: profile.site, with sites smaller than
        min_site_size pooled.
      - Score: cross-validated macro one-vs-rest AUC (StratifiedKFold, cv_folds).
      - Null: repeat with y permuted n_permutations times
        (sklearn.model_selection.permutation_test_score does both).
      - WARN, degrading, when p < alpha. Evidence: observed AUC, null mean and 95th
        percentile, p-value, the ten most site-predictive features.
      - NOT_APPLICABLE when the profile has no site column or only one site.
    """

    id = "integrity.site_effects"
    title = "Batch / site effects"
    family = Family.INTEGRITY
    criteria = (Criterion.CHARACTERIZATION, Criterion.EXPLAINABILITY)
    owner = "member-2"
    order = 30
    description = "Cross-validated site-predictability against a permutation null"


@register_check
class Confounding(StubCheck):
    """Is site associated with the target? Then site effects become outcome shortcuts.

    Spec
      - Cramér's V between profile.site (small sites pooled) and the task target
        (task.survival_target(profile)["event"]), plus the chi-square p-value.
      - WARN, degrading, when V >= cramers_v_warn. Evidence: contingency table of
        the five sites with the most extreme event rates.
      - Optional extension: log-rank test of survival by site.
    """

    id = "integrity.confounding"
    title = "Confounding"
    family = Family.INTEGRITY
    criteria = (Criterion.EXPLAINABILITY,)
    owner = "member-2"
    order = 40
    description = "Association between site and the declared target"


@register_check
class DataLeakage(StubCheck):
    """Would a naive train/test split leak information? Blocking when it would.

    Spec
      - Identifier columns: any FEATURE column that is unique per patient, or whose
        values contain the patient id or a TCGA barcode (regex TCGA-\\w\\w-\\w{4}).
        FAIL, blocking. These should have role IDENTIFIER in the adapter.
      - Patient straddle: when a profile carries more than one row per patient
        (future sample-level profiles) or a split column, count patients appearing
        in more than one split. FAIL, blocking.
      - Near-duplicates: pairs of patients whose feature vectors agree above
        near_duplicate_threshold. WARN, degrading.
      - Target leakage: FEATURE columns that predict the target almost perfectly on
        their own (single-feature CV AUC > 0.95), for example post-outcome fields.
        FAIL, blocking.
      - Evidence: the offending columns and up to ten example patient ids.
    """

    id = "integrity.leakage"
    title = "Data leakage"
    family = Family.INTEGRITY
    criteria = (Criterion.COMPUTABILITY,)
    owner = "member-2"
    order = 50
    description = "Patient-straddle across splits, identifier columns, near-duplicates"
