"""add subject_type to lint_issues

Revision ID: 47cc27515626
Revises: 94afeba9ab5c
Create Date: 2026-04-21 12:34:26.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "47cc27515626"
down_revision = "94afeba9ab5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lint_issues", sa.Column("subject_type", sa.String(length=50), nullable=True))
    op.create_check_constraint(
        "ck_lint_issues_subject_type",
        "lint_issues",
        "subject_type IS NULL OR subject_type IN ('class', 'property', 'individual', 'other')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_lint_issues_subject_type", "lint_issues", type_="check")
    op.drop_column("lint_issues", "subject_type")
