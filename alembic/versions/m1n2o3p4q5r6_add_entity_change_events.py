"""Add entity_change_events table.

Revision ID: m1n2o3p4q5r6
Revises: l0g1h2i3j4k5
Create Date: 2026-03-05

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m1n2o3p4q5r6"
down_revision: str | None = "l0g1h2i3j4k5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_change_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("branch", sa.String(255), nullable=False),
        sa.Column("entity_iri", sa.String(2000), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("user_name", sa.String(255), nullable=True),
        sa.Column("commit_hash", sa.String(40), nullable=True),
        sa.Column("changed_fields", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("old_values", sa.JSON(), nullable=True),
        sa.Column("new_values", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_change_events_project_entity",
        "entity_change_events",
        ["project_id", "entity_iri"],
    )
    op.create_index(
        "ix_change_events_project_time",
        "entity_change_events",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_change_events_project_branch_time",
        "entity_change_events",
        ["project_id", "branch", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_change_events_project_branch_time")
    op.drop_index("ix_change_events_project_time")
    op.drop_index("ix_change_events_project_entity")
    op.drop_table("entity_change_events")
