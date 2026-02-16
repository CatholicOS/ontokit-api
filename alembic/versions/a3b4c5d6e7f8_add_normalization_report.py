"""Add normalization_report column to projects table and normalization_runs table.

Revision ID: a3b4c5d6e7f8
Revises: 295fa3db0e38
Create Date: 2026-02-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "295fa3db0e38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add normalization_report column to projects (for backward compatibility)
    op.add_column(
        "projects",
        sa.Column("normalization_report", sa.Text(), nullable=True),
    )

    # Create normalization_runs table
    op.create_table(
        "normalization_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("triggered_by", sa.String(255), nullable=True),
        sa.Column("trigger_type", sa.String(50), nullable=False, default="manual"),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("original_format", sa.String(50), nullable=False),
        sa.Column("original_size_bytes", sa.Integer(), nullable=False),
        sa.Column("normalized_size_bytes", sa.Integer(), nullable=False),
        sa.Column("triple_count", sa.Integer(), nullable=False),
        sa.Column("prefixes_removed_count", sa.Integer(), nullable=False, default=0),
        sa.Column("prefixes_added_count", sa.Integer(), nullable=False, default=0),
        sa.Column("format_converted", sa.Boolean(), nullable=False, default=False),
        sa.Column("is_dry_run", sa.Boolean(), nullable=False, default=False),
        sa.Column("commit_hash", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_normalization_runs_project_id",
        "normalization_runs",
        ["project_id"],
    )
    op.create_index(
        "ix_normalization_runs_created_at",
        "normalization_runs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_normalization_runs_created_at", table_name="normalization_runs")
    op.drop_index("ix_normalization_runs_project_id", table_name="normalization_runs")
    op.drop_table("normalization_runs")
    op.drop_column("projects", "normalization_report")
