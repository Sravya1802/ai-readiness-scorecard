import pytest

from scorecard.adapters.gdc import COLUMNS
from scorecard.profile import Role


def test_one_row_per_patient(profile):
    assert profile.n_patients == 40
    assert profile.features.index.is_unique
    assert profile.features.index[0].startswith("TCGA-")


def test_every_column_described(profile):
    assert list(profile.features.columns) == [name for name, *_ in COLUMNS]
    assert set(profile.feature_meta) == set(profile.features.columns)


def test_sentinel_strings_become_missing(profile):
    text = profile.features.astype("string")
    for value in ("Not Reported", "not reported", "Unknown", "unknown"):
        assert not (text == value).any().any(), value
    assert sum(profile.provenance.sentinels_normalized.values()) > 0


def test_site_and_roles(profile):
    assert profile.site_column == "tissue_source_site"
    assert profile.site.notna().all()
    assert "vital_status" in profile.columns_with_role(Role.TARGET)
    assert "gdc_case_id" in profile.columns_with_role(Role.IDENTIFIER)
    # Outcome columns must never be offered to checks as features.
    assert "days_to_death" not in profile.columns_with_role(Role.FEATURE)


def test_follow_up_uses_follow_up_records(profile):
    alive = profile.features["vital_status"] == "Alive"
    assert profile.features.loc[alive, "days_to_last_follow_up"].notna().mean() > 0.9


def test_modalities_are_boolean_and_clinical_complete(profile):
    assert set(profile.modalities.columns) == {"clinical", "gene_expression", "somatic_mutation"}
    assert profile.modalities["clinical"].all()


def test_provenance_hash_is_stable(profile):
    from scorecard.adapters import get_adapter
    from tests.conftest import FIXTURE

    again = get_adapter("gdc").load_snapshot(FIXTURE)
    assert again.provenance.content_sha256 == profile.provenance.content_sha256


@pytest.mark.network
def test_live_fetch_small():
    from scorecard.adapters import get_adapter

    p = get_adapter("gdc").load("TCGA-BRCA", limit=5)
    assert p.n_patients == 5
