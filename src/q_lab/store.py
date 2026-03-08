from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from q_lab.models import ExperimentResult


class ResultsStore(Protocol):
    def append(self, result: ExperimentResult) -> None:
        """Persist an experiment result."""

    def list_runs(self) -> list[ExperimentResult]:
        """Read all persisted experiment results."""


class JsonlResultsStore:
    """File-backed append-only JSONL result store."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, result: ExperimentResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result.to_dict(), sort_keys=True))
            handle.write("\n")

    def list_runs(self) -> list[ExperimentResult]:
        if not self.path.exists():
            return []

        runs: list[ExperimentResult] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                record = line.strip()
                if not record:
                    continue
                runs.append(ExperimentResult.from_dict(json.loads(record)))
        return runs
