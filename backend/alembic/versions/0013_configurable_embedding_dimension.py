"""Make chunks.embedding's vector dimension configurable via EMBEDDING_DIMENSIONS

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-06

Fixes a real bug: chunks.embedding was hardcoded Vector(1536) (OpenAI
text-embedding-3-small's dimension), but CLAUDE.md/the README promise bge-m3
(1024-dim, via Ollama) as a BYOK embedding option too — inserting a bge-m3
embedding fails with "expected 1536 dimensions, not 1024". This migration
reads the target dimension from EMBEDDING_DIMENSIONS directly (not via
app.config, to keep migrations standalone) and resizes the column/index to
match, refusing (rather than silently truncating) if chunks already has rows
in a different dimension — those embeddings are in an incompatible vector
space anyway once the model changes, so there is no safe automatic migration
path for existing data; the operator must clear chunks (e.g. re-scan from
empty) first.
"""
import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_DIMENSIONS = 1536


def _resize_embedding_column(target_dimensions: int) -> None:
    connection = op.get_bind()

    current_dimensions = connection.exec_driver_sql(
        "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
    ).scalar_one()
    if current_dimensions == target_dimensions:
        return

    row_count = connection.exec_driver_sql("SELECT COUNT(*) FROM chunks").scalar_one()
    if row_count > 0:
        raise RuntimeError(
            f"chunks has {row_count} row(s) embedded at {current_dimensions} dimensions, but "
            f"EMBEDDING_DIMENSIONS={target_dimensions} was requested. Switching embedding models "
            "requires a full re-embed anyway (vectors from different models aren't comparable) — "
            "clear chunks first (e.g. re-scan from empty), then re-run this migration."
        )

    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.execute(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({target_dimensions})")
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def upgrade() -> None:
    target = int(os.environ.get("EMBEDDING_DIMENSIONS", _DEFAULT_DIMENSIONS))
    _resize_embedding_column(target)


def downgrade() -> None:
    _resize_embedding_column(_DEFAULT_DIMENSIONS)
