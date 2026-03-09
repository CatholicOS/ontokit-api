"""Add embedding tables (pgvector).

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-03-05

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n2o3p4q5r6s7"
down_revision: str | None = "m1n2o3p4q5r6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "project_embedding_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("provider", sa.String(50), nullable=False, server_default="local"),
        sa.Column(
            "model_name", sa.String(200), nullable=False, server_default="all-MiniLM-L6-v2"
        ),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("dimensions", sa.Integer(), nullable=False, server_default="384"),
        sa.Column("auto_embed_on_save", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_full_embed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Use raw SQL for the vector column since alembic doesn't natively handle it
    op.create_table(
        "entity_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("branch", sa.String(255), nullable=False, server_default="main"),
        sa.Column("entity_iri", sa.String(2000), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("label", sa.String(500), nullable=True),
        sa.Column("embedding_text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("deprecated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Add vector column via raw SQL (dimension-agnostic)
    op.execute("ALTER TABLE entity_embeddings ADD COLUMN embedding vector NOT NULL")

    op.create_unique_constraint(
        "uq_entity_embedding",
        "entity_embeddings",
        ["project_id", "branch", "entity_iri"],
    )
    op.create_index(
        "ix_entity_embeddings_project_branch",
        "entity_embeddings",
        ["project_id", "branch"],
    )

    op.create_table(
        "embedding_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("branch", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("total_entities", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedded_entities", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("embedding_jobs")
    op.drop_index("ix_entity_embeddings_project_branch")
    op.drop_constraint("uq_entity_embedding", "entity_embeddings")
    op.drop_table("entity_embeddings")
    op.drop_table("project_embedding_configs")
