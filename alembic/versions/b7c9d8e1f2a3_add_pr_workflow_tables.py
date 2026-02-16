"""Add PR workflow tables

Revision ID: b7c9d8e1f2a3
Revises: e68f6b98b09b
Create Date: 2026-02-09 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c9d8e1f2a3'
down_revision: str | Sequence[str] | None = 'e68f6b98b09b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add pr_approval_required column to projects table
    op.add_column('projects', sa.Column('pr_approval_required', sa.Integer(), nullable=False, server_default='0'))

    # Create pull_requests table
    op.create_table('pull_requests',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('pr_number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source_branch', sa.String(length=255), nullable=False),
        sa.Column('target_branch', sa.String(length=255), nullable=False, server_default='main'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='open'),
        sa.Column('author_id', sa.String(length=255), nullable=False),
        sa.Column('github_pr_number', sa.Integer(), nullable=True),
        sa.Column('github_pr_url', sa.String(length=1000), nullable=True),
        sa.Column('merged_by', sa.String(length=255), nullable=True),
        sa.Column('merged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'pr_number', name='uq_project_pr_number')
    )
    op.create_index('ix_pull_requests_project_id', 'pull_requests', ['project_id'])
    op.create_index('ix_pull_requests_author_id', 'pull_requests', ['author_id'])
    op.create_index('ix_pull_requests_status', 'pull_requests', ['status'])

    # Create pull_request_reviews table
    op.create_table('pull_request_reviews',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('pull_request_id', sa.Uuid(), nullable=False),
        sa.Column('reviewer_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('github_review_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['pull_request_id'], ['pull_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_pull_request_reviews_pull_request_id', 'pull_request_reviews', ['pull_request_id'])
    op.create_index('ix_pull_request_reviews_reviewer_id', 'pull_request_reviews', ['reviewer_id'])

    # Create pull_request_comments table
    op.create_table('pull_request_comments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('pull_request_id', sa.Uuid(), nullable=False),
        sa.Column('author_id', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('parent_id', sa.Uuid(), nullable=True),
        sa.Column('github_comment_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['parent_id'], ['pull_request_comments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pull_request_id'], ['pull_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_pull_request_comments_pull_request_id', 'pull_request_comments', ['pull_request_id'])
    op.create_index('ix_pull_request_comments_author_id', 'pull_request_comments', ['author_id'])
    op.create_index('ix_pull_request_comments_parent_id', 'pull_request_comments', ['parent_id'])

    # Create github_integrations table
    op.create_table('github_integrations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('repo_owner', sa.String(length=255), nullable=False),
        sa.Column('repo_name', sa.String(length=255), nullable=False),
        sa.Column('installation_id', sa.Integer(), nullable=False),
        sa.Column('webhook_secret', sa.String(length=255), nullable=False),
        sa.Column('default_branch', sa.String(length=255), nullable=False, server_default='main'),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sync_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', name='uq_github_integration_project')
    )
    op.create_index('ix_github_integrations_project_id', 'github_integrations', ['project_id'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop github_integrations table
    op.drop_index('ix_github_integrations_project_id', table_name='github_integrations')
    op.drop_table('github_integrations')

    # Drop pull_request_comments table
    op.drop_index('ix_pull_request_comments_parent_id', table_name='pull_request_comments')
    op.drop_index('ix_pull_request_comments_author_id', table_name='pull_request_comments')
    op.drop_index('ix_pull_request_comments_pull_request_id', table_name='pull_request_comments')
    op.drop_table('pull_request_comments')

    # Drop pull_request_reviews table
    op.drop_index('ix_pull_request_reviews_reviewer_id', table_name='pull_request_reviews')
    op.drop_index('ix_pull_request_reviews_pull_request_id', table_name='pull_request_reviews')
    op.drop_table('pull_request_reviews')

    # Drop pull_requests table
    op.drop_index('ix_pull_requests_status', table_name='pull_requests')
    op.drop_index('ix_pull_requests_author_id', table_name='pull_requests')
    op.drop_index('ix_pull_requests_project_id', table_name='pull_requests')
    op.drop_table('pull_requests')

    # Remove pr_approval_required column from projects table
    op.drop_column('projects', 'pr_approval_required')
