from __future__ import annotations

from collections.abc import Mapping
import uuid

from q_lab.evaluators.base import Evaluator
from q_lab.git_utils import GitLineage, get_git_lineage
from q_lab.models import ExperimentResult, ExperimentSpec, utc_now
from q_lab.store import ResultsStore


class ExperimentRunner:
    """Runs a single experiment spec through evaluator + persistence."""

    def __init__(
        self,
        evaluator: Evaluator,
        store: ResultsStore,
        lineage_provider=get_git_lineage,
    ):
        self.evaluator = evaluator
        self.store = store
        self.lineage_provider = lineage_provider

    def run(self, spec: ExperimentSpec) -> ExperimentResult:
        started_at = utc_now()
        evaluation = self.evaluator.evaluate(spec)
        finished_at = utc_now()

        lineage = self.lineage_provider()
        if isinstance(lineage, GitLineage):
            lineage_payload = lineage.to_dict()
        elif isinstance(lineage, Mapping):
            lineage_payload = dict(lineage)
        else:
            raise TypeError("lineage_provider must return GitLineage or mapping")

        result = ExperimentResult(
            run_id=str(uuid.uuid4()),
            spec=spec,
            evaluator_name=self.evaluator.name,
            evaluation=evaluation,
            git_lineage=lineage_payload,
            started_at=started_at,
            finished_at=finished_at,
        )
        self.store.append(result)
        return result
