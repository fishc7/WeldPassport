"""Create-exclusive, canonical TEST-DB-F2 evidence handling."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Mapping
from uuid import UUID

from app.testing.f2_contract import F2Error, F2_PROTOCOL_VERSION


_FORBIDDEN_KEYS = {
    "database",
    "database_name",
    "database_url",
    "dsn",
    "host",
    "ownership_token",
    "password",
    "test_database_url",
    "token",
    "url",
    "user",
    "username",
}
_UNSAFE_EVIDENCE = (
    "TEST-DB-F2-EVIDENCE-UNSAFE",
    "TEST-DB-F2 evidence path or payload is unsafe",
)
_FAILED_EVIDENCE = (
    "TEST-DB-F2-EVIDENCE-FAILED",
    "TEST-DB-F2 evidence could not be published or verified",
)


@dataclass(frozen=True)
class PublishedArtifact:
    name: str
    digest: str


def _reject_unsafe_value(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str) or key.casefold() in _FORBIDDEN_KEYS:
                raise F2Error(*_UNSAFE_EVIDENCE)
            _reject_unsafe_value(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _reject_unsafe_value(nested)
        return
    if isinstance(value, str):
        folded = value.casefold()
        if "://" in folded or "password=" in folded or "token=" in folded:
            raise F2Error(*_UNSAFE_EVIDENCE)


def canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    _reject_unsafe_value(payload)
    try:
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise F2Error(*_UNSAFE_EVIDENCE) from None
    return rendered.encode("utf-8") + b"\n"


def _assert_safe_existing_path(path: Path) -> None:
    absolute = path.absolute()
    existing: list[Path] = []
    current = absolute
    while True:
        if current.exists() or current.is_symlink():
            existing.append(current)
        if current.parent == current:
            break
        current = current.parent

    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    try:
        for component in existing:
            metadata = os.lstat(component)
            if stat.S_ISLNK(metadata.st_mode):
                raise F2Error(*_UNSAFE_EVIDENCE)
            attributes = getattr(metadata, "st_file_attributes", 0)
            if reparse_flag and attributes & reparse_flag:
                raise F2Error(*_UNSAFE_EVIDENCE)
    except OSError:
        raise F2Error(*_UNSAFE_EVIDENCE) from None


def reserve_run_namespace(root: Path, run_id: UUID) -> Path:
    if run_id.version != 4 or not root.exists() or not root.is_dir():
        raise F2Error(*_UNSAFE_EVIDENCE)
    _assert_safe_existing_path(root)
    namespace = root / str(run_id)
    try:
        namespace.mkdir(mode=0o700, exist_ok=False)
    except OSError:
        raise F2Error(*_UNSAFE_EVIDENCE) from None
    _assert_safe_existing_path(namespace)
    return namespace


def publish_artifact(
    path: Path,
    payload: Mapping[str, object],
) -> PublishedArtifact:
    content = canonical_json_bytes(payload)
    _assert_safe_existing_path(path.parent)
    try:
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise F2Error(*_FAILED_EVIDENCE) from None
    return PublishedArtifact(path.name, sha256(content).hexdigest())


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def verify_artifact(
    path: Path,
    expected_name: str,
    expected_run_id: UUID,
    expected_source_sha: str,
    expected_previous_digest: str | None,
) -> PublishedArtifact:
    if path.name != expected_name:
        raise F2Error(*_FAILED_EVIDENCE)
    _assert_safe_existing_path(path)
    try:
        metadata = os.lstat(path)
        if not stat.S_ISREG(metadata.st_mode):
            raise F2Error(*_FAILED_EVIDENCE)
        content = path.read_bytes()
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(payload, dict):
            raise ValueError
        if canonical_json_bytes(payload) != content:
            raise ValueError
        if (
            payload.get("protocol_version") != F2_PROTOCOL_VERSION
            or payload.get("run_id") != str(expected_run_id)
            or payload.get("source_sha") != expected_source_sha
            or payload.get("previous_digest") != expected_previous_digest
            or payload.get("status") != "verified"
        ):
            raise ValueError
    except F2Error:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        raise F2Error(*_FAILED_EVIDENCE) from None
    return PublishedArtifact(path.name, sha256(content).hexdigest())
