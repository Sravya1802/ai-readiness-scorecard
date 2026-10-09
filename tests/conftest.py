from pathlib import Path

import pytest

from scorecard.adapters import get_adapter
from scorecard.profile import DatasetProfile
from scorecard.tasks import Task, load_task

FIXTURE = Path(__file__).parent / "fixtures" / "gdc_tcga_brca_40.json"


@pytest.fixture(scope="session")
def profile() -> DatasetProfile:
    """40 real open-access TCGA-BRCA cases, captured with `scorecard snapshot --limit 40`."""
    return get_adapter("gdc").load_snapshot(FIXTURE)


@pytest.fixture(scope="session")
def task() -> Task:
    return load_task("survival-prediction")
