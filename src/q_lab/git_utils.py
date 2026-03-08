from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class GitLineage:
    commit_sha: str
    branch: str
    is_dirty: bool
    origin_url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or f"git command failed: {' '.join(args)}"
        raise RuntimeError(message)
    return result.stdout.strip()


def get_git_lineage(repo_path: str | Path = ".") -> GitLineage:
    cwd = Path(repo_path)

    try:
        commit_sha = _git(["rev-parse", "HEAD"], cwd)
    except Exception:
        commit_sha = "unknown"

    try:
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    except Exception:
        branch = "unknown"

    try:
        dirty_output = _git(["status", "--porcelain"], cwd)
        is_dirty = bool(dirty_output)
    except Exception:
        is_dirty = False

    try:
        origin_url = _git(["config", "--get", "remote.origin.url"], cwd) or None
    except Exception:
        origin_url = None

    return GitLineage(
        commit_sha=commit_sha,
        branch=branch,
        is_dirty=is_dirty,
        origin_url=origin_url,
    )
