"""Add anonymous suggestion fields to suggestion_sessions.

Revision ID: t8u9v0w1x2y3
Revises: s7t8u9v0w1x2
Create Date: 2026-04-03
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "t8u9v0w1x2y3"
down_revision = "s7t8u9v0w1x2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("suggestion_sessions", sa.Column("is_anonymous", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("suggestion_sessions", sa.Column("submitter_name", sa.String(), nullable=True))
    op.add_column("suggestion_sessions", sa.Column("submitter_email", sa.String(), nullable=True))
    op.add_column("suggestion_sessions", sa.Column("client_ip", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("suggestion_sessions", "client_ip")
    op.drop_column("suggestion_sessions", "submitter_email")
    op.drop_column("suggestion_sessions", "submitter_name")
    op.drop_column("suggestion_sessions", "is_anonymous")
