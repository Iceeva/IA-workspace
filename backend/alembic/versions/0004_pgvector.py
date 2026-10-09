"""RAG côté PostgreSQL : extension pgvector (si disponible) et index plein texte.

Facultatif et sans effet hors PostgreSQL. Si l'extension n'est pas installable (droits, image sans pgvector), la migration
continue et la recherche retombe sur le calcul en Python. Les embeddings restent en JSON (dimension variable selon le modèle
d'embedding) : la pré-sélection par `<=>` se fait sans index vectoriel ; si vous fixez un modèle d'embedding unique, ajoutez
une colonne `vector(N)` et un index HNSW (voir docs/PLATFORM.md)."""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:  # noqa: BLE001
        pass
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_file_chunks_fts ON file_chunks USING gin (to_tsvector('simple', content))"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("DROP INDEX IF EXISTS ix_file_chunks_fts"))
