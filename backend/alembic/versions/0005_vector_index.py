"""Index vectoriel HNSW (colonne `embedding_vec vector(EMBEDDING_DIM)`), si PostgreSQL + pgvector. Sans effet sinon."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from app.core.config import get_settings
    from app.services import vector_index as VI
    dim = get_settings().embedding_dim
    if dim == 0 or not VI.valid_dim(dim):
        return
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            for q in VI.ddl(dim):
                bind.execute(sa.text(q))
    except Exception:  # noqa: BLE001 — pgvector absent : la recherche garde la voie sans index
        pass


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("DROP INDEX IF EXISTS ix_file_chunks_embedding_hnsw"))
        bind.execute(sa.text("ALTER TABLE file_chunks DROP COLUMN IF EXISTS embedding_vec"))
