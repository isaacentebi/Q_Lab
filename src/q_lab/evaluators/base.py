from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from q_lab.models import EvaluationResult, ExperimentSpec


class Evaluator(Protocol):
    name: str

    def evaluate(self, spec: ExperimentSpec) -> EvaluationResult:
        """Evaluate one experiment spec and return scored outputs."""


class BaseEvaluator(ABC):
    name = "base"

    @abstractmethod
    def evaluate(self, spec: ExperimentSpec) -> EvaluationResult:
        """Evaluate one experiment spec and return scored outputs."""
