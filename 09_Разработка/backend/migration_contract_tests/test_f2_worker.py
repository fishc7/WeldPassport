from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.shared.database_target import authorize_test_database
from app.testing.f2_contract import (
    F2Error,
    F2_PROTOCOL_VERSION,
    F2Role,
    F2WorkerRequest,
)
from app.testing.f2_evidence import publish_artifact
from app.testing.f2_worker import (
    WorkerDependencies,
    _BoundCommandExecutor,
    run_worker,
)


RUN_ID = UUID("12345678-1234-4234-8234-123456789abc")
SOURCE_SHA = "a" * 40


def _request(role: F2Role = F2Role.CANONICAL) -> F2WorkerRequest:
    names = {
        F2Role.CANONICAL: "10_canonical.json",
        F2Role.LEGACY_COMPATIBLE: "20_legacy_compatible.json",
        F2Role.LEGACY_NEGATIVE: "30_legacy_negative.json",
    }
    return F2WorkerRequest(
        F2_PROTOCOL_VERSION,
        str(RUN_ID),
        SOURCE_SHA,
        role,
        names[role],
    )


def _environment(tmp_path: Path, role: F2Role) -> dict[str, str]:
    result = {
        "WELDPASSPORT_F2_PROTOCOL_VERSION": F2_PROTOCOL_VERSION,
        "WELDPASSPORT_F2_RUN_ID": str(RUN_ID),
        "WELDPASSPORT_F2_SOURCE_SHA": SOURCE_SHA,
        "WELDPASSPORT_F2_ROLE": role.value,
        "WELDPASSPORT_F2_ARTIFACT_PATH": str(
            tmp_path / _request(role).artifact_name
        ),
        "WELDPASSPORT_F2_IDENTITY_DIGEST": "d" * 64,
        "WELDPASSPORT_F2_PREVIOUS_DIGEST": "e" * 64,
        "WELDPASSPORT_F2_WORKING_DATABASE_URL": (
            "postgresql+psycopg://worker:secret@localhost/weldpassport_dev"
        ),
        "TEST_DATABASE_URL": (
            "postgresql+psycopg://worker:secret@localhost/"
            f"test_{role.value}"
        ),
        "WELDPASSPORT_TEST_DB_CONFIRM": f"test_{role.value}",
        "WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN": f"token-{role.value}",
        "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS": "YES",
    }
    if role is not F2Role.CANONICAL:
        result["WELDPASSPORT_RUNTIME_PROFILE"] = "legacy_compatibility"
        result["WELDPASSPORT_LEGACY_SCHEMA"] = "test"
    return result


class FakeAdapter:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def run(self, role: F2Role) -> dict[str, object]:
        self.events.append(f"adapter:{role.value}")
        return {"role_gate": "verified"}


def _dependencies(events: list[str], version: int = 180003) -> WorkerDependencies:
    def authorize(**kwargs: object) -> object:
        events.append("authorize")
        return authorize_test_database(**kwargs)  # type: ignore[arg-type]

    def bind(target: object) -> object:
        events.append("bind")
        return target

    @contextmanager
    def live_gate(authorization: object):
        events.append("live")
        try:
            yield object()
        finally:
            events.append("close")

    def version_gate(connection: object) -> int:
        events.append("version")
        return version

    def empty_gate(connection: object) -> None:
        events.append("empty")

    def publisher(path: Path, payload: dict[str, object]):
        events.append("publish")
        return publish_artifact(path, payload)

    return WorkerDependencies(
        authorize=authorize,
        bind=bind,
        live_gate=live_gate,
        version_gate=version_gate,
        empty_gate=empty_gate,
        role_adapter=FakeAdapter(events),
        publisher=publisher,
    )


@pytest.mark.parametrize("role", list(F2Role))
def test_f2_worker_001_binds_once_before_live_work_and_publishes_after_close(
    tmp_path: Path,
    role: F2Role,
) -> None:
    events: list[str] = []

    artifact = run_worker(
        _request(role),
        _environment(tmp_path, role),
        _dependencies(events),
    )

    assert artifact.name == _request(role).artifact_name
    assert events == [
        "authorize",
        "bind",
        "live",
        "version",
        "empty",
        f"adapter:{role.value}",
        "close",
        "publish",
    ]


def test_f2_worker_002_version_mismatch_fails_before_adapter(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    with pytest.raises(F2Error) as exc_info:
        run_worker(
            _request(),
            _environment(tmp_path, F2Role.CANONICAL),
            _dependencies(events, version=180004),
        )

    assert exc_info.value.code == "TEST-DB-F2-VERSION-MISMATCH"
    assert "adapter:canonical" not in events
    assert events[-1] == "close"
    assert not (tmp_path / "10_canonical.json").exists()


@pytest.mark.parametrize(
    "name,value",
    [
        ("WELDPASSPORT_F2_PROTOCOL_VERSION", "wrong"),
        ("WELDPASSPORT_F2_SOURCE_SHA", "b" * 40),
        ("WELDPASSPORT_F2_ROLE", "legacy_compatible"),
    ],
)
def test_f2_worker_003_rejects_protocol_mismatch_before_authorization(
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    environment = _environment(tmp_path, F2Role.CANONICAL)
    environment[name] = value
    events: list[str] = []

    with pytest.raises(F2Error) as exc_info:
        run_worker(_request(), environment, _dependencies(events))

    assert exc_info.value.code == "TEST-DB-F2-WORKER-PROTOCOL"
    assert events == []


def test_f2_worker_004_existing_output_fails_before_authorization(
    tmp_path: Path,
) -> None:
    output = tmp_path / "10_canonical.json"
    output.write_text("existing", encoding="utf-8")
    events: list[str] = []

    with pytest.raises(F2Error):
        run_worker(
            _request(),
            _environment(tmp_path, F2Role.CANONICAL),
            _dependencies(events),
        )

    assert events == []


def test_f2_worker_005_rejects_adapter_secret_before_publication(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class LeakingAdapter:
        def run(self, role: F2Role) -> dict[str, object]:
            events.append("adapter")
            return {"opaque_value": "token-canonical"}

    dependencies = replace(
        _dependencies(events),
        role_adapter=LeakingAdapter(),
    )

    with pytest.raises(F2Error) as exc_info:
        run_worker(
            _request(),
            _environment(tmp_path, F2Role.CANONICAL),
            dependencies,
        )

    assert exc_info.value.code == "TEST-DB-F2-EVIDENCE-UNSAFE"
    assert "publish" not in events
    assert events[-1] == "close"


def test_f2_worker_006_application_suite_runs_from_backend_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> object:
        observed["argv"] = argv
        observed["cwd"] = kwargs.get("cwd")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("app.testing.f2_worker.subprocess.run", fake_run)

    exit_code = _BoundCommandExecutor().run(
        (sys.executable, "-m", "pytest", "tests", "-q")
    )

    backend_root = Path(__file__).resolve().parents[1]
    assert exit_code == 0
    assert observed["cwd"] == backend_root
    assert observed["argv"] == (
        sys.executable,
        "-m",
        "pytest",
        str(backend_root / "tests"),
        "-q",
    )
