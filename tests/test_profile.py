import pandas as pd
import pytest

from scorecard.profile import DatasetProfile, FeatureMeta, ProfileError, Provenance, Role


def _profile(**overrides):
    features = pd.DataFrame({"site": ["A", "B"], "x": [1.0, None]}, index=["p1", "p2"])
    kwargs = dict(
        dataset_id="toy",
        title="Toy",
        description="toy",
        features=features,
        feature_meta={
            "site": FeatureMeta(name="site", modality="clinical", role=Role.SITE),
            "x": FeatureMeta(name="x", modality="clinical"),
        },
        modalities=pd.DataFrame({"clinical": [True, True]}, index=features.index),
        provenance=Provenance(
            adapter="toy",
            adapter_version="0",
            repository="toy",
            retrieved_at="now",
            content_sha256="0",
            n_source_records=2,
        ),
        site_column="site",
    )
    kwargs.update(overrides)
    return DatasetProfile(**kwargs)


def test_valid_profile_summary():
    summary = _profile().summary()
    assert summary.n_patients == 2 and summary.n_features == 1 and summary.n_sites == 2


def test_rejects_duplicate_patients():
    features = pd.DataFrame({"site": ["A", "B"], "x": [1, 2]}, index=["p1", "p1"])
    with pytest.raises(ProfileError, match="one row per patient"):
        _profile(
            features=features,
            modalities=pd.DataFrame({"clinical": [True, True]}, index=features.index),
        )


def test_rejects_undescribed_column():
    with pytest.raises(ProfileError, match="undescribed"):
        _profile(feature_meta={"site": FeatureMeta(name="site", modality="c", role=Role.SITE)})


def test_rejects_site_column_without_site_role():
    meta = {
        "site": FeatureMeta(name="site", modality="clinical"),
        "x": FeatureMeta(name="x", modality="clinical"),
    }
    with pytest.raises(ProfileError, match="role 'site'"):
        _profile(feature_meta=meta)
