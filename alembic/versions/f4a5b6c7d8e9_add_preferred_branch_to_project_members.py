"""Add preferred_branch to project_members.

Revision ID: f4a5b6c7d8e9
Revises: a3b4c5d6e7f8
Create Date: 2026-02-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_members", sa.Column("preferred_branch", sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("project_members", "preferred_branch")
