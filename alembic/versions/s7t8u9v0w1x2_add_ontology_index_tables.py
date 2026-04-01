"""Add ontology index tables for query optimization.

Revision ID: s7t8u9v0w1x2
Revises: r6s7t8u9v0w1
Create Date: 2026-03-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "s7t8u9v0w1x2"
down_revision: str | None = "r6s7t8u9v0w1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable pg_trgm extension for trigram indexes
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ontology_index_status
    op.create_table(
        "ontology_index_status",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("branch", sa.String(255), nullable=False),
        sa.Column("commit_hash", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("entity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "branch", name="uq_ontology_index_status"),
    )

    # indexed_entities
    op.create_table(
        "indexed_entities",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("branch", sa.String(255), nullable=False),
        sa.Column("iri", sa.String(2000), nullable=False),
        sa.Column("local_name", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("deprecated", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "branch", "iri", name="uq_indexed_entity"),
    )
    op.create_index(
        "ix_indexed_entities_project_branch_type",
        "indexed_entities",
        ["project_id", "branch", "entity_type"],
    )
    op.create_index(
        "ix_indexed_entities_local_name_trgm",
        "indexed_entities",
        ["local_name"],
        postgresql_using="gin",
        postgresql_ops={"local_name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_indexed_entities_iri_trgm",
        "indexed_entities",
        ["iri"],
        postgresql_using="gin",
        postgresql_ops={"iri": "gin_trgm_ops"},
    )

    # indexed_labels
    op.create_table(
        "indexed_labels",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("property_iri", sa.String(2000), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(20), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["indexed_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_indexed_labels_entity_id", "indexed_labels", ["entity_id"])
    op.create_index(
        "ix_indexed_labels_value_trgm",
        "indexed_labels",
        ["value"],
        postgresql_using="gin",
        postgresql_ops={"value": "gin_trgm_ops"},
    )

    # indexed_hierarchy
    op.create_table(
        "indexed_hierarchy",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("branch", sa.String(255), nullable=False),
        sa.Column("child_iri", sa.String(2000), nullable=False),
        sa.Column("parent_iri", sa.String(2000), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "branch",
            "child_iri",
            "parent_iri",
            name="uq_indexed_hierarchy",
        ),
    )
    op.create_index(
        "ix_indexed_hierarchy_parent",
        "indexed_hierarchy",
        ["project_id", "branch", "parent_iri"],
    )
    op.create_index(
        "ix_indexed_hierarchy_child",
        "indexed_hierarchy",
        ["project_id", "branch", "child_iri"],
    )

    # indexed_annotations
    op.create_table(
        "indexed_annotations",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("property_iri", sa.String(2000), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(20), nullable=True),
        sa.Column("is_uri", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["entity_id"], ["indexed_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_indexed_annotations_entity_id", "indexed_annotations", ["entity_id"])


def downgrade() -> None:
    op.drop_table("indexed_annotations")
    op.drop_table("indexed_labels")
    op.drop_table("indexed_hierarchy")
    op.drop_table("indexed_entities")
    op.drop_table("ontology_index_status")
