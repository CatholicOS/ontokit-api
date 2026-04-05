"""rename upstream to remote sync

Revision ID: r1s2t3u4v5w6
Revises: s7t8u9v0w1x2
Create Date: 2026-04-05
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "r1s2t3u4v5w6"
down_revision = "s7t8u9v0w1x2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename table
    op.rename_table("upstream_sync_configs", "remote_sync_configs")

    # Rename columns
    op.alter_column(
        "remote_sync_configs",
        "upstream_commit_sha",
        new_column_name="remote_commit_sha",
    )
    op.alter_column(
        "sync_events",
        "upstream_commit_sha",
        new_column_name="remote_commit_sha",
    )

    # Rename index
    op.drop_index("ix_upstream_sync_configs_project_id", table_name="remote_sync_configs")
    op.create_index("ix_remote_sync_configs_project_id", "remote_sync_configs", ["project_id"])


def downgrade() -> None:
    # Revert index
    op.drop_index("ix_remote_sync_configs_project_id", table_name="remote_sync_configs")
    op.create_index("ix_upstream_sync_configs_project_id", "remote_sync_configs", ["project_id"])

    # Revert columns
    op.alter_column(
        "sync_events",
        "remote_commit_sha",
        new_column_name="upstream_commit_sha",
    )
    op.alter_column(
        "remote_sync_configs",
        "remote_commit_sha",
        new_column_name="upstream_commit_sha",
    )

    # Revert table
    op.rename_table("remote_sync_configs", "upstream_sync_configs")
