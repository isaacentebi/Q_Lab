from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Protocol

from q_lab.models import ExperimentSpec
from q_lab.runner import ExperimentRunner

logger = logging.getLogger(__name__)


class ExperimentSource(Protocol):
    def next_experiments(self) -> list[ExperimentSpec]:
        """Return the next experiment batch to execute."""


class ListExperimentSource:
    """Simple one-shot source for static experiment lists."""

    def __init__(self, experiments: list[ExperimentSpec]):
        self._pending = list(experiments)

    def next_experiments(self) -> list[ExperimentSpec]:
        if not self._pending:
            return []
        batch = list(self._pending)
        self._pending.clear()
        return batch


@dataclass(frozen=True)
class SchedulerStats:
    cycles: int
    runs_executed: int
    failures: int


class SchedulerLoop:
    """Polls experiment sources and dispatches runs."""

    def __init__(
        self,
        source: ExperimentSource,
        runner: ExperimentRunner,
        poll_interval_seconds: float = 1.0,
    ):
        self.source = source
        self.runner = runner
        self.poll_interval_seconds = max(0.0, poll_interval_seconds)

    def run(self, max_cycles: int | None = None) -> SchedulerStats:
        cycles = 0
        runs_executed = 0
        failures = 0

        while max_cycles is None or cycles < max_cycles:
            batch = self.source.next_experiments()
            for spec in batch:
                try:
                    self.runner.run(spec)
                    runs_executed += 1
                except Exception:
                    failures += 1
                    logger.exception("Failed experiment: %s", spec.experiment_id)

            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            if self.poll_interval_seconds > 0:
                time.sleep(self.poll_interval_seconds)

        return SchedulerStats(cycles=cycles, runs_executed=runs_executed, failures=failures)
