"""Add github_hook_id to github_integrations.

Revision ID: r6s7t8u9v0w1
Revises: q5r6s7t8u9v0
Create Date: 2026-03-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r6s7t8u9v0w1"
down_revision: str | None = "q5r6s7t8u9v0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "github_integrations",
        sa.Column("github_hook_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("github_integrations", "github_hook_id")
