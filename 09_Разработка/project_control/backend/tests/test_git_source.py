import subprocess
from pathlib import Path

from app.sources.git import collect_git_status


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_collects_branch_commit_and_dirty_state_from_real_repository(tmp_path: Path) -> None:
    git(tmp_path, "init", "-b", "feature/demo")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-m", "initial")

    clean = collect_git_status(tmp_path)

    assert clean.branch == "feature/demo"
    assert clean.is_clean is True
    assert clean.latest_subject == "initial"
    assert len(clean.commit_sha) == 40

    (tmp_path / "README.md").write_text("changed", encoding="utf-8")
    dirty = collect_git_status(tmp_path)

    assert dirty.is_clean is False
