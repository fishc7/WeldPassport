"""engineering documents: engineering_documents, document_revisions.

Revision ID: 20260710_04_engineering_docs
Revises: 20260710_03_project_lines
Create Date: 2026-07-10

Идентификатор ревизии сокращён (…_docs вместо …_documents): полное имя из плана
занимало 33 символа и не помещалось в alembic_version.version_num varchar(32).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_04_engineering_docs"
down_revision: Union[str, None] = "20260710_03_project_lines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROJECT_SCHEMA = "project"
ENGINEERING_SCHEMA = "engineering"

DOCUMENT_TYPE_CHECK = (
    "document_type IN ('ISOMETRIC', 'DRAWING', 'WELD_MAP', 'OTHER')"
)
STATUS_CHECK = "status IN ('DRAFT', 'APPROVED', 'CANCELLED', 'SUPERSEDED')"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{ENGINEERING_SCHEMA}"')

    # engineering_documents → document_revisions (порядок из-за FK).
    op.create_table(
        "engineering_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_no", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(trim(document_no)) > 0",
            name="ck_engineering_documents_document_no_not_empty",
        ),
        sa.CheckConstraint(
            DOCUMENT_TYPE_CHECK,
            name="ck_engineering_documents_document_type",
        ),
        sa.CheckConstraint(
            STATUS_CHECK,
            name="ck_engineering_documents_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{PROJECT_SCHEMA}.projects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["line_id"],
            [f"{PROJECT_SCHEMA}.lines.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "document_no",
            name="uq_engineering_documents_project_document_no",
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_documents_project_id",
        "engineering_documents",
        ["project_id"],
        unique=False,
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_documents_line_id",
        "engineering_documents",
        ["line_id"],
        unique=False,
        schema=ENGINEERING_SCHEMA,
    )

    op.create_table(
        "document_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "engineering_document_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("revision_code", sa.String(length=100), nullable=False),
        sa.Column("issued_at", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(trim(revision_code)) > 0",
            name="ck_engineering_document_revisions_revision_code_not_empty",
        ),
        sa.CheckConstraint(
            STATUS_CHECK,
            name="ck_engineering_document_revisions_status",
        ),
        sa.ForeignKeyConstraint(
            ["engineering_document_id"],
            [f"{ENGINEERING_SCHEMA}.engineering_documents.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "engineering_document_id",
            "revision_code",
            name="uq_engineering_document_revisions_doc_revision_code",
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_document_revisions_document_id",
        "document_revisions",
        ["engineering_document_id"],
        unique=False,
        schema=ENGINEERING_SCHEMA,
    )


def downgrade() -> None:
    # document_revisions → engineering_documents (обратный порядок).
    op.drop_index(
        "ix_engineering_document_revisions_document_id",
        table_name="document_revisions",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_table("document_revisions", schema=ENGINEERING_SCHEMA)

    op.drop_index(
        "ix_engineering_documents_line_id",
        table_name="engineering_documents",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_index(
        "ix_engineering_documents_project_id",
        table_name="engineering_documents",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_table("engineering_documents", schema=ENGINEERING_SCHEMA)

    op.execute(f'DROP SCHEMA IF EXISTS "{ENGINEERING_SCHEMA}"')
