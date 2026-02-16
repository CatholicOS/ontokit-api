"""Add source_file_path and ontology_iri to projects

Revision ID: a1b2c3d4e5f6
Revises: 5f63c89c3669
Create Date: 2026-02-09 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "5f63c89c3669"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add source_file_path and ontology_iri columns to projects table."""
    op.add_column(
        "projects",
        sa.Column("source_file_path", sa.String(500), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("ontology_iri", sa.String(1000), nullable=True),
    )


def downgrade() -> None:
    """Remove source_file_path and ontology_iri columns from projects table."""
    op.drop_column("projects", "ontology_iri")
    op.drop_column("projects", "source_file_path")
