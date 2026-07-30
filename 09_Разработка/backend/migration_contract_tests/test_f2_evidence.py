import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.testing.f2_contract import F2Error, F2_PROTOCOL_VERSION
from app.testing.f2_evidence import (
    canonical_json_bytes,
    publish_artifact,
    reserve_run_namespace,
    verify_artifact,
)


SOURCE_SHA = "a" * 40


def _payload(run_id: UUID, previous_digest: str | None = None) -> dict[str, object]:
    return {
        "protocol_version": F2_PROTOCOL_VERSION,
        "run_id": str(run_id),
        "source_sha": SOURCE_SHA,
        "previous_digest": previous_digest,
        "role": "canonical",
        "status": "verified",
    }


def test_f2_evidence_001_canonical_json_is_sorted_compact_utf8_lf() -> None:
    assert canonical_json_bytes({"z": "ёж", "a": 1}) == (
        '{"a":1,"z":"ёж"}\n'.encode()
    )
    with pytest.raises(F2Error):
        canonical_json_bytes({"unsafe": float("nan")})


def test_f2_evidence_002_reserves_only_fresh_uuid4_namespace(
    tmp_path: Path,
) -> None:
    run_id = uuid4()
    namespace = reserve_run_namespace(tmp_path, run_id)

    assert namespace == tmp_path / str(run_id)
    assert namespace.is_dir()
    with pytest.raises(F2Error):
        reserve_run_namespace(tmp_path, run_id)
    with pytest.raises(F2Error):
        reserve_run_namespace(tmp_path / "missing", uuid4())
    with pytest.raises(F2Error):
        reserve_run_namespace(tmp_path, UUID(int=0))


def test_f2_evidence_003_publish_is_exclusive_and_stable(tmp_path: Path) -> None:
    path = tmp_path / "10_canonical.json"
    payload = {"z": 2, "a": 1}

    artifact = publish_artifact(path, payload)

    assert artifact.name == path.name
    assert len(artifact.digest) == 64
    assert path.read_bytes() == b'{"a":1,"z":2}\n'
    with pytest.raises(F2Error):
        publish_artifact(path, payload)


def test_f2_evidence_004_verifies_chain_and_detects_mutation(
    tmp_path: Path,
) -> None:
    run_id = uuid4()
    path = tmp_path / "10_canonical.json"
    published = publish_artifact(path, _payload(run_id))

    verified = verify_artifact(
        path,
        path.name,
        run_id,
        SOURCE_SHA,
        None,
    )
    assert verified == published

    path.write_bytes(path.read_bytes().replace(b'"verified"', b'"tampered"'))
    with pytest.raises(F2Error):
        verify_artifact(path, path.name, run_id, SOURCE_SHA, None)


@pytest.mark.parametrize(
    "payload",
    [
        {"password": "secret"},
        {"nested": [{"ownership_token": "secret"}]},
        {"safe": "postgresql+psycopg://user:secret@host/db"},
    ],
)
def test_f2_evidence_005_rejects_recursive_secret_shape(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    with pytest.raises(F2Error) as exc_info:
        publish_artifact(tmp_path / "unsafe.json", payload)

    assert exc_info.value.code == "TEST-DB-F2-EVIDENCE-UNSAFE"
    assert "secret" not in str(exc_info.value)


def test_f2_evidence_006_rejects_symlink_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(F2Error):
        reserve_run_namespace(link, uuid4())
