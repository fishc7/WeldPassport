from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from app.testing.f2_contract import (
    F2Error,
    F2ParentInputs,
    F2Role,
    F2TargetInput,
)
from app.testing.f2_preflight import (
    GitState,
    authorize_offline_targets,
    build_offline_plan,
)


RUN_ID = UUID("12345678-1234-4234-8234-123456789abc")
SOURCE_SHA = "b" * 40


class FakeGitInspector:
    def __init__(self, state: GitState) -> None:
        self.state = state
        self.calls = 0

    def read_state(self) -> GitState:
        self.calls += 1
        return self.state


def _inputs(root: Path) -> F2ParentInputs:
    return F2ParentInputs(
        working_database_url=(
            "postgresql+psycopg://worker:secret@localhost/weldpassport_dev"
        ),
        evidence_root=root,
        authorization="I_AUTHORIZE_TEST_DB_F2_LOCAL_REHEARSAL",
        destructive_opt_in="YES",
        targets=tuple(
            F2TargetInput(
                role=role,
                test_database_url=(
                    "postgresql+psycopg://worker:secret@localhost/"
                    f"test_{role.value}"
                ),
                confirmed_name=f"test_{role.value}",
                ownership_token=f"token-{role.value}",
            )
            for role in F2Role
        ),
    )


def test_f2_preflight_001_builds_complete_offline_plan(tmp_path: Path) -> None:
    inspector = FakeGitInspector(GitState(SOURCE_SHA, True))

    plan = build_offline_plan(_inputs(tmp_path), inspector, lambda: RUN_ID)

    assert plan.run_id == RUN_ID
    assert plan.source_sha == SOURCE_SHA
    assert plan.namespace == tmp_path / str(RUN_ID)
    assert [target.role for target in plan.targets] == list(F2Role)
    assert all(len(target.identity_digest) == 64 for target in plan.targets)
    assert inspector.calls == 1


def test_f2_preflight_006_authorizes_targets_without_reserving_namespace(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)

    targets = authorize_offline_targets(inputs)

    assert tuple(target.role for target in targets) == tuple(F2Role)
    assert len({target.identity_digest for target in targets}) == 3
    assert not (tmp_path / str(RUN_ID)).exists()


@pytest.mark.parametrize(
    "state",
    [
        GitState(SOURCE_SHA, False),
        GitState("not-a-sha", True),
        GitState("A" * 40, True),
    ],
)
def test_f2_preflight_002_rejects_unsafe_source(
    tmp_path: Path,
    state: GitState,
) -> None:
    with pytest.raises(F2Error) as exc_info:
        build_offline_plan(
            _inputs(tmp_path),
            FakeGitInspector(state),
            lambda: RUN_ID,
        )

    assert exc_info.value.code == "TEST-DB-F2-SOURCE-UNSAFE"
    assert not (tmp_path / str(RUN_ID)).exists()


def test_f2_preflight_003_rejects_missing_or_duplicate_roles(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    malformed = replace(inputs, targets=(inputs.targets[0],) * 3)

    with pytest.raises(F2Error) as exc_info:
        build_offline_plan(
            malformed,
            FakeGitInspector(GitState(SOURCE_SHA, True)),
            lambda: RUN_ID,
        )

    assert exc_info.value.code == "TEST-DB-F2-AUTHORIZATION-MISSING"


@pytest.mark.parametrize("second_index", [1, 2])
def test_f2_preflight_004_rejects_pairwise_target_collision(
    tmp_path: Path,
    second_index: int,
) -> None:
    inputs = _inputs(tmp_path)
    targets = list(inputs.targets)
    first = targets[0]
    targets[second_index] = replace(
        targets[second_index],
        test_database_url=first.test_database_url,
        confirmed_name=first.confirmed_name,
    )

    with pytest.raises(F2Error) as exc_info:
        build_offline_plan(
            replace(inputs, targets=tuple(targets)),
            FakeGitInspector(GitState(SOURCE_SHA, True)),
            lambda: RUN_ID,
        )

    assert exc_info.value.code == "TEST-DB-F2-TARGET-COLLISION"
    assert not (tmp_path / str(RUN_ID)).exists()


def test_f2_preflight_005_rejects_namespace_collision(tmp_path: Path) -> None:
    (tmp_path / str(RUN_ID)).mkdir()

    with pytest.raises(F2Error) as exc_info:
        build_offline_plan(
            _inputs(tmp_path),
            FakeGitInspector(GitState(SOURCE_SHA, True)),
            lambda: RUN_ID,
        )

    assert exc_info.value.code == "TEST-DB-F2-EVIDENCE-UNSAFE"
