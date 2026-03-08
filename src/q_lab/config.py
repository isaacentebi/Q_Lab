from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib
from typing import Any

from q_lab.models import ExperimentSpec


@dataclass(frozen=True)
class SchedulerConfig:
    poll_interval_seconds: float = 1.0
    max_cycles: int | None = 1


@dataclass(frozen=True)
class StoreConfig:
    results_path: Path = Path("data/results.jsonl")


@dataclass(frozen=True)
class AppConfig:
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
    experiments: list[ExperimentSpec] = field(default_factory=list)


def _to_spec(index: int, payload: dict[str, Any]) -> ExperimentSpec:
    if "strategy" not in payload:
        raise ValueError(f"Missing 'strategy' for experiments[{index}]")
    return ExperimentSpec(
        experiment_id=str(payload.get("experiment_id", f"exp-{index + 1}")),
        strategy=str(payload["strategy"]),
        params=dict(payload.get("params", {})),
    )


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)

    scheduler_section = dict(payload.get("scheduler", {}))
    store_section = dict(payload.get("store", {}))
    experiments_section = list(payload.get("experiments", []))

    raw_max_cycles = scheduler_section.get("max_cycles", 1)
    max_cycles = None if raw_max_cycles is None else int(raw_max_cycles)
    scheduler = SchedulerConfig(
        poll_interval_seconds=float(scheduler_section.get("poll_interval_seconds", 1.0)),
        max_cycles=max_cycles,
    )
    store = StoreConfig(
        results_path=Path(store_section.get("results_path", "data/results.jsonl"))
    )
    experiments = [_to_spec(index, item) for index, item in enumerate(experiments_section)]
    return AppConfig(scheduler=scheduler, store=store, experiments=experiments)
