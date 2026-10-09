import json

from scorecard.cli import main
from scorecard.pipeline import assess
from scorecard.report import write_outputs
from tests.conftest import FIXTURE


def test_end_to_end_outputs(profile, task, tmp_path):
    run = assess(profile, task)
    written = {p.name for p in write_outputs(run, tmp_path)}
    assert written == {"data_card.html", "scorecard.json", "provenance.json"}

    card = (tmp_path / "data_card.html").read_text()
    for panel in (
        "Task-relative verdict",
        "Bridge2AI criteria profile",
        "Multimodal linkage",
        "Data integrity",
        "Oncology completeness",
        "Outputs",
        "Evidence",
        "PROVISIONAL",
    ):
        assert panel.lower() in card.lower(), panel
    # Every assessed row links to an evidence anchor that exists.
    assert 'href="#ev-integrity-missingness"' in card and 'id="ev-integrity-missingness"' in card

    scorecard = json.loads((tmp_path / "scorecard.json").read_text())
    assert len(scorecard["results"]) == 10
    provenance = json.loads((tmp_path / "provenance.json").read_text())
    assert provenance["data"]["content_sha256"] == profile.provenance.content_sha256
    assert sum(not c["ran"] for c in provenance["checks"]) == 4


def test_cli_profile_from_snapshot(tmp_path, capsys):
    assert main(["profile", "--snapshot", str(FIXTURE), "--out", str(tmp_path)]) == 0
    assert "Verdict:" in capsys.readouterr().out


def test_cli_listings(capsys):
    for command in ("checks", "adapters", "tasks"):
        assert main([command]) == 0
    out = capsys.readouterr().out
    assert "integrity.site_effects" in out and "idc" in out and "survival-prediction" in out
