from __future__ import annotations

import hashlib
import json

from q_lab.evaluators.base import BaseEvaluator
from q_lab.models import EvaluationResult, ExperimentSpec


class DeterministicEvaluator(BaseEvaluator):
    """A deterministic evaluator for scaffold testing and development."""

    name = "deterministic_v1"

    def evaluate(self, spec: ExperimentSpec) -> EvaluationResult:
        signature = json.dumps(
            {"strategy": spec.strategy, "params": dict(spec.params)},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        scalar = int(digest[:8], 16) / float(0xFFFFFFFF)
        score = round(scalar, 6)
        sharpe_like = round(0.4 + (score * 2.2), 4)
        drawdown_like = round(0.35 - (score * 0.2), 4)
        return EvaluationResult(
            score=score,
            metrics={
                "sharpe_like": sharpe_like,
                "max_drawdown_like": drawdown_like,
            },
            notes="Deterministic placeholder evaluator for MVP scaffolding.",
        )
