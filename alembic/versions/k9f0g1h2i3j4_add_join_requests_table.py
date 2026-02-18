"""Add join_requests table.

Revision ID: k9f0g1h2i3j4
Revises: j8e9f0g1h2i3
Create Date: 2026-02-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k9f0g1h2i3j4"
down_revision: str | None = "j8e9f0g1h2i3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "join_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("user_name", sa.String(255), nullable=True),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("responded_by", sa.String(255), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Indexes for common queries
    op.create_index(
        "ix_join_requests_project_id", "join_requests", ["project_id"]
    )
    op.create_index(
        "ix_join_requests_user_id", "join_requests", ["user_id"]
    )
    op.create_index(
        "ix_join_requests_status", "join_requests", ["status"]
    )

    # Partial unique index: one pending request per user per project
    op.execute(
        "CREATE UNIQUE INDEX ix_join_requests_one_pending_per_user "
        "ON join_requests(project_id, user_id) "
        "WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_join_requests_one_pending_per_user")
    op.drop_index("ix_join_requests_status")
    op.drop_index("ix_join_requests_user_id")
    op.drop_index("ix_join_requests_project_id")
    op.drop_table("join_requests")
