"""Add suggestion review fields.

Revision ID: q5r6s7t8u9v0
Revises: p4q5r6s7t8u9
Create Date: 2026-03-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q5r6s7t8u9v0"
down_revision: str | None = "p4q5r6s7t8u9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "suggestion_sessions",
        sa.Column("reviewer_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "suggestion_sessions",
        sa.Column("reviewer_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "suggestion_sessions",
        sa.Column("reviewer_email", sa.String(255), nullable=True),
    )
    op.add_column(
        "suggestion_sessions",
        sa.Column("reviewer_feedback", sa.Text(), nullable=True),
    )
    op.add_column(
        "suggestion_sessions",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "suggestion_sessions",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "suggestion_sessions",
        sa.Column("summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("suggestion_sessions", "summary")
    op.drop_column("suggestion_sessions", "revision")
    op.drop_column("suggestion_sessions", "reviewed_at")
    op.drop_column("suggestion_sessions", "reviewer_feedback")
    op.drop_column("suggestion_sessions", "reviewer_email")
    op.drop_column("suggestion_sessions", "reviewer_name")
    op.drop_column("suggestion_sessions", "reviewer_id")
