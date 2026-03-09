"""Add upstream sync tables.

Revision ID: p4q5r6s7t8u9
Revises: o3p4q5r6s7t8
Create Date: 2026-03-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p4q5r6s7t8u9"
down_revision: str | None = "o3p4q5r6s7t8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upstream_sync_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("repo_owner", sa.String(255), nullable=False),
        sa.Column("repo_name", sa.String(255), nullable=False),
        sa.Column("branch", sa.String(255), nullable=False, server_default="main"),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("frequency", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("update_mode", sa.String(50), nullable=False, server_default="review_required"),
        sa.Column("status", sa.String(50), nullable=False, server_default="idle"),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_update_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upstream_commit_sha", sa.String(255), nullable=True),
        sa.Column("pending_pr_id", sa.Uuid(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pending_pr_id"], ["pull_requests.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index(
        "ix_upstream_sync_configs_project_id",
        "upstream_sync_configs",
        ["project_id"],
    )

    op.create_table(
        "sync_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("config_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("upstream_commit_sha", sa.String(255), nullable=True),
        sa.Column("pr_id", sa.Uuid(), nullable=True),
        sa.Column("changes_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["config_id"], ["upstream_sync_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pr_id"], ["pull_requests.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_events_project_id", "sync_events", ["project_id"])
    op.create_index("ix_sync_events_config_id", "sync_events", ["config_id"])
    op.create_index("ix_sync_events_created_at", "sync_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_sync_events_created_at", table_name="sync_events")
    op.drop_index("ix_sync_events_config_id", table_name="sync_events")
    op.drop_index("ix_sync_events_project_id", table_name="sync_events")
    op.drop_table("sync_events")
    op.drop_index("ix_upstream_sync_configs_project_id", table_name="upstream_sync_configs")
    op.drop_table("upstream_sync_configs")
