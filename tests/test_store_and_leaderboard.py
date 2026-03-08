from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from q_lab.leaderboard import Leaderboard, build_leaderboard
from q_lab.models import EvaluationResult, ExperimentResult, ExperimentSpec
from q_lab.store import JsonlResultsStore


def _make_result(run_id: str, experiment_id: str, strategy: str, score: float) -> ExperimentResult:
    return ExperimentResult(
        run_id=run_id,
        spec=ExperimentSpec(experiment_id=experiment_id, strategy=strategy),
        evaluator_name="unit_test",
        evaluation=EvaluationResult(score=score),
        git_lineage={"commit_sha": "abc", "branch": "main", "is_dirty": False},
    )


class TestStoreAndLeaderboard(unittest.TestCase):
    def test_jsonl_store_roundtrip(self):
        with TemporaryDirectory() as temp_dir:
            store = JsonlResultsStore(Path(temp_dir) / "results.jsonl")
            first = _make_result("run-1", "exp-1", "momentum", 0.5)
            second = _make_result("run-2", "exp-2", "mean_reversion", 0.9)
            store.append(first)
            store.append(second)

            runs = store.list_runs()
            self.assertEqual(len(runs), 2)
            self.assertEqual(runs[0].run_id, "run-1")
            self.assertEqual(runs[1].evaluation.score, 0.9)

    def test_leaderboard_ranks_highest_score_first(self):
        with TemporaryDirectory() as temp_dir:
            store = JsonlResultsStore(Path(temp_dir) / "results.jsonl")
            store.append(_make_result("run-a", "exp-a", "s1", 0.4))
            store.append(_make_result("run-b", "exp-b", "s2", 0.8))
            store.append(_make_result("run-c", "exp-c", "s3", 0.7))

            entries = Leaderboard(store).top(limit=2)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].run_id, "run-b")
            self.assertEqual(entries[1].run_id, "run-c")

            direct_entries = build_leaderboard(store.list_runs(), limit=1)
            self.assertEqual(direct_entries[0].score, 0.8)


if __name__ == "__main__":
    unittest.main()
