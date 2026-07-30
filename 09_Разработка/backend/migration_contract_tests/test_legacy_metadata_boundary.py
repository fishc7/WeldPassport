from __future__ import annotations

from pathlib import Path
import subprocess
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        check=False,
        capture_output=True,
        text=True,
    )


def test_legacy_metadata_001_uses_a_physically_separate_registry() -> None:
    result = _run_python(
        """
from app.shared.orm import Base
before = tuple(sorted(Base.metadata.tables))
from app.workforce.legacy_orm import LegacyBase, bind_legacy_schema
bind_legacy_schema("legacy_fixture")
import app.workforce.models
assert tuple(sorted(Base.metadata.tables)) == before
assert LegacyBase.metadata is not Base.metadata
assert len(LegacyBase.metadata.tables) == 7
assert {table.schema for table in LegacyBase.metadata.tables.values()} == {
    "legacy_fixture"
}
"""
    )

    assert result.returncode == 0, result.stderr


def test_legacy_metadata_002_same_schema_bind_is_idempotent() -> None:
    result = _run_python(
        """
from app.workforce.legacy_orm import bind_legacy_schema, get_bound_legacy_schema
assert bind_legacy_schema("legacy_fixture") == "legacy_fixture"
assert bind_legacy_schema("legacy_fixture") == "legacy_fixture"
assert get_bound_legacy_schema() == "legacy_fixture"
"""
    )

    assert result.returncode == 0, result.stderr


def test_legacy_metadata_003_different_schema_rebind_fails_closed() -> None:
    result = _run_python(
        """
from app.shared.runtime_profile import RuntimeContractError
from app.workforce.legacy_orm import bind_legacy_schema
bind_legacy_schema("legacy_fixture")
try:
    bind_legacy_schema("different_fixture")
except RuntimeContractError as error:
    assert error.code == "LEGACY-CONTRACT-MISMATCH"
    assert error.safe_detail == "legacy schema is already bound"
else:
    raise AssertionError("different legacy schema rebind was accepted")
"""
    )

    assert result.returncode == 0, result.stderr


def test_legacy_metadata_004_standalone_import_binds_test_schema() -> None:
    result = _run_python(
        """
from app.workforce.legacy_orm import LegacyBase, get_bound_legacy_schema
import app.workforce.models
assert get_bound_legacy_schema() == "test"
assert {table.schema for table in LegacyBase.metadata.tables.values()} == {"test"}
"""
    )

    assert result.returncode == 0, result.stderr
