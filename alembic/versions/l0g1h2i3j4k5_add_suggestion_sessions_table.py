"""Add suggestion_sessions table.

Revision ID: l0g1h2i3j4k5
Revises: k9f0g1h2i3j4
Create Date: 2026-03-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l0g1h2i3j4k5"
down_revision: str | None = "k9f0g1h2i3j4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "suggestion_sessions",
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
        sa.Column("session_id", sa.String(100), nullable=False),
        sa.Column("branch", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.CheckConstraint(
            "status IN ('active', 'submitted', 'auto-submitted', 'discarded')",
            name="ck_suggestion_session_status",
        ),
        sa.Column("changes_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entities_modified", sa.Text(), nullable=True),
        sa.Column("beacon_token", sa.String(500), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column(
            "pr_id",
            sa.Uuid(),
            sa.ForeignKey("pull_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_activity",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Unique constraint: one session_id per project
    op.create_unique_constraint(
        "uq_suggestion_session", "suggestion_sessions", ["project_id", "session_id"]
    )

    # Indexes for common queries
    op.create_index("ix_suggestion_sessions_project_id", "suggestion_sessions", ["project_id"])
    op.create_index("ix_suggestion_sessions_user_id", "suggestion_sessions", ["user_id"])
    op.create_index("ix_suggestion_sessions_status", "suggestion_sessions", ["status"])
    # Partial unique index: at most one ACTIVE session per user per project
    op.create_index(
        "uq_one_active_session_per_user",
        "suggestion_sessions",
        ["project_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_one_active_session_per_user", table_name="suggestion_sessions")
    op.drop_index("ix_suggestion_sessions_status", table_name="suggestion_sessions")
    op.drop_index("ix_suggestion_sessions_user_id", table_name="suggestion_sessions")
    op.drop_index("ix_suggestion_sessions_project_id", table_name="suggestion_sessions")
    op.drop_constraint("uq_suggestion_session", "suggestion_sessions")
    op.drop_table("suggestion_sessions")
