"""Deterministically freeze and verify the pre-B-04 Alembic revision chain."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from migrations.b04.source_contract import (
    HISTORICAL_HEAD,
    HISTORICAL_REVISION_COUNT,
    HISTORICAL_ROOT,
    SCHEMA_SOURCE_COMMIT,
)


MANIFEST_FILENAME = "frozen-revision-manifest.json"
DIGEST_FILENAME = "frozen-revision-manifest.sha256"
CUT_FILENAME = "cut.json"
SOURCE_PREFIX = PurePosixPath("migrations/versions")
ARCHIVE_PREFIX = PurePosixPath("migrations/archive/canonical_baseline_v1/revisions")


class ManifestError(ValueError):
    """The frozen migration source or manifest violates its fail-closed contract."""


@dataclass(frozen=True)
class RevisionRecord:
    """AST-derived immutable facts about one historical revision file."""

    revision: str
    down_revision: str | None
    filename: str
    data: bytes


def canonical_json_bytes(value: object) -> bytes:
    """Return canonical UTF-8 JSON suitable for content-addressed artifacts."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return the lowercase SHA-256 digest for raw bytes."""
    return hashlib.sha256(data).hexdigest()


def parse_revision(path: Path) -> RevisionRecord:
    """Read revision identifiers through AST literals, without importing the module."""
    data = path.read_bytes()
    try:
        module = ast.parse(data.decode("utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise ManifestError(f"B04-MANIFEST-PARSE: {path}") from exc

    values: dict[str, object] = {}
    for node in module.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if not isinstance(target, ast.Name) or target.id not in {"revision", "down_revision"}:
            continue
        if target.id in values:
            raise ManifestError(f"B04-MANIFEST-DUPLICATE-LITERAL: {path}")
        try:
            values[target.id] = ast.literal_eval(value)
        except (ValueError, TypeError) as exc:
            raise ManifestError(f"B04-MANIFEST-NONLITERAL: {path}") from exc

    if {"revision", "down_revision"} - values.keys():
        raise ManifestError(f"B04-MANIFEST-MISSING-LITERAL: {path}")
    revision = values["revision"]
    down_revision = values["down_revision"]
    if not isinstance(revision, str) or not revision:
        raise ManifestError(f"B04-MANIFEST-REVISION: {path}")
    if down_revision is not None and not isinstance(down_revision, str):
        raise ManifestError(f"B04-MANIFEST-DOWN-REVISION: {path}")
    return RevisionRecord(revision, down_revision, path.name, data)


def _ordered_linear_records(records: Sequence[RevisionRecord]) -> list[RevisionRecord]:
    if len(records) != HISTORICAL_REVISION_COUNT:
        raise ManifestError("B04-MANIFEST-REVISION-COUNT")
    by_revision = {record.revision: record for record in records}
    if len(by_revision) != len(records):
        raise ManifestError("B04-MANIFEST-DUPLICATE-REVISION")
    roots = [record for record in records if record.down_revision is None]
    if len(roots) != 1 or roots[0].revision != HISTORICAL_ROOT:
        raise ManifestError("B04-MANIFEST-ROOT")
    if HISTORICAL_HEAD not in by_revision:
        raise ManifestError("B04-MANIFEST-HEAD")

    children: dict[str, list[RevisionRecord]] = {}
    for record in records:
        if record.down_revision is None:
            continue
        if record.down_revision not in by_revision:
            raise ManifestError("B04-MANIFEST-OUT-OF-BOUND-PARENT")
        children.setdefault(record.down_revision, []).append(record)
    if any(len(items) != 1 for items in children.values()):
        raise ManifestError("B04-MANIFEST-NON-LINEAR")

    ordered = [roots[0]]
    while ordered[-1].revision in children:
        ordered.append(children[ordered[-1].revision][0])
    if len(ordered) != len(records) or ordered[-1].revision != HISTORICAL_HEAD:
        raise ManifestError("B04-MANIFEST-DISCONNECTED-OR-HEAD")
    return ordered


def _source_path(filename: str) -> str:
    return (SOURCE_PREFIX / filename).as_posix()


def _archive_path(filename: str) -> str:
    return (ARCHIVE_PREFIX / filename).as_posix()


def build_frozen_manifest(versions_dir: Path) -> dict[str, object]:
    """Build a deterministic manifest for the accepted active historical chain."""
    records = _ordered_linear_records(
        [parse_revision(path) for path in sorted(versions_dir.glob("*.py"))]
    )
    return {
        "historical_head": HISTORICAL_HEAD,
        "historical_revision_count": HISTORICAL_REVISION_COUNT,
        "historical_root": HISTORICAL_ROOT,
        "revisions": [
            {
                "archive_path": _archive_path(record.filename),
                "byte_size": len(record.data),
                "down_revision": record.down_revision,
                "filename": record.filename,
                "revision": record.revision,
                "sha256": sha256_hex(record.data),
                "source_path": _source_path(record.filename),
            }
            for record in records
        ],
        "source_commit": SCHEMA_SOURCE_COMMIT,
    }


def _manifest_entries(manifest: Mapping[str, object]) -> list[Mapping[str, object]]:
    required = {
        "source_commit": SCHEMA_SOURCE_COMMIT,
        "historical_root": HISTORICAL_ROOT,
        "historical_head": HISTORICAL_HEAD,
        "historical_revision_count": HISTORICAL_REVISION_COUNT,
    }
    for field, expected in required.items():
        if manifest.get(field) != expected:
            raise ManifestError(f"B04-MANIFEST-CONTRACT-{field}")
    raw_entries = manifest.get("revisions")
    if not isinstance(raw_entries, list) or len(raw_entries) != HISTORICAL_REVISION_COUNT:
        raise ManifestError("B04-MANIFEST-ENTRIES")

    required_fields = {
        "revision",
        "down_revision",
        "filename",
        "source_path",
        "archive_path",
        "byte_size",
        "sha256",
    }
    entries: list[Mapping[str, object]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict) or set(entry) != required_fields:
            raise ManifestError("B04-MANIFEST-ENTRY-SHAPE")
        revision = entry["revision"]
        down_revision = entry["down_revision"]
        filename = entry["filename"]
        byte_size = entry["byte_size"]
        digest = entry["sha256"]
        if (
            not isinstance(revision, str)
            or not revision
            or (down_revision is not None and not isinstance(down_revision, str))
            or not isinstance(filename, str)
            or PurePosixPath(filename).name != filename
            or not filename.endswith(".py")
            or not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or byte_size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or entry["source_path"] != _source_path(filename)
            or entry["archive_path"] != _archive_path(filename)
        ):
            raise ManifestError("B04-MANIFEST-ENTRY-VALUES")
        entries.append(entry)

    records = [
        RevisionRecord(
            revision=entry["revision"],
            down_revision=entry["down_revision"],
            filename=entry["filename"],
            data=b"",
        )
        for entry in entries
    ]
    ordered = _ordered_linear_records(records)
    if [record.revision for record in ordered] != [entry["revision"] for entry in entries]:
        raise ManifestError("B04-MANIFEST-ORDER")
    return entries


def _resolve_under_root(root: Path, path: Path, *, directory: bool) -> Path:
    """Resolve an existing regular object, rejecting every symlink boundary."""
    if root.is_symlink():
        raise ManifestError("B04-MANIFEST-SYMLINK")
    root_lexical = root.absolute()
    if root_lexical.is_symlink():
        raise ManifestError("B04-MANIFEST-SYMLINK")
    try:
        root_resolved = root_lexical.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ManifestError("B04-MANIFEST-ROOT-MISSING") from exc

    path_lexical = path.absolute()
    try:
        relative = path_lexical.relative_to(root_lexical)
    except ValueError as exc:
        raise ManifestError("B04-MANIFEST-PATH-BOUNDARY") from exc
    current = root_lexical
    try:
        for component in relative.parts:
            current = current / component
            if current.is_symlink():
                raise ManifestError("B04-MANIFEST-SYMLINK")
            resolved = current.resolve(strict=True)
            try:
                resolved.relative_to(root_resolved)
            except ValueError as exc:
                raise ManifestError("B04-MANIFEST-PATH-BOUNDARY") from exc
    except FileNotFoundError as exc:
        raise ManifestError("B04-MANIFEST-PATH-MISSING") from exc

    if directory:
        if not resolved.is_dir():
            raise ManifestError("B04-MANIFEST-NONREGULAR-DIRECTORY")
    elif not resolved.is_file():
        raise ManifestError("B04-MANIFEST-NONREGULAR-FILE")
    return resolved


def _resolve_regular_file(root: Path, path: Path) -> Path:
    """Return a regular manifest file after physical containment checks."""
    return _resolve_under_root(root, path, directory=False)


def _resolve_regular_directory(root: Path, path: Path) -> Path:
    """Return a real manifest directory after physical containment checks."""
    return _resolve_under_root(root, path, directory=True)


def verify_manifest_files(
    manifest: Mapping[str, object], root: Path, *, archived: bool
) -> None:
    """Fail closed unless every expected historical file exactly matches the manifest."""
    entries = _manifest_entries(manifest)
    path_key = "archive_path" if archived else "source_path"
    paths = [entry[path_key] for entry in entries]
    if len(set(paths)) != len(paths):
        raise ManifestError("B04-MANIFEST-DUPLICATE-PATH")

    expected_paths = {str(path) for path in paths}
    expected_directory = ARCHIVE_PREFIX if archived else SOURCE_PREFIX
    actual_directory = root.joinpath(*expected_directory.parts)
    _resolve_regular_directory(root, actual_directory)
    actual_paths = {
        path.relative_to(root).as_posix() for path in actual_directory.glob("*.py")
    }
    if actual_paths != expected_paths:
        raise ManifestError("B04-MANIFEST-MISSING-OR-EXTRA")

    for entry in entries:
        relative_path = PurePosixPath(str(entry[path_key]))
        if relative_path.parent != expected_directory:
            raise ManifestError("B04-MANIFEST-PATH-BOUNDARY")
        path = _resolve_regular_file(root, root.joinpath(*relative_path.parts))
        data = path.read_bytes()
        if len(data) != entry["byte_size"] or sha256_hex(data) != entry["sha256"]:
            raise ManifestError("B04-MANIFEST-BYTE-DRIFT")
        parsed = parse_revision(path)
        if (
            parsed.revision != entry["revision"]
            or parsed.down_revision != entry["down_revision"]
            or parsed.filename != entry["filename"]
        ):
            raise ManifestError("B04-MANIFEST-REVISION-DRIFT")


def _cut_document() -> dict[str, object]:
    return {
        "historical_head": HISTORICAL_HEAD,
        "historical_revision_count": HISTORICAL_REVISION_COUNT,
        "historical_root": HISTORICAL_ROOT,
        "source_commit": SCHEMA_SOURCE_COMMIT,
    }


def _write_artifacts(manifest: Mapping[str, object], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_bytes = canonical_json_bytes(manifest)
    (output_dir / MANIFEST_FILENAME).write_bytes(manifest_bytes)
    (output_dir / DIGEST_FILENAME).write_text(
        f"{sha256_hex(manifest_bytes)}  {MANIFEST_FILENAME}\n", encoding="utf-8", newline=""
    )
    (output_dir / CUT_FILENAME).write_bytes(canonical_json_bytes(_cut_document()))


def verify_manifest_artifact(manifest_path: Path, root: Path) -> None:
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise ManifestError("B04-MANIFEST-JSON") from exc
    if canonical_json_bytes(manifest) != manifest_bytes:
        raise ManifestError("B04-MANIFEST-NONCANONICAL-JSON")
    digest_path = manifest_path.with_name(DIGEST_FILENAME)
    expected_digest = f"{sha256_hex(manifest_bytes)}  {MANIFEST_FILENAME}\n"
    if digest_path.read_bytes() != expected_digest.encode("ascii"):
        raise ManifestError("B04-MANIFEST-DIGEST")
    verify_manifest_files(manifest, root, archived=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions-dir", type=Path, default=Path("migrations/versions"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--verify-source", action="store_true")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    if args.verify_source:
        if args.manifest is None:
            parser.error("--verify-source requires --manifest")
        verify_manifest_artifact(args.manifest, args.versions_dir.parent.parent)
        return
    if args.output_dir is None:
        parser.error("--output-dir is required when generating a manifest")
    manifest = build_frozen_manifest(args.versions_dir)
    verify_manifest_files(manifest, args.versions_dir.parent.parent, archived=False)
    _write_artifacts(manifest, args.output_dir)


if __name__ == "__main__":
    main()
