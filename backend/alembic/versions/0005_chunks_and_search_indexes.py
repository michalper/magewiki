"""chunks table (pgvector + tsvector) and pg_trgm identifier indexes

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_analysis_cache_kind", "analysis_cache", type_="check")
    op.create_check_constraint(
        "ck_analysis_cache_kind", "analysis_cache", "kind IN ('file_summary','module_synthesis','embedding')"
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_type", sa.Text, nullable=False),
        sa.Column("relative_path", sa.Text, nullable=True),
        sa.Column("method_id", sa.Integer, sa.ForeignKey("php_class_methods.id", ondelete="CASCADE"), nullable=True),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR,
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint("ck_chunks_chunk_type", "chunks", "chunk_type IN ('module','file','method')")
    op.create_index("ix_chunks_module_id", "chunks", ["module_id"])
    op.create_index("ix_chunks_module_chunk_type", "chunks", ["module_id", "chunk_type"])
    op.create_index("ix_chunks_relative_path", "chunks", ["relative_path"])
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_chunks_tsv_gin", "chunks", ["tsv"], postgresql_using="gin")

    op.create_index(
        "ix_modules_name_trgm", "modules", ["name"], postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}
    )
    op.create_index(
        "ix_php_classes_fqcn_trgm",
        "php_classes",
        ["fqcn"],
        postgresql_using="gin",
        postgresql_ops={"fqcn": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_php_classes_class_name_trgm",
        "php_classes",
        ["class_name"],
        postgresql_using="gin",
        postgresql_ops={"class_name": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_php_classes_class_name_trgm", table_name="php_classes")
    op.drop_index("ix_php_classes_fqcn_trgm", table_name="php_classes")
    op.drop_index("ix_modules_name_trgm", table_name="modules")
    op.drop_table("chunks")
    op.drop_constraint("ck_analysis_cache_kind", "analysis_cache", type_="check")
    op.create_check_constraint(
        "ck_analysis_cache_kind", "analysis_cache", "kind IN ('file_summary','module_synthesis')"
    )
