"""Non-DB contracts for the real Alembic CLI path."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
EXPECTED_ROOT = "canonical_baseline_v1"
EXPECTED_HEAD = "canonical_baseline_v1"
EXPECTED_REVISION_COUNT = 1


def _run_alembic(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "alembic", *arguments]
    result = subprocess.run(
        command,
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "\n".join(
                (
                    f"command: {subprocess.list2cmdline(command)}",
                    f"exit code: {result.returncode}",
                    f"stdout:\n{result.stdout}",
                    f"stderr:\n{result.stderr}",
                )
            ),
            pytrace=False,
        )
    return result


def test_alembic_001_heads_has_exactly_one_expected_head() -> None:
    """TEST-B03-ALEMBIC-001."""
    result = _run_alembic(["heads"])
    head_lines = [line for line in result.stdout.splitlines() if line.strip()]

    assert len(head_lines) == 1
    assert head_lines[0].split()[0] == EXPECTED_HEAD


def test_alembic_002_history_contains_expected_graph() -> None:
    """TEST-B03-ALEMBIC-002."""
    result = _run_alembic(["history"])
    history_lines = [line for line in result.stdout.splitlines() if line.strip()]

    assert EXPECTED_ROOT in result.stdout
    assert EXPECTED_HEAD in result.stdout
    assert len(history_lines) == EXPECTED_REVISION_COUNT
