from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    strategy: str
    params: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "strategy": self.strategy,
            "params": dict(self.params),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExperimentSpec":
        created_at = payload.get("created_at")
        return cls(
            experiment_id=str(payload["experiment_id"]),
            strategy=str(payload["strategy"]),
            params=dict(payload.get("params", {})),
            created_at=datetime.fromisoformat(created_at) if created_at else utc_now(),
        )


@dataclass(frozen=True)
class EvaluationResult:
    score: float
    metrics: Mapping[str, float] = field(default_factory=dict)
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": float(self.score),
            "metrics": dict(self.metrics),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvaluationResult":
        return cls(
            score=float(payload["score"]),
            metrics=dict(payload.get("metrics", {})),
            notes=payload.get("notes"),
        )


@dataclass(frozen=True)
class ExperimentResult:
    run_id: str
    spec: ExperimentSpec
    evaluator_name: str
    evaluation: EvaluationResult
    git_lineage: Mapping[str, Any]
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "spec": self.spec.to_dict(),
            "evaluator_name": self.evaluator_name,
            "evaluation": self.evaluation.to_dict(),
            "git_lineage": dict(self.git_lineage),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExperimentResult":
        return cls(
            run_id=str(payload["run_id"]),
            spec=ExperimentSpec.from_dict(payload["spec"]),
            evaluator_name=str(payload["evaluator_name"]),
            evaluation=EvaluationResult.from_dict(payload["evaluation"]),
            git_lineage=dict(payload.get("git_lineage", {})),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            finished_at=datetime.fromisoformat(str(payload["finished_at"])),
        )
