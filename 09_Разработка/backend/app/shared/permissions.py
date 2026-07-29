from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.hr.models import WorkerRole
from app.hr.repository import HrRepo

# Канонический набор scope_type (Р-1 / Р-11-4). SITE/COMPANY сохранены; в Task 5B
# добавлен ENGINEERING_DOCUMENT (ISOMETRIC → ENGINEERING_DOCUMENT). Литералы
# UNIT/ISOMETRIC не вводятся (UNIT → SITE, ISOMETRIC → ENGINEERING_DOCUMENT).
ScopeType = Literal[
    "GLOBAL", "COMPANY", "PROJECT", "SITE", "LINE", "ENGINEERING_DOCUMENT"
]


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
    if requirement.scope_type in ("PROJECT", "LINE", "ENGINEERING_DOCUMENT"):
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


# ── Иерархический scope для Joint (Task 5B, §19 ADR-011 / §5 задания) ──────────
#
# Иерархия: GLOBAL → PROJECT → SITE → LINE → ENGINEERING_DOCUMENT. Широкий scope
# покрывает вложенные уровни; узкий не покрывает соседние ветви. Проверка ведётся
# по фактическим связям (project_id / line_id / engineering_document_id Joint), а
# не только по равенству scope_id. COMPANY — сквозной организационный фильтр:
# роль покрывает Joint, если организация участвует в проекте Joint.
#
# SITE как уровень дерева пока не имеет физической сущности (в модели есть только
# Project и Line): SITE-scoped роль не резолвится против Joint и не даёт доступа.
# Это осознанная граница (§5 задания: не создавать фиктивную сущность).


@dataclass(frozen=True)
class JointScopeContext:
    """Контекст Joint для иерархической проверки scope.

    `company_ids` — организации, действующие в проекте Joint (project_companies с
    valid_to IS NULL); используется только для COMPANY-scope.
    """

    project_id: UUID
    line_id: UUID | None
    engineering_document_id: UUID | None
    company_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class AuthorizationGrant:
    """Доказуемое effective-назначение роли, покрывающее конкретный Joint."""

    actor_worker_id: int
    actor_role_code: str
    worker_role_assignment_id: int
    scope_type: str
    scope_id: str | None
    role_valid_from: date | None
    role_valid_to: date | None


_JOINT_SCOPE_PRIORITY: dict[str, int] = {
    "ENGINEERING_DOCUMENT": 0,
    "LINE": 1,
    "PROJECT": 2,
    "GLOBAL": 3,
}


def _uuid_equal(role_scope_id: str | None, target: UUID | None) -> bool:
    if role_scope_id is None or target is None:
        return False
    try:
        return normalize_uuid(role_scope_id) == str(target)
    except (ValueError, AttributeError, TypeError):
        return False


def role_covers_joint(role: WorkerRole, ctx: JointScopeContext) -> bool:
    """Покрывает ли активная роль Joint по иерархии scope (без проверки даты)."""
    scope = role.scope_type
    if scope == "GLOBAL":
        return role.scope_id is None or str(role.scope_id).strip() == ""
    if scope == "PROJECT":
        return _uuid_equal(role.scope_id, ctx.project_id)
    if scope == "LINE":
        return _uuid_equal(role.scope_id, ctx.line_id)
    if scope == "ENGINEERING_DOCUMENT":
        return _uuid_equal(role.scope_id, ctx.engineering_document_id)
    if scope == "COMPANY":
        if role.scope_id is None:
            return False
        try:
            return int(str(role.scope_id).strip()) in ctx.company_ids
        except (ValueError, TypeError):
            return False
    # SITE и прочие уровни без физической связи не резолвятся против Joint.
    return False


def worker_authorization_grants_for_joint(
    db: Session,
    worker_id: int,
    role_codes: Iterable[str],
    ctx: JointScopeContext,
    *,
    on_date: date | None = None,
) -> tuple[AuthorizationGrant, ...]:
    """Возвращает все effective role assignments, покрывающие Joint.

    В отличие от совместимой code-only оболочки сохраняет assignment/scope/validity,
    необходимые для immutable authorization evidence.
    """
    effective_date = on_date if on_date is not None else current_check_date()
    repo = HrRepo(db)
    grants: list[AuthorizationGrant] = []
    for code in sorted(set(role_codes)):
        roles = repo.find_active_roles(worker_id=worker_id, role_code=code)
        for role in roles:
            if not is_role_effective_on(role, effective_date):
                continue
            if not role_covers_joint(role, ctx):
                continue
            grants.append(
                AuthorizationGrant(
                    actor_worker_id=worker_id,
                    actor_role_code=role.role_code,
                    worker_role_assignment_id=role.id,
                    scope_type=role.scope_type,
                    scope_id=role.scope_id,
                    role_valid_from=role.valid_from,
                    role_valid_to=role.valid_to,
                )
            )
    return tuple(
        sorted(
            grants,
            key=lambda grant: (
                grant.actor_role_code,
                _JOINT_SCOPE_PRIORITY.get(grant.scope_type, 99),
                grant.worker_role_assignment_id,
            ),
        )
    )


def select_preferred_authorization_grant(
    grants: Iterable[AuthorizationGrant],
    role_code: str,
) -> AuthorizationGrant | None:
    """Детерминированно выбирает наиболее узкое назначение указанной роли."""
    matching = (
        grant for grant in grants if grant.actor_role_code == role_code
    )
    return min(
        matching,
        key=lambda grant: (
            _JOINT_SCOPE_PRIORITY.get(grant.scope_type, 99),
            grant.worker_role_assignment_id,
        ),
        default=None,
    )


def worker_role_codes_for_joint(
    db: Session,
    worker_id: int,
    role_codes: Iterable[str],
    ctx: JointScopeContext,
    *,
    on_date: date | None = None,
) -> set[str]:
    """Возвращает подмножество `role_codes`, по которым у работника есть активная
    роль, покрывающая Joint по иерархии. Пусто → доступа нет.

    Несколько активных ролей объединяют разрешённые scope. Неактивные/просроченные
    роли и роль без подходящего scope не учитываются (§19 ADR-011).
    """
    return {
        grant.actor_role_code
        for grant in worker_authorization_grants_for_joint(
            db,
            worker_id,
            role_codes,
            ctx,
            on_date=on_date,
        )
    }
