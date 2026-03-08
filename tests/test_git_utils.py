from types import SimpleNamespace
import unittest
from unittest.mock import patch

from q_lab.git_utils import get_git_lineage


class TestGitUtils(unittest.TestCase):
    def test_get_git_lineage_reads_expected_fields(self):
        outputs = {
            ("rev-parse", "HEAD"): SimpleNamespace(returncode=0, stdout="abc123\n", stderr=""),
            ("rev-parse", "--abbrev-ref", "HEAD"): SimpleNamespace(
                returncode=0, stdout="main\n", stderr=""
            ),
            ("status", "--porcelain"): SimpleNamespace(
                returncode=0, stdout=" M file.py\n", stderr=""
            ),
            ("config", "--get", "remote.origin.url"): SimpleNamespace(
                returncode=0, stdout="git@example.com/repo.git\n", stderr=""
            ),
        }

        def fake_run(cmd, cwd, capture_output, text, check):
            self.assertEqual(cmd[0], "git")
            return outputs[tuple(cmd[1:])]

        with patch("q_lab.git_utils.subprocess.run", side_effect=fake_run):
            lineage = get_git_lineage(".")

        self.assertEqual(lineage.commit_sha, "abc123")
        self.assertEqual(lineage.branch, "main")
        self.assertIs(lineage.is_dirty, True)
        self.assertEqual(lineage.origin_url, "git@example.com/repo.git")

    def test_get_git_lineage_handles_git_errors(self):
        def fake_run(cmd, cwd, capture_output, text, check):
            return SimpleNamespace(returncode=1, stdout="", stderr="not a git repository")

        with patch("q_lab.git_utils.subprocess.run", side_effect=fake_run):
            lineage = get_git_lineage(".")

        self.assertEqual(lineage.commit_sha, "unknown")
        self.assertEqual(lineage.branch, "unknown")
        self.assertIs(lineage.is_dirty, False)
        self.assertIsNone(lineage.origin_url)


if __name__ == "__main__":
    unittest.main()
