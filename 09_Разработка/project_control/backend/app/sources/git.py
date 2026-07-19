from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True, slots=True)
class GitStatus:
    branch: str
    commit_sha: str
    latest_subject: str
    is_clean: bool


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def collect_git_status(repo: Path) -> GitStatus:
    return GitStatus(
        branch=_git(repo, "branch", "--show-current"),
        commit_sha=_git(repo, "rev-parse", "HEAD"),
        latest_subject=_git(repo, "log", "-1", "--pretty=%s"),
        is_clean=not bool(_git(repo, "status", "--porcelain")),
    )
