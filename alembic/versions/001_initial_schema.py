"""Initial schema - consolidated from all migrations.

Revision ID: 001_initial
Revises:
Create Date: 2026-02-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Projects table
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, default=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # Import-related fields
        sa.Column("source_file_path", sa.String(length=500), nullable=True),
        sa.Column("ontology_iri", sa.String(length=1000), nullable=True),
        # Label preferences
        sa.Column("label_preferences", sa.String(length=2000), nullable=True),
        # PR workflow settings
        sa.Column("pr_approval_required", sa.Integer(), nullable=False, default=0),
        sa.PrimaryKeyConstraint("id"),
    )

    # Project members table
    op.create_table(
        "project_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, default="viewer"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )

    # Pull requests table
    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_branch", sa.String(length=255), nullable=False),
        sa.Column("target_branch", sa.String(length=255), nullable=False, default="main"),
        sa.Column("status", sa.String(length=50), nullable=False, default="open"),
        sa.Column("author_id", sa.String(length=255), nullable=False),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("author_email", sa.String(length=255), nullable=True),
        sa.Column("github_pr_number", sa.Integer(), nullable=True),
        sa.Column("github_pr_url", sa.String(length=1000), nullable=True),
        sa.Column("merged_by", sa.String(length=255), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merge_commit_hash", sa.String(length=40), nullable=True),
        sa.Column("base_commit_hash", sa.String(length=40), nullable=True),
        sa.Column("head_commit_hash", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "pr_number", name="uq_project_pr_number"),
    )

    # Pull request reviews table
    op.create_table(
        "pull_request_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pull_request_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("github_review_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pull_request_id"], ["pull_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Pull request comments table
    op.create_table(
        "pull_request_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pull_request_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.String(length=255), nullable=False),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("author_email", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("github_comment_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["pull_request_id"], ["pull_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["pull_request_comments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # GitHub integrations table
    op.create_table(
        "github_integrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("repo_owner", sa.String(length=255), nullable=False),
        sa.Column("repo_name", sa.String(length=255), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("webhook_secret", sa.String(length=255), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False, default="main"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )

    # Lint runs table
    op.create_table(
        "lint_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, default="pending"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issues_found", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Lint issues table
    op.create_table(
        "lint_issues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("issue_type", sa.String(length=50), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("subject_iri", sa.String(length=2000), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["lint_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for common queries
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_index("ix_projects_is_public", "projects", ["is_public"])
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
    op.create_index("ix_pull_requests_author_id", "pull_requests", ["author_id"])
    op.create_index("ix_pull_requests_status", "pull_requests", ["status"])
    op.create_index("ix_lint_runs_status", "lint_runs", ["status"])
    op.create_index("ix_lint_issues_rule_id", "lint_issues", ["rule_id"])


def downgrade() -> None:
    op.drop_index("ix_lint_issues_rule_id")
    op.drop_index("ix_lint_runs_status")
    op.drop_index("ix_pull_requests_status")
    op.drop_index("ix_pull_requests_author_id")
    op.drop_index("ix_project_members_user_id")
    op.drop_index("ix_projects_is_public")
    op.drop_index("ix_projects_owner_id")

    op.drop_table("lint_issues")
    op.drop_table("lint_runs")
    op.drop_table("github_integrations")
    op.drop_table("pull_request_comments")
    op.drop_table("pull_request_reviews")
    op.drop_table("pull_requests")
    op.drop_table("project_members")
    op.drop_table("projects")
