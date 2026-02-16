"""Add lint_runs and lint_issues tables

Revision ID: c8d9e0f1a2b3
Revises: b7c9d8e1f2a3
Create Date: 2026-02-09 20:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c8d9e0f1a2b3'
down_revision: str | Sequence[str] | None = 'b7c9d8e1f2a3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create lint_runs table
    op.create_table('lint_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('issues_found', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_lint_runs_project_id', 'lint_runs', ['project_id'])
    op.create_index('ix_lint_runs_status', 'lint_runs', ['status'])
    op.create_index('ix_lint_runs_started_at', 'lint_runs', ['started_at'])

    # Create lint_issues table
    op.create_table('lint_issues',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('issue_type', sa.String(length=50), nullable=False),
        sa.Column('rule_id', sa.String(length=100), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('subject_iri', sa.String(length=2000), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['lint_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_lint_issues_run_id', 'lint_issues', ['run_id'])
    op.create_index('ix_lint_issues_project_id', 'lint_issues', ['project_id'])
    op.create_index('ix_lint_issues_issue_type', 'lint_issues', ['issue_type'])
    op.create_index('ix_lint_issues_rule_id', 'lint_issues', ['rule_id'])
    op.create_index('ix_lint_issues_resolved_at', 'lint_issues', ['resolved_at'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop lint_issues table
    op.drop_index('ix_lint_issues_resolved_at', table_name='lint_issues')
    op.drop_index('ix_lint_issues_rule_id', table_name='lint_issues')
    op.drop_index('ix_lint_issues_issue_type', table_name='lint_issues')
    op.drop_index('ix_lint_issues_project_id', table_name='lint_issues')
    op.drop_index('ix_lint_issues_run_id', table_name='lint_issues')
    op.drop_table('lint_issues')

    # Drop lint_runs table
    op.drop_index('ix_lint_runs_started_at', table_name='lint_runs')
    op.drop_index('ix_lint_runs_status', table_name='lint_runs')
    op.drop_index('ix_lint_runs_project_id', table_name='lint_runs')
    op.drop_table('lint_runs')
