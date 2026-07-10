from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.hr.models import WorkerRole
from app.hr.repository import HrRepo

ScopeType = Literal["GLOBAL", "PROJECT", "LINE"]


@dataclass(frozen=True)
class RoleRequirement:
    role_code: str
    scope_type: ScopeType
    scope_id: str | None = None


def current_check_date() -> date:
    return date.today()


def normalize_uuid(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return str(UUID(text))


def is_role_effective_on(role: WorkerRole, on_date: date) -> bool:
    if not role.is_active:
        return False
    if role.valid_from is not None and role.valid_from > on_date:
        return False
    if role.valid_to is not None and role.valid_to < on_date:
        return False
    return True


def role_scope_matches(role: WorkerRole, requirement: RoleRequirement) -> bool:
    if requirement.scope_type == "GLOBAL":
        return role.scope_type == "GLOBAL" and (
            role.scope_id is None or str(role.scope_id).strip() == ""
        )
    if requirement.scope_type in ("PROJECT", "LINE"):
        if role.scope_type != requirement.scope_type:
            return False
        try:
            required_id = normalize_uuid(requirement.scope_id)
            role_id = normalize_uuid(role.scope_id)
        except (ValueError, AttributeError, TypeError):
            return False
        if required_id is None or role_id is None:
            return False
        return required_id == role_id
    return False


def role_matches_requirement(
    role: WorkerRole,
    requirement: RoleRequirement,
    *,
    on_date: date,
) -> bool:
    if role.role_code != requirement.role_code:
        return False
    if not is_role_effective_on(role, on_date):
        return False
    return role_scope_matches(role, requirement)


def check_worker_role(
    db: Session,
    worker_id: int,
    requirement: RoleRequirement,
    *,
    on_date: date | None = None,
) -> bool:
    effective_date = on_date if on_date is not None else current_check_date()
    roles = HrRepo(db).find_active_roles(
        worker_id=worker_id,
        role_code=requirement.role_code,
    )
    return any(
        role_matches_requirement(role, requirement, on_date=effective_date)
        for role in roles
    )


def require_worker_role(
    db: Session,
    worker_id: int,
    requirement: RoleRequirement,
    *,
    on_date: date | None = None,
) -> None:
    if not check_worker_role(db, worker_id, requirement, on_date=on_date):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Недостаточно прав: требуется роль {requirement.role_code} "
                f"в scope {requirement.scope_type}"
            ),
        )
