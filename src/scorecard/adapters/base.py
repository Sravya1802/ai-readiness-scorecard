"""Adapter interface: one repository in, one DatasetProfile out.

An adapter has two halves, kept apart on purpose:

  fetch_raw      talks to the repository and returns a JSON-serializable snapshot
  build_profile  is a pure function from that snapshot to a DatasetProfile

Splitting them means a run can be reproduced from a saved snapshot, tests never
need the network, and the snapshot hash in the provenance record identifies
exactly what was assessed.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from scorecard.profile import DatasetProfile

_REGISTRY: dict[str, type[Adapter]] = {}


def default_cache_dir() -> Path:
    return Path(
        os.environ.get("SCORECARD_CACHE_DIR", Path.home() / ".cache" / "ai-readiness-scorecard")
    )


class Adapter(ABC):
    name: ClassVar[str]
    repository: ClassVar[str]
    version: ClassVar[str] = "0.1.0"
    # Modalities this adapter can report per-patient presence for.
    modalities: ClassVar[tuple[str, ...]] = ()
    implemented: ClassVar[bool] = True
    # False for sources that cannot be joined to other repositories per patient
    # (for example population registries such as SEER).
    linkable: ClassVar[bool] = True
    owner: ClassVar[str] = "lead"

    @abstractmethod
    def fetch_raw(self, dataset: str, *, limit: int | None = None) -> dict:
        """Download a snapshot of `dataset`. `limit` caps the number of patients (dev use)."""

    @abstractmethod
    def build_profile(self, raw: dict) -> DatasetProfile:
        """Turn a snapshot into a DatasetProfile. Must not touch the network."""

    def load(
        self,
        dataset: str,
        *,
        cache_dir: Path | None = None,
        refresh: bool = False,
        limit: int | None = None,
    ) -> DatasetProfile:
        """Fetch (or reuse a cached snapshot of) `dataset` and build its profile."""
        if limit is not None:
            return self.build_profile(self.fetch_raw(dataset, limit=limit))
        path = (cache_dir or default_cache_dir()) / self.name / f"{dataset}.json"
        if path.exists() and not refresh:
            return self.load_snapshot(path)
        raw = self.fetch_raw(dataset)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw))
        return self.build_profile(raw)

    def load_snapshot(self, path: str | Path) -> DatasetProfile:
        return self.build_profile(json.loads(Path(path).read_text()))


def register_adapter(cls: type[Adapter]) -> type[Adapter]:
    if cls.name in _REGISTRY:
        raise ValueError(f"adapter {cls.name!r} is already registered")
    _REGISTRY[cls.name] = cls
    return cls


def get_adapter(name: str) -> Adapter:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise KeyError(f"unknown adapter {name!r}; available: {sorted(_REGISTRY)}") from None


def list_adapters() -> list[type[Adapter]]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]
