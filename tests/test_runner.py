from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from q_lab.evaluators.base import BaseEvaluator
from q_lab.git_utils import GitLineage
from q_lab.models import EvaluationResult, ExperimentSpec
from q_lab.runner import ExperimentRunner
from q_lab.store import JsonlResultsStore


class FixedEvaluator(BaseEvaluator):
    name = "fixed_eval"

    def evaluate(self, spec: ExperimentSpec) -> EvaluationResult:
        return EvaluationResult(score=0.42, metrics={"sharpe_like": 1.1})


class TestExperimentRunner(unittest.TestCase):
    def test_runner_persists_result(self):
        with TemporaryDirectory() as temp_dir:
            store = JsonlResultsStore(Path(temp_dir) / "results.jsonl")

            def lineage_provider() -> GitLineage:
                return GitLineage(
                    commit_sha="abc123",
                    branch="main",
                    is_dirty=False,
                    origin_url="git@example.com/repo.git",
                )

            runner = ExperimentRunner(
                evaluator=FixedEvaluator(),
                store=store,
                lineage_provider=lineage_provider,
            )
            spec = ExperimentSpec(
                experiment_id="exp-1",
                strategy="momentum",
                params={"lookback": 20},
            )
            result = runner.run(spec)

            stored = store.list_runs()
            self.assertEqual(result.evaluator_name, "fixed_eval")
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].run_id, result.run_id)
            self.assertEqual(stored[0].evaluation.score, 0.42)
            self.assertEqual(stored[0].git_lineage["commit_sha"], "abc123")


if __name__ == "__main__":
    unittest.main()
