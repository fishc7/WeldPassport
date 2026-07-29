from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError

from migrations.b04.manifest import verify_manifest_files


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
ARCHIVE_DIR = (
    MIGRATIONS_DIR / "archive" / "canonical_baseline_v1" / "revisions"
)
MANIFEST_PATH = (
    MIGRATIONS_DIR
    / "baselines"
    / "canonical_baseline_v1"
    / "frozen-revision-manifest.json"
)
HISTORICAL_HEAD = "20260724_27_qd_rbac_sod"


def test_b04_archive_001_exactly_matches_frozen_manifest() -> None:
    manifest = json.loads(MANIFEST_PATH.read_bytes())

    verify_manifest_files(manifest, BACKEND_DIR, archived=True)

    assert len(list(ARCHIVE_DIR.glob("*.py"))) == 31
    assert not list(ARCHIVE_DIR.rglob("__pycache__"))
    assert not list(ARCHIVE_DIR.rglob("*.pyc"))


def test_b04_archive_002_historical_revisions_are_invisible_to_alembic() -> None:
    script = ScriptDirectory.from_config(Config(BACKEND_DIR / "alembic.ini"))

    with pytest.raises(CommandError, match="Can't locate revision"):
        script.get_revision(HISTORICAL_HEAD)
