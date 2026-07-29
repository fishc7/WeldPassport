"""HR worker roles: add MASTER role_code and scoped UUID scope_id.

Revision ID: 20260710_01_hr_master_role
Revises: 20260703_03_welder_admissions
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260710_01_hr_master_role"
down_revision: Union[str, None] = "20260703_03_welder_admissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HR_SCHEMA = "hr"

ROLE_CODE_CHECK = (
    "role_code IN ("
    "'WELDER', 'FOREMAN', 'MASTER', 'PTO_ENGINEER', 'OTK_INSPECTOR', "
    "'NDT_SPECIALIST', 'OGS_ENGINEER', 'CONFIRMING_PERSON', 'CLOSING_RESPONSIBLE'"
    ")"
)

PREVIOUS_ROLE_CODE_CHECK = (
    "role_code IN ("
    "'WELDER', 'FOREMAN', 'PTO_ENGINEER', 'OTK_INSPECTOR', "
    "'NDT_SPECIALIST', 'OGS_ENGINEER', 'CONFIRMING_PERSON', 'CLOSING_RESPONSIBLE'"
    ")"
)

SCOPE_TYPE_CHECK = (
    "scope_type IN ('GLOBAL', 'COMPANY', 'PROJECT', 'SITE', 'LINE')"
)

PREVIOUS_SCOPE_TYPE_CHECK = (
    "scope_type IN ('GLOBAL', 'COMPANY', 'PROJECT', 'SITE')"
)


def upgrade() -> None:
    op.execute(
        f'DROP INDEX IF EXISTS "{HR_SCHEMA}".uq_hr_worker_roles_active_scope'
    )

    op.alter_column(
        "worker_roles",
        "scope_id",
        existing_type=sa.Integer(),
        type_=sa.String(length=36),
        existing_nullable=True,
        postgresql_using="scope_id::text",
        schema=HR_SCHEMA,
    )

    op.drop_constraint(
        "ck_hr_worker_roles_role_code",
        "worker_roles",
        schema=HR_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_hr_worker_roles_role_code",
        "worker_roles",
        ROLE_CODE_CHECK,
        schema=HR_SCHEMA,
    )

    op.drop_constraint(
        "ck_hr_worker_roles_scope_type",
        "worker_roles",
        schema=HR_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_hr_worker_roles_scope_type",
        "worker_roles",
        SCOPE_TYPE_CHECK,
        schema=HR_SCHEMA,
    )

    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_hr_worker_roles_active_scope
        ON "{HR_SCHEMA}".worker_roles (
            worker_id,
            role_code,
            scope_type,
            COALESCE(scope_id, '')
        )
        WHERE is_active = true
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM "{HR_SCHEMA}".worker_roles
                WHERE role_code = 'MASTER'
            ) THEN
                RAISE EXCEPTION
                    'Нельзя откатить миграцию: есть записи role_code=MASTER';
            END IF;
        END $$;
        """
    )

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM "{HR_SCHEMA}".worker_roles
                WHERE scope_type = 'LINE'
            ) THEN
                RAISE EXCEPTION
                    'Нельзя откатить миграцию: есть записи scope_type=LINE';
            END IF;
        END $$;
        """
    )

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM "{HR_SCHEMA}".worker_roles
                WHERE scope_id IS NOT NULL
                  AND scope_id !~ '^[0-9]+$'
            ) THEN
                RAISE EXCEPTION
                    'Нельзя откатить миграцию: scope_id содержит нечисловые значения';
            END IF;
        END $$;
        """
    )

    op.execute(
        f'DROP INDEX IF EXISTS "{HR_SCHEMA}".uq_hr_worker_roles_active_scope'
    )

    op.drop_constraint(
        "ck_hr_worker_roles_scope_type",
        "worker_roles",
        schema=HR_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_hr_worker_roles_scope_type",
        "worker_roles",
        PREVIOUS_SCOPE_TYPE_CHECK,
        schema=HR_SCHEMA,
    )

    op.drop_constraint(
        "ck_hr_worker_roles_role_code",
        "worker_roles",
        schema=HR_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_hr_worker_roles_role_code",
        "worker_roles",
        PREVIOUS_ROLE_CODE_CHECK,
        schema=HR_SCHEMA,
    )

    op.alter_column(
        "worker_roles",
        "scope_id",
        existing_type=sa.String(length=36),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="NULLIF(scope_id, '')::integer",
        schema=HR_SCHEMA,
    )

    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_hr_worker_roles_active_scope
        ON "{HR_SCHEMA}".worker_roles (
            worker_id,
            role_code,
            scope_type,
            COALESCE(scope_id, 0)
        )
        WHERE is_active = true
        """
    )
