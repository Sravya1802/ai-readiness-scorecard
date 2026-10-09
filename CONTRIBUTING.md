# Contributing

## Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest && ruff check . && ruff format --check .
```

## Workflow

1. Branch from `main`: `git switch -c member-2/site-effects`.
2. Keep each PR to one check, one adapter, or one output.
3. Before you push, run `pytest`, `ruff check .` and `ruff format .`. CI runs the same three on Python 3.10 and 3.12.
4. Open a PR and ask the owner of any file you touched outside your area to review it.

## Rules that keep four people from colliding

- **The IR is frozen.** Changes to `profile.py`, `checks/base.py` or `adapters/base.py` go through the lead, because every other module compiles against them. If you need a new field, open an issue first.
- **Checks never fetch data and never change the profile.** They read a `DatasetProfile` and a `Task` and return a `CheckResult`.
- **No hard-coded thresholds.** Put them in the task YAML under `integrity:` or `completeness:` and read them with `task.param(...)`.
- **Every non-PASS result carries evidence**: the columns, counts and example patient ids a reviewer needs to confirm the finding by hand.
- **No leakage in our own code.** Any model a check fits (site predictability, single-feature AUC) is fitted inside cross-validation folds, with preprocessing inside the fold pipeline.
- **Tests run offline.** Use the fixture in `tests/fixtures/`. Mark anything that calls a live API with `@pytest.mark.network`.
- **Only open-access data** goes in the repo.

## Adding a check

1. Create `src/scorecard/checks/integrity/<name>.py`. Copy the structure of `missingness.py`.
2. Subclass `Check`. Set `id`, `title`, `family`, `criteria` (the Bridge2AI axes it informs), `owner`, `order` and `description`. Implement `run(profile, task)`.
3. Decorate the class with `@register_check` and import the module in the package `__init__.py`.
4. If you are replacing a stub, delete it from `stubs.py`, keeping the same `id`.
5. Add tests in `tests/test_checks.py` against the `profile` fixture.

A completeness criterion usually needs no code. Add the variables to `packs/oncology.yaml` and the requirement to the task YAML.

## Adding an adapter

1. Subclass `Adapter` in `src/scorecard/adapters/<repo>.py`.
2. Implement `fetch_raw` (network, returns JSON-serializable data) and `build_profile` (pure, no network).
3. Map source fields onto the canonical column names the GDC adapter uses, so the existing packs work unchanged.
4. Record every missing-value string you normalize in `Provenance.sentinels_normalized`.
5. Capture a small fixture with `scorecard snapshot --adapter <name> --dataset <id> --limit 40 --out tests/fixtures/<name>_<dataset>_40.json` and test against it.
