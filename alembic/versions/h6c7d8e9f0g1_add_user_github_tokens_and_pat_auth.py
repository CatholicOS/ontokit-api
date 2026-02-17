"""Add user_github_tokens table and PAT-based auth fields to github_integrations.

Revision ID: h6c7d8e9f0g1
Revises: g5b6c7d8e9f0
Create Date: 2026-02-17

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h6c7d8e9f0g1"
down_revision: str | None = "g5b6c7d8e9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create user_github_tokens table
    op.create_table(
        "user_github_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("github_username", sa.String(255), nullable=True),
        sa.Column("token_scopes", sa.String(1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_github_tokens_user_id", "user_github_tokens", ["user_id"])

    # Alter github_integrations: make installation_id and webhook_secret nullable
    op.alter_column(
        "github_integrations",
        "installation_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "github_integrations",
        "webhook_secret",
        existing_type=sa.String(255),
        nullable=True,
    )

    # Add new columns for PAT-based auth
    op.add_column(
        "github_integrations",
        sa.Column("connected_by_user_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "github_integrations",
        sa.Column(
            "webhooks_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    # Remove new columns
    op.drop_column("github_integrations", "webhooks_enabled")
    op.drop_column("github_integrations", "connected_by_user_id")

    # Restore NOT NULL constraints
    op.alter_column(
        "github_integrations",
        "webhook_secret",
        existing_type=sa.String(255),
        nullable=False,
    )
    op.alter_column(
        "github_integrations",
        "installation_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # Drop user_github_tokens table
    op.drop_index("ix_user_github_tokens_user_id", table_name="user_github_tokens")
    op.drop_table("user_github_tokens")
