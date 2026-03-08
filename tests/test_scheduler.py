import unittest

from q_lab.models import ExperimentSpec
from q_lab.scheduler import ListExperimentSource, SchedulerLoop


class RecordingRunner:
    def __init__(self, fail_id: str | None = None):
        self.fail_id = fail_id
        self.calls: list[str] = []

    def run(self, spec: ExperimentSpec):
        self.calls.append(spec.experiment_id)
        if spec.experiment_id == self.fail_id:
            raise RuntimeError("intentional failure")
        return None


class TestScheduler(unittest.TestCase):
    def test_scheduler_executes_batch_once(self):
        specs = [
            ExperimentSpec(experiment_id="exp-1", strategy="momentum"),
            ExperimentSpec(experiment_id="exp-2", strategy="mean_reversion"),
        ]
        source = ListExperimentSource(specs)
        runner = RecordingRunner()
        scheduler = SchedulerLoop(source=source, runner=runner, poll_interval_seconds=0)

        stats = scheduler.run(max_cycles=1)
        self.assertEqual(stats.cycles, 1)
        self.assertEqual(stats.runs_executed, 2)
        self.assertEqual(stats.failures, 0)
        self.assertEqual(runner.calls, ["exp-1", "exp-2"])

    def test_scheduler_counts_failures_and_continues(self):
        specs = [
            ExperimentSpec(experiment_id="exp-1", strategy="momentum"),
            ExperimentSpec(experiment_id="exp-2", strategy="mean_reversion"),
        ]
        source = ListExperimentSource(specs)
        runner = RecordingRunner(fail_id="exp-2")
        scheduler = SchedulerLoop(source=source, runner=runner, poll_interval_seconds=0)

        stats = scheduler.run(max_cycles=1)
        self.assertEqual(stats.runs_executed, 1)
        self.assertEqual(stats.failures, 1)
        self.assertEqual(runner.calls, ["exp-1", "exp-2"])


if __name__ == "__main__":
    unittest.main()
