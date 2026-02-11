"""Add author_name and author_email to pull_request_comments

Revision ID: 2d41d93ea12f
Revises: c8d9e0f1a2b3
Create Date: 2026-02-11 17:30:37.746302

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d41d93ea12f'
down_revision: Union[str, Sequence[str], None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('pull_request_comments', sa.Column('author_name', sa.String(length=255), nullable=True))
    op.add_column('pull_request_comments', sa.Column('author_email', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('pull_request_comments', 'author_email')
    op.drop_column('pull_request_comments', 'author_name')
