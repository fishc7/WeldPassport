from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.testing.f2_contract import F2Error, F2Role
from app.testing.f2_operator_preflight import (
    F2OperatorPreflightStatus,
    OperatorSourceState,
    SubprocessOperatorSourceInspector,
    load_operator_preflight_inputs,
    resolve_repository_boundary,
    validate_operator_source,
)


SOURCE_SHA = "a" * 40
PREREQUISITES = ("20c7ea7", "03d4c59", "32ffec8")


def _environment(root: Path) -> dict[str, str]:
    environment = {
        "WELDPASSPORT_F2_WORKING_DATABASE_URL": (
            "postgresql+psycopg://worker:working-secret@localhost/weldpassport_dev"
        ),
        "WELDPASSPORT_F2_EVIDENCE_DIR": str(root),
        "WELDPASSPORT_F2_PREFLIGHT_AUTHORIZATION": (
            "I_AUTHORIZE_TEST_DB_F2_OPERATOR_PREFLIGHT"
        ),
        "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS": "YES",
    }
    for role in F2Role:
        prefix = role.value.upper()
        environment[f"WELDPASSPORT_F2_{prefix}_TEST_DATABASE_URL"] = (
            "postgresql+psycopg://worker:target-secret@localhost/"
            f"test_{role.value}"
        )
        environment[f"WELDPASSPORT_F2_{prefix}_DATABASE_CONFIRM"] = (
            f"test_{role.value}"
        )
        environment[f"WELDPASSPORT_F2_{prefix}_OWNERSHIP_TOKEN"] = (
            f"token-{role.value}"
        )
    return environment


def _source_state(**changes: object) -> OperatorSourceState:
    values: dict[str, object] = {
        "source_sha": SOURCE_SHA,
        "branch": "codex/b04b-maintenance-readiness-review",
        "tracked_clean": True,
        "prerequisites": tuple((sha, True) for sha in PREREQUISITES),
    }
    values.update(changes)
    return OperatorSourceState(**values)  # type: ignore[arg-type]


def test_f2_operator_contract_001_loads_preflight_authorization_without_leaks(
    tmp_path: Path,
) -> None:
    inputs = load_operator_preflight_inputs(_environment(tmp_path))

    assert tuple(target.role for target in inputs.targets) == tuple(F2Role)
    rendered = repr(inputs)
    for secret in ("working-secret", "target-secret", "token-"):
        assert secret not in rendered


@pytest.mark.parametrize(
    "mutation",
    [
        {"WELDPASSPORT_F2_PREFLIGHT_AUTHORIZATION": "wrong"},
        {
            "WELDPASSPORT_F2_OPERATOR_AUTHORIZATION":
                "I_AUTHORIZE_TEST_DB_F2_LOCAL_REHEARSAL"
        },
        {"WELDPASSPORT_F2_UNKNOWN": "must-not-leak"},
    ],
)
def test_f2_operator_contract_002_rejects_wrong_or_rehearsal_authorization(
    tmp_path: Path,
    mutation: dict[str, str],
) -> None:
    environment = _environment(tmp_path)
    environment.update(mutation)

    with pytest.raises(F2Error) as exc_info:
        load_operator_preflight_inputs(environment)

    assert exc_info.value.code == "TEST-DB-F2-AUTHORIZATION-MISSING"
    assert "must-not-leak" not in str(exc_info.value)


@pytest.mark.parametrize(
    "state,version",
    [
        (_source_state(branch="main"), (3, 14, 0)),
        (_source_state(tracked_clean=False), (3, 14, 0)),
        (_source_state(source_sha="not-a-sha"), (3, 14, 0)),
        (
            _source_state(
                prerequisites=(
                    ("20c7ea7", True),
                    ("03d4c59", False),
                    ("32ffec8", True),
                )
            ),
            (3, 14, 0),
        ),
        (_source_state(), (3, 11, 9)),
    ],
)
def test_f2_operator_contract_003_rejects_unsafe_source_or_python(
    state: OperatorSourceState,
    version: tuple[int, int, int],
) -> None:
    with pytest.raises(F2Error) as exc_info:
        validate_operator_source(state, PREREQUISITES, version)

    assert exc_info.value.code == "TEST-DB-F2-SOURCE-UNSAFE"


def test_f2_operator_contract_004_accepts_source_and_is_immutable() -> None:
    state = _source_state()

    validate_operator_source(state, PREREQUISITES, (3, 12, 0))

    with pytest.raises(FrozenInstanceError):
        state.branch = "changed"  # type: ignore[misc]
    assert (
        F2OperatorPreflightStatus.READY
        == "TEST_DB_F2_OPERATOR_PREFLIGHT_READY"
    )


def test_f2_operator_contract_005_git_inspector_uses_exact_safe_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    class Completed:
        def __init__(self, returncode: int, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> Completed:
        calls.append((argv, kwargs))
        if argv[1:3] == ("rev-parse", "HEAD"):
            return Completed(0, SOURCE_SHA + "\n")
        if argv[1] == "status":
            return Completed(0, "")
        if argv[1:3] == ("branch", "--show-current"):
            return Completed(0, "codex/b04b-maintenance-readiness-review\n")
        return Completed(0)

    monkeypatch.setattr(
        "app.testing.f2_operator_preflight.subprocess.run",
        fake_run,
    )
    inspector = SubprocessOperatorSourceInspector(
        tmp_path,
        {
            "PATH": "C:\\Git",
            "SECRET_SENTINEL": "must-not-pass",
        },
    )

    state = inspector.read_state(PREREQUISITES)

    assert state == _source_state()
    assert [call[0] for call in calls] == [
        ("git", "rev-parse", "HEAD"),
        ("git", "status", "--porcelain", "--untracked-files=no"),
        ("git", "branch", "--show-current"),
        *[
            ("git", "merge-base", "--is-ancestor", sha, "HEAD")
            for sha in PREREQUISITES
        ],
    ]
    assert all(call[1]["shell"] is False for call in calls)
    assert all("SECRET_SENTINEL" not in call[1]["env"] for call in calls)


def test_f2_operator_contract_006_resolves_common_repository_from_gitfile(
    tmp_path: Path,
) -> None:
    common_root = tmp_path / "repository"
    common_git = common_root / ".git"
    worktree_root = common_root / ".worktrees" / "feature"
    worktree_git = common_git / "worktrees" / "feature"
    worktree_git.mkdir(parents=True)
    worktree_root.mkdir(parents=True)
    (worktree_root / ".git").write_text(
        f"gitdir: {worktree_git}\n",
        encoding="utf-8",
    )

    assert resolve_repository_boundary(worktree_root) == common_root.resolve()
