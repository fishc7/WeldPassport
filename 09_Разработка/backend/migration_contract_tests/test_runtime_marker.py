from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

from app.shared.runtime_marker import (
    read_canonical_marker,
    resolve_active_alembic_head,
    verify_canonical_marker,
)
from app.shared.runtime_profile import RuntimeContractError


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "shared" / "runtime_marker.py"
)
BACKEND_DIR = Path(__file__).resolve().parents[1]
FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COMMENT)\b",
    re.IGNORECASE,
)


def test_runtime_marker_001_resolves_single_active_head_independent_of_cwd(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_active_alembic_head() == "canonical_baseline_v1"


@pytest.mark.parametrize("heads", [(), ("head_a", "head_b")])
def test_runtime_marker_002_rejects_non_single_graph_head(
    monkeypatch,
    heads: tuple[str, ...],
) -> None:
    class _Script:
        def get_heads(self) -> tuple[str, ...]:
            return heads

    monkeypatch.setattr(
        "app.shared.runtime_marker.ScriptDirectory.from_config",
        lambda _config: _Script(),
    )

    with pytest.raises(RuntimeContractError) as exc_info:
        resolve_active_alembic_head(BACKEND_DIR / "alembic.ini")

    assert exc_info.value.code == "CANONICAL-MARKER-MISMATCH"
    assert (
        exc_info.value.safe_detail
        == "active Alembic graph does not have exactly one head"
    )


class _ScalarResult:
    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = values

    def scalar_one(self):
        assert len(self._values) == 1
        return self._values[0]

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class _MarkerConnection:
    def __init__(
        self,
        marker_relation: object,
        versions: tuple[object, ...] = (),
    ) -> None:
        self._responses = [
            _ScalarResult((marker_relation,)),
            _ScalarResult(versions),
        ]
        self.calls = 0

    def execute(self, *_args, **_kwargs):
        response = self._responses[self.calls]
        self.calls += 1
        return response


def test_runtime_marker_003_missing_public_marker_fails_closed() -> None:
    connection = _MarkerConnection(None)

    with pytest.raises(RuntimeContractError) as exc_info:
        read_canonical_marker(connection)

    assert exc_info.value.code == "CANONICAL-MARKER-MISMATCH"
    assert exc_info.value.safe_detail == "public Alembic marker is missing"
    assert connection.calls == 1


@pytest.mark.parametrize(
    "versions",
    [(), ("canonical_baseline_v1", "second_head"), ("wrong_head",)],
)
def test_runtime_marker_004_nonmatching_marker_rows_fail(
    versions: tuple[str, ...],
) -> None:
    connection = _MarkerConnection("public.alembic_version", versions)

    with pytest.raises(RuntimeContractError) as exc_info:
        verify_canonical_marker(connection, "canonical_baseline_v1")

    assert exc_info.value.code == "CANONICAL-MARKER-MISMATCH"
    assert exc_info.value.safe_detail == "public Alembic marker does not match"


def test_runtime_marker_005_exact_marker_succeeds() -> None:
    connection = _MarkerConnection(
        "public.alembic_version",
        ("canonical_baseline_v1",),
    )

    assert read_canonical_marker(connection) == ("canonical_baseline_v1",)
    verify_canonical_marker(
        _MarkerConnection(
            "public.alembic_version",
            ("canonical_baseline_v1",),
        ),
        "canonical_baseline_v1",
    )


class _BrokenConnection:
    def execute(self, *_args, **_kwargs):
        raise RuntimeError("password=must-not-leak secret-host.example")


def test_runtime_marker_006_raw_sql_error_is_redacted() -> None:
    with pytest.raises(RuntimeContractError) as exc_info:
        read_canonical_marker(_BrokenConnection())

    assert exc_info.value.code == "CANONICAL-MARKER-MISMATCH"
    assert exc_info.value.safe_detail == "canonical marker read failed"
    assert "must-not-leak" not in str(exc_info.value)
    assert "secret-host" not in str(exc_info.value)


def test_runtime_marker_007_raw_alembic_error_is_redacted(
    monkeypatch,
) -> None:
    def _raise(_config):
        raise RuntimeError("C:/secret/path/password=must-not-leak")

    monkeypatch.setattr(
        "app.shared.runtime_marker.ScriptDirectory.from_config",
        _raise,
    )

    with pytest.raises(RuntimeContractError) as exc_info:
        resolve_active_alembic_head(BACKEND_DIR / "alembic.ini")

    assert exc_info.value.code == "CANONICAL-MARKER-MISMATCH"
    assert exc_info.value.safe_detail == "active Alembic graph could not be read"
    assert "must-not-leak" not in str(exc_info.value)


def test_runtime_marker_008_all_sql_is_read_only() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    sql_literals = [
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "text"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ]

    assert len(sql_literals) == 2
    for sql in sql_literals:
        assert sql.lstrip().split(maxsplit=1)[0].upper() == "SELECT"
        assert FORBIDDEN_SQL.search(sql) is None
