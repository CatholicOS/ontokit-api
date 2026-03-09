"""Add notifications table.

Revision ID: o3p4q5r6s7t8
Revises: n2o3p4q5r6s7
Create Date: 2026-03-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "o3p4q5r6s7t8"
down_revision: str | None = "n2o3p4q5r6s7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("target_url", sa.String(1000), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Composite index for the polling query: user + unread + newest first
    op.create_index(
        "ix_notifications_user_unread_created",
        "notifications",
        ["user_id", "is_read", sa.text("created_at DESC")],
    )

    # Simple index for CASCADE deletes on project_id FK
    op.create_index(
        "ix_notifications_project_id",
        "notifications",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_project_id")
    op.drop_index("ix_notifications_user_unread_created")
    op.drop_table("notifications")
