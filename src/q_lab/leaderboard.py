from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from q_lab.models import ExperimentResult
from q_lab.store import ResultsStore


@dataclass(frozen=True)
class LeaderboardEntry:
    rank: int
    run_id: str
    experiment_id: str
    strategy: str
    score: float


def build_leaderboard(
    runs: Iterable[ExperimentResult],
    limit: int = 10,
) -> list[LeaderboardEntry]:
    sorted_runs = sorted(runs, key=lambda run: run.evaluation.score, reverse=True)
    entries: list[LeaderboardEntry] = []
    for index, run in enumerate(sorted_runs[:limit], start=1):
        entries.append(
            LeaderboardEntry(
                rank=index,
                run_id=run.run_id,
                experiment_id=run.spec.experiment_id,
                strategy=run.spec.strategy,
                score=run.evaluation.score,
            )
        )
    return entries


class Leaderboard:
    def __init__(self, store: ResultsStore):
        self.store = store

    def top(self, limit: int = 10) -> list[LeaderboardEntry]:
        return build_leaderboard(self.store.list_runs(), limit=limit)
