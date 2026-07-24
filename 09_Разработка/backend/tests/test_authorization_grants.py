"""Isolated contracts for evidence-bearing Joint authorization grants (ADR-028)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.hr.models import WorkerRole
from app.shared import permissions


CHECK_DATE = date(2026, 7, 24)
PROJECT_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
LINE_ID = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")
DOCUMENT_ID = UUID("7a1f5ad8-5290-4f74-9164-338af267b3f8")


def _role(
    role_id: int,
    role_code: str,
    scope_type: str,
    scope_id: str | None = None,
    *,
    active: bool = True,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> WorkerRole:
    return WorkerRole(
        id=role_id,
        worker_id=42,
        role_code=role_code,
        scope_type=scope_type,
        scope_id=scope_id,
        is_active=active,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _install_roles(monkeypatch, roles: list[WorkerRole]) -> None:
    class FakeHrRepo:
        def __init__(self, db: object) -> None:
            self.db = db

        def find_active_roles(
            self,
            *,
            worker_id: int,
            role_code: str,
        ) -> list[WorkerRole]:
            return [
                role
                for role in roles
                if role.worker_id == worker_id and role.role_code == role_code
            ]

    monkeypatch.setattr(permissions, "HrRepo", FakeHrRepo)


def _context(*, company_ids: frozenset[int] = frozenset()):
    return permissions.JointScopeContext(
        project_id=PROJECT_ID,
        line_id=LINE_ID,
        engineering_document_id=DOCUMENT_ID,
        company_ids=company_ids,
    )


def test_resolver_returns_stable_assignment_evidence(monkeypatch) -> None:
    _install_roles(
        monkeypatch,
        [
            _role(
                11,
                "OGS_ENGINEER",
                "PROJECT",
                str(PROJECT_ID),
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 12, 31),
            )
        ],
    )

    grants = permissions.worker_authorization_grants_for_joint(
        object(),
        42,
        {"OGS_ENGINEER"},
        _context(),
        on_date=CHECK_DATE,
    )

    assert grants == (
        permissions.AuthorizationGrant(
            actor_worker_id=42,
            actor_role_code="OGS_ENGINEER",
            worker_role_assignment_id=11,
            scope_type="PROJECT",
            scope_id=str(PROJECT_ID),
            role_valid_from=date(2026, 1, 1),
            role_valid_to=date(2026, 12, 31),
        ),
    )


def test_resolver_filters_ineffective_and_non_covering_assignments(
    monkeypatch,
) -> None:
    _install_roles(
        monkeypatch,
        [
            _role(1, "OGS_ENGINEER", "GLOBAL"),
            _role(2, "OGS_ENGINEER", "SITE", "site-1"),
            _role(3, "OGS_ENGINEER", "PROJECT", str(UUID(int=99))),
            _role(4, "OGS_ENGINEER", "PROJECT", str(PROJECT_ID), active=False),
            _role(
                5,
                "OGS_ENGINEER",
                "PROJECT",
                str(PROJECT_ID),
                valid_to=date(2026, 7, 23),
            ),
            _role(
                6,
                "OGS_ENGINEER",
                "PROJECT",
                str(PROJECT_ID),
                valid_from=date(2026, 7, 25),
            ),
        ],
    )

    grants = permissions.worker_authorization_grants_for_joint(
        object(),
        42,
        {"OGS_ENGINEER"},
        _context(),
        on_date=CHECK_DATE,
    )

    assert [grant.worker_role_assignment_id for grant in grants] == [1]


def test_selector_prefers_narrowest_scope_then_smallest_assignment_id(
    monkeypatch,
) -> None:
    _install_roles(
        monkeypatch,
        [
            _role(40, "OTK_INSPECTOR", "GLOBAL"),
            _role(30, "OTK_INSPECTOR", "PROJECT", str(PROJECT_ID)),
            _role(20, "OTK_INSPECTOR", "LINE", str(LINE_ID)),
            _role(
                12,
                "OTK_INSPECTOR",
                "ENGINEERING_DOCUMENT",
                str(DOCUMENT_ID),
            ),
            _role(
                11,
                "OTK_INSPECTOR",
                "ENGINEERING_DOCUMENT",
                str(DOCUMENT_ID),
            ),
        ],
    )
    grants = permissions.worker_authorization_grants_for_joint(
        object(),
        42,
        {"OTK_INSPECTOR"},
        _context(),
        on_date=CHECK_DATE,
    )

    selected = permissions.select_preferred_authorization_grant(
        grants,
        "OTK_INSPECTOR",
    )

    assert selected is not None
    assert selected.scope_type == "ENGINEERING_DOCUMENT"
    assert selected.worker_role_assignment_id == 11


def test_dual_roles_and_legacy_code_wrapper_remain_compatible(monkeypatch) -> None:
    _install_roles(
        monkeypatch,
        [
            _role(1, "OGS_ENGINEER", "GLOBAL"),
            _role(2, "OTK_INSPECTOR", "PROJECT", str(PROJECT_ID)),
            _role(3, "OTK_INSPECTOR", "COMPANY", "77"),
        ],
    )
    ctx = _context(company_ids=frozenset({77}))

    grants = permissions.worker_authorization_grants_for_joint(
        object(),
        42,
        {"OGS_ENGINEER", "OTK_INSPECTOR"},
        ctx,
        on_date=CHECK_DATE,
    )
    codes = permissions.worker_role_codes_for_joint(
        object(),
        42,
        {"OGS_ENGINEER", "OTK_INSPECTOR"},
        ctx,
        on_date=CHECK_DATE,
    )

    assert {
        (grant.actor_role_code, grant.worker_role_assignment_id)
        for grant in grants
    } == {
        ("OGS_ENGINEER", 1),
        ("OTK_INSPECTOR", 2),
        ("OTK_INSPECTOR", 3),
    }
    assert codes == {"OGS_ENGINEER", "OTK_INSPECTOR"}

