"""add QualityDecision person-level SoD and authorization evidence (AS-02).

Revision ID: 20260724_27_qd_rbac_sod
Revises: 20260724_26_qd_idempotency
Create Date: 2026-07-24

Self-contained correcting migration for ADR-028. Revisions 25/26 are intentionally
not modified. Historical role scope is never reconstructed from current HR data.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260724_27_qd_rbac_sod"
down_revision: Union[str, None] = "20260724_26_qd_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"
DECISIONS_TABLE = "quality_decisions"
AUDIT_TABLE = "quality_audit_events"

REVIEW_SUBMITTER_CONSTRAINT = "ck_quality_decisions_review_submitter_state"
AUDIT_AUTHORIZATION_CONSTRAINT = "ck_quality_audit_qd_authorization_context"


def upgrade() -> None:
    op.add_column(
        DECISIONS_TABLE,
        sa.Column("review_submitted_by_worker_id", sa.Integer(), nullable=True),
        schema=QUALITY_SCHEMA,
    )
    op.add_column(
        AUDIT_TABLE,
        sa.Column(
            "authorization_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema=QUALITY_SCHEMA,
    )

    # Reconstruct only the actor of the latest persisted SUBMIT cycle. Version is the
    # primary ordering key because it is the aggregate's optimistic-lock version at
    # submission time; timestamp/id are deterministic tie-breakers.
    op.execute(
        sa.text(
            """
            WITH ranked_submissions AS (
                SELECT
                    entity_id,
                    actor_worker_id,
                    row_number() OVER (
                        PARTITION BY entity_id
                        ORDER BY
                            CASE
                                WHEN COALESCE(new_values ->> 'version', '')
                                     ~ '^[0-9]+$'
                                THEN (new_values ->> 'version')::bigint
                                ELSE -1
                            END DESC,
                            occurred_at DESC,
                            id DESC
                    ) AS submission_rank
                FROM quality.quality_audit_events
                WHERE entity_type = 'QUALITY_DECISION'
                  AND event_type = 'QUALITY_DECISION_SUBMITTED'
            )
            UPDATE quality.quality_decisions AS decision
            SET review_submitted_by_worker_id = submission.actor_worker_id
            FROM ranked_submissions AS submission
            WHERE submission.entity_id = decision.id
              AND submission.submission_rank = 1
              AND decision.status IN (
                  'UNDER_REVIEW',
                  'DECIDED',
                  'SUPERSEDED'
              )
            """
        )
    )

    # Abort rather than inventing an actor for a non-DRAFT decision whose current
    # review cycle cannot be proven from append-only history.
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM quality.quality_decisions
                    WHERE status IN ('UNDER_REVIEW', 'DECIDED', 'SUPERSEDED')
                      AND review_submitted_by_worker_id IS NULL
                ) THEN
                    RAISE EXCEPTION
                        'AS-02 migration cannot prove review submitter '
                        'for a non-DRAFT QualityDecision';
                END IF;
            END
            $$
            """
        )
    )

    # Existing events predate evidence-bearing grants. Preserve only facts recorded
    # at event time and mark the snapshot as legacy; never infer scope/assignment.
    op.execute(
        sa.text(
            """
            UPDATE quality.quality_audit_events
            SET authorization_context = jsonb_strip_nulls(
                jsonb_build_object(
                    'schema_version', 1,
                    'authorization_snapshot_status',
                    'LEGACY_AUTHORIZATION_SNAPSHOT',
                    'actor_worker_id', actor_worker_id,
                    'actor_role_code', changed_fields ->> 'actor_role'
                )
            )
            WHERE entity_type = 'QUALITY_DECISION'
              AND authorization_context IS NULL
            """
        )
    )

    op.create_check_constraint(
        REVIEW_SUBMITTER_CONSTRAINT,
        DECISIONS_TABLE,
        "(status = 'DRAFT' AND review_submitted_by_worker_id IS NULL) OR "
        "(status IN ('UNDER_REVIEW', 'DECIDED', 'SUPERSEDED') "
        "AND review_submitted_by_worker_id IS NOT NULL)",
        schema=QUALITY_SCHEMA,
    )
    op.create_check_constraint(
        AUDIT_AUTHORIZATION_CONSTRAINT,
        AUDIT_TABLE,
        "entity_type <> 'QUALITY_DECISION' OR authorization_context IS NOT NULL",
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        AUDIT_AUTHORIZATION_CONSTRAINT,
        AUDIT_TABLE,
        schema=QUALITY_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        REVIEW_SUBMITTER_CONSTRAINT,
        DECISIONS_TABLE,
        schema=QUALITY_SCHEMA,
        type_="check",
    )
    op.drop_column(
        AUDIT_TABLE,
        "authorization_context",
        schema=QUALITY_SCHEMA,
    )
    op.drop_column(
        DECISIONS_TABLE,
        "review_submitted_by_worker_id",
        schema=QUALITY_SCHEMA,
    )
