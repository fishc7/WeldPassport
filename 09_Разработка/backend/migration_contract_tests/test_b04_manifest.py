"""Pure contracts for the B-04 frozen historical-revision manifest."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from migrations.b04.manifest import (
    ManifestError,
    build_frozen_manifest,
    canonical_json_bytes,
    parse_revision,
    sha256_hex,
    verify_manifest_artifact,
    verify_manifest_files,
)
from migrations.b04.source_contract import (
    HISTORICAL_HEAD,
    HISTORICAL_REVISION_COUNT,
    HISTORICAL_ROOT,
    SCHEMA_SOURCE_COMMIT,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = BACKEND_ROOT / "migrations" / "versions"
ARCHIVE_PREFIX = "migrations/archive/canonical_baseline_v1/revisions/"
SOURCE_PREFIX = "migrations/versions/"


def test_b04_manifest_001_is_deterministic() -> None:
    left = canonical_json_bytes({"b": 2, "a": [3, 1]})
    right = canonical_json_bytes({"a": [3, 1], "b": 2})

    assert left == right == b'{"a":[3,1],"b":2}\n'
    assert left.decode("utf-8")
    assert left.endswith(b"\n")


def test_b04_manifest_002_parses_literals_without_executing_revision_module(
    tmp_path: Path,
) -> None:
    revision = tmp_path / "unsafe.py"
    revision.write_text(
        "revision: str = 'unsafe_revision'\n"
        "down_revision = None\n"
        "raise RuntimeError('revision module must never execute')\n",
        encoding="utf-8",
    )

    record = parse_revision(revision)

    assert record.revision == "unsafe_revision"
    assert record.down_revision is None
    assert record.filename == "unsafe.py"


def test_b04_manifest_002a_requires_explicit_down_revision_literal(tmp_path: Path) -> None:
    revision = tmp_path / "missing_down_revision.py"
    revision.write_text("revision = 'missing_down_revision'\n", encoding="utf-8")

    with pytest.raises(ManifestError, match="B04-MANIFEST-MISSING-LITERAL"):
        parse_revision(revision)


def test_b04_manifest_003_raw_byte_digest_changes_after_any_edit(tmp_path: Path) -> None:
    revision = tmp_path / "revision.py"
    revision.write_bytes(b"first\r\n")
    first = sha256_hex(revision.read_bytes())
    revision.write_bytes(b"first\n")
    second = sha256_hex(revision.read_bytes())

    assert first == hashlib.sha256(b"first\r\n").hexdigest()
    assert first != second


def test_b04_manifest_004_builds_the_accepted_closed_linear_graph() -> None:
    manifest = build_frozen_manifest(VERSIONS_DIR)
    entries = manifest["revisions"]

    assert manifest["source_commit"] == SCHEMA_SOURCE_COMMIT
    assert manifest["historical_root"] == HISTORICAL_ROOT
    assert manifest["historical_head"] == HISTORICAL_HEAD
    assert manifest["historical_revision_count"] == HISTORICAL_REVISION_COUNT
    assert len(entries) == HISTORICAL_REVISION_COUNT
    assert [entry["revision"] for entry in entries][0] == HISTORICAL_ROOT
    assert [entry["revision"] for entry in entries][-1] == HISTORICAL_HEAD
    assert len({entry["revision"] for entry in entries}) == HISTORICAL_REVISION_COUNT
    assert entries[0]["down_revision"] is None
    assert [entry["down_revision"] for entry in entries[1:]] == [
        entry["revision"] for entry in entries[:-1]
    ]


def test_b04_manifest_005_uses_exact_portable_source_and_archive_paths() -> None:
    manifest = build_frozen_manifest(VERSIONS_DIR)

    for entry in manifest["revisions"]:
        filename = entry["filename"]
        assert entry["source_path"] == f"{SOURCE_PREFIX}{filename}"
        assert entry["archive_path"] == f"{ARCHIVE_PREFIX}{filename}"
        assert "\\" not in entry["source_path"]
        assert "\\" not in entry["archive_path"]


def test_b04_manifest_006_verification_fails_closed_for_tree_drift(tmp_path: Path) -> None:
    source_root = tmp_path / "backend"
    versions_dir = source_root / "migrations" / "versions"
    versions_dir.mkdir(parents=True)
    previous: str | None = None
    for index in range(1, HISTORICAL_REVISION_COUNT + 1):
        revision = HISTORICAL_ROOT if index == 1 else f"revision_{index:02d}"
        if index == HISTORICAL_REVISION_COUNT:
            revision = HISTORICAL_HEAD
        (versions_dir / f"{index:02d}.py").write_text(
            f"revision = {revision!r}\n"
            f"down_revision = {previous!r}\n",
            encoding="utf-8",
        )
        previous = revision

    manifest = build_frozen_manifest(versions_dir)
    verify_manifest_files(manifest, source_root, archived=False)

    (versions_dir / "extra.py").write_text(
        "revision = 'extra'\ndown_revision = None\n", encoding="utf-8"
    )
    with pytest.raises(ManifestError):
        verify_manifest_files(manifest, source_root, archived=False)
    (versions_dir / "extra.py").unlink()

    target = versions_dir / manifest["revisions"][0]["filename"]
    target.write_bytes(target.read_bytes() + b"# byte edit\n")
    with pytest.raises(ManifestError):
        verify_manifest_files(manifest, source_root, archived=False)

    malformed = copy.deepcopy(manifest)
    malformed["revisions"][0]["source_path"] = "../escape.py"
    with pytest.raises(ManifestError):
        verify_manifest_files(malformed, source_root, archived=False)


def test_b04_manifest_006a_verification_rejects_a_missing_expected_file(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "backend"
    versions_dir = source_root / "migrations" / "versions"
    versions_dir.mkdir(parents=True)
    previous: str | None = None
    for index in range(1, HISTORICAL_REVISION_COUNT + 1):
        revision = HISTORICAL_ROOT if index == 1 else f"revision_{index:02d}"
        if index == HISTORICAL_REVISION_COUNT:
            revision = HISTORICAL_HEAD
        (versions_dir / f"{index:02d}.py").write_text(
            f"revision = {revision!r}\n"
            f"down_revision = {previous!r}\n",
            encoding="utf-8",
        )
        previous = revision
    manifest = build_frozen_manifest(versions_dir)

    (versions_dir / manifest["revisions"][0]["filename"]).unlink()

    with pytest.raises(ManifestError, match="B04-MANIFEST-MISSING-OR-EXTRA"):
        verify_manifest_files(manifest, source_root, archived=False)


def test_b04_manifest_007_rejects_duplicate_non_linear_and_out_of_bound_entries() -> None:
    manifest = build_frozen_manifest(VERSIONS_DIR)

    duplicate = copy.deepcopy(manifest)
    duplicate["revisions"][1]["revision"] = duplicate["revisions"][0]["revision"]
    with pytest.raises(ManifestError):
        verify_manifest_files(duplicate, BACKEND_ROOT, archived=False)

    non_linear = copy.deepcopy(manifest)
    non_linear["revisions"][1]["down_revision"] = None
    with pytest.raises(ManifestError):
        verify_manifest_files(non_linear, BACKEND_ROOT, archived=False)

    out_of_bound = copy.deepcopy(manifest)
    out_of_bound["revisions"][0]["archive_path"] = "migrations/versions/other.py"
    with pytest.raises(ManifestError):
        verify_manifest_files(out_of_bound, BACKEND_ROOT, archived=False)


def test_b04_manifest_008_generated_artifacts_have_a_verified_digest() -> None:
    output_dir = (
        BACKEND_ROOT
        / "migrations"
        / "baselines"
        / "canonical_baseline_v1"
    )
    manifest_bytes = (output_dir / "frozen-revision-manifest.json").read_bytes()
    digest_bytes = (output_dir / "frozen-revision-manifest.sha256").read_bytes()
    cut = json.loads((output_dir / "cut.json").read_text(encoding="utf-8"))

    assert digest_bytes == (
        f"{sha256_hex(manifest_bytes)}  frozen-revision-manifest.json\n".encode("ascii")
    )
    assert cut == {
        "historical_head": HISTORICAL_HEAD,
        "historical_revision_count": HISTORICAL_REVISION_COUNT,
        "historical_root": HISTORICAL_ROOT,
        "source_commit": SCHEMA_SOURCE_COMMIT,
    }
    verify_manifest_files(json.loads(manifest_bytes), BACKEND_ROOT, archived=False)


def test_b04_manifest_009_rejects_crlf_digest_bytes(tmp_path: Path) -> None:
    output_dir = (
        BACKEND_ROOT
        / "migrations"
        / "baselines"
        / "canonical_baseline_v1"
    )
    manifest_path = tmp_path / "frozen-revision-manifest.json"
    digest_path = tmp_path / "frozen-revision-manifest.sha256"
    shutil.copyfile(output_dir / "frozen-revision-manifest.json", manifest_path)
    shutil.copyfile(output_dir / "frozen-revision-manifest.sha256", digest_path)
    verify_manifest_artifact(manifest_path, BACKEND_ROOT)

    digest_path.write_bytes(digest_path.read_bytes().replace(b"\n", b"\r\n"))

    with pytest.raises(ManifestError, match="B04-MANIFEST-DIGEST"):
        verify_manifest_artifact(manifest_path, BACKEND_ROOT)


def test_b04_manifest_010_verifies_source_and_archived_files_are_regular(tmp_path: Path) -> None:
    source_root = tmp_path / "backend"
    source_versions = source_root / "migrations" / "versions"
    source_versions.mkdir(parents=True)
    previous: str | None = None
    for index in range(1, HISTORICAL_REVISION_COUNT + 1):
        revision = HISTORICAL_ROOT if index == 1 else f"revision_{index:02d}"
        if index == HISTORICAL_REVISION_COUNT:
            revision = HISTORICAL_HEAD
        (source_versions / f"{index:02d}.py").write_text(
            f"revision = {revision!r}\n"
            f"down_revision = {previous!r}\n",
            encoding="utf-8",
        )
        previous = revision
    manifest = build_frozen_manifest(source_versions)
    archive_dir = source_root / "migrations" / "archive" / "canonical_baseline_v1" / "revisions"
    archive_dir.mkdir(parents=True)
    for entry in manifest["revisions"]:
        shutil.copyfile(source_versions / entry["filename"], archive_dir / entry["filename"])

    verify_manifest_files(manifest, source_root, archived=False)
    verify_manifest_files(manifest, source_root, archived=True)

    (archive_dir / manifest["revisions"][0]["filename"]).unlink()
    (archive_dir / manifest["revisions"][0]["filename"]).mkdir()
    with pytest.raises(ManifestError, match="B04-MANIFEST-NONREGULAR-FILE"):
        verify_manifest_files(manifest, source_root, archived=True)


def test_b04_manifest_011_rejects_root_and_expected_directory_symlinks_or_mocked_equivalent(
    tmp_path: Path,
) -> None:
    import migrations.b04.manifest as manifest_module

    root = tmp_path / "backend"
    root.mkdir()
    regular_file = root / "regular.py"
    regular_file.write_text("# regular\n", encoding="utf-8")
    with patch.object(Path, "is_symlink", autospec=True) as is_symlink:
        is_symlink.side_effect = lambda path: path == root
        with pytest.raises(ManifestError, match="B04-MANIFEST-SYMLINK"):
            manifest_module._resolve_regular_file(root, regular_file)

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "root-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege is unavailable; helper boundary is mocked above")
    with pytest.raises(ManifestError, match="B04-MANIFEST-SYMLINK"):
        manifest_module._resolve_regular_file(link, target / "missing.py")

    expected_directory_root = tmp_path / "expected-directory-root"
    expected_directory_root.joinpath("migrations").mkdir(parents=True)
    expected_directory_link = expected_directory_root / "migrations" / "versions"
    expected_directory_link.symlink_to(VERSIONS_DIR, target_is_directory=True)
    with pytest.raises(ManifestError, match="B04-MANIFEST-SYMLINK"):
        verify_manifest_files(
            build_frozen_manifest(VERSIONS_DIR), expected_directory_root, archived=False
        )
