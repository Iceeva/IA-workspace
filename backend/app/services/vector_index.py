"""Index vectoriel pgvector (HNSW) pour le RAG.

Les embeddings d'origine restent en JSON (dimensions et modèles variables). Une colonne `embedding_vec vector(N)` — N =
EMBEDDING_DIM, la dimension du modèle d'embedding de la plateforme — est alimentée en parallèle et indexée en HNSW (cosinus).
Un passage dont le vecteur n'a pas N dimensions n'entre pas dans l'index : la recherche retombe alors sur la voie
sans index (pré-sélection `<=>` + calcul en Python). Rien de tout cela n'agit hors PostgreSQL + pgvector.

Changer de dimension : `python -m app.services.vector_index --dim 768` (recrée la colonne et l'index, puis recopie les vecteurs
compatibles ; les autres seront recalculés par `ensure_embeddings`)."""
from __future__ import annotations
import time

MAX_HNSW_DIM = 2000           # limite de pgvector pour un index HNSW sur le type vector
_flag: dict = {"has": None, "at": 0.0}


def valid_dim(dim: int) -> bool:
    return isinstance(dim, int) and 1 <= dim <= MAX_HNSW_DIM


def vec_literal(v) -> str:
    return "[" + ",".join(f"{float(x):.6g}" for x in v) + "]"


def ddl(dim: int, *, recreate: bool = False) -> list[str]:
    """Instructions SQL (PostgreSQL) : colonne, recopie des vecteurs de dimension N, index HNSW cosinus."""
    if not valid_dim(dim):
        raise ValueError(f"EMBEDDING_DIM doit être compris entre 1 et {MAX_HNSW_DIM}")
    out = []
    if recreate:
        out += ["DROP INDEX IF EXISTS ix_file_chunks_embedding_hnsw", "ALTER TABLE file_chunks DROP COLUMN IF EXISTS embedding_vec"]
    out += [
        f"ALTER TABLE file_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector({dim})",
        "UPDATE file_chunks SET embedding_vec = (embedding::text)::vector WHERE embedding_vec IS NULL AND embedding IS NOT NULL "
        f"AND CASE WHEN json_typeof(embedding) = 'array' THEN json_array_length(embedding) END = {dim}",
        "CREATE INDEX IF NOT EXISTS ix_file_chunks_embedding_hnsw ON file_chunks USING hnsw (embedding_vec vector_cosine_ops)",
    ]
    return out


async def has_column(db) -> bool:
    """La colonne existe-t-elle ? Résultat mémorisé 60 s (la migration peut passer pendant que le serveur tourne)."""
    from sqlalchemy import text
    if _flag["has"] is not None and time.monotonic() - _flag["at"] < 60:
        return _flag["has"]
    row = (await db.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = 'file_chunks' "
                                 "AND column_name = 'embedding_vec'"))).first()
    _flag.update(has=bool(row), at=time.monotonic())
    return bool(row)


async def store(db, pairs: list[tuple[int, list[float]]], dim: int) -> int:
    """Copie dans `embedding_vec` les vecteurs de dimension N (id de passage, vecteur). Sans effet hors PostgreSQL/pgvector."""
    if not pairs or not valid_dim(dim) or db.bind is None or db.bind.dialect.name != "postgresql":
        return 0
    rows = [{"i": i, "v": vec_literal(v)} for i, v in pairs if len(v) == dim]
    if not rows:
        return 0
    from sqlalchemy import text
    try:
        async with db.begin_nested():
            if not await has_column(db):
                return 0
            await db.execute(text("UPDATE file_chunks SET embedding_vec = CAST(:v AS vector) WHERE id = :i"), rows)
    except Exception:  # noqa: BLE001 — l'index est une optimisation : jamais bloquant
        return 0
    return len(rows)


async def nearest(db, org_id, qvec: list[float], model: str, project_id, dim: int, limit: int = 200) -> list[int] | None:
    """Identifiants des `limit` passages les plus proches via l'index HNSW ; None si indisponible (le repli prend le relais)."""
    if not valid_dim(dim) or len(qvec) != dim or db.bind is None or db.bind.dialect.name != "postgresql":
        return None
    from sqlalchemy import text
    try:
        async with db.begin_nested():
            if not await has_column(db):
                return None
            try:   # pgvector ≥ 0.8 : le filtre (organisation, projet) ne doit pas vider la liste de candidats de l'index
                async with db.begin_nested():
                    await db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
                    await db.execute(text("SET LOCAL hnsw.ef_search = 100"))
            except Exception:  # noqa: BLE001 — versions antérieures : réglage inconnu
                pass
            proj = "AND f.project_id = :proj" if project_id else ""
            args = {"org": org_id, "m": model, "q": vec_literal(qvec), "lim": limit, **({"proj": project_id} if project_id else {})}
            ids = (await db.execute(text(
                "SELECT c.id FROM file_chunks c JOIN files f ON f.id = c.file_id WHERE c.organization_id = :org "
                f"AND f.deleted_at IS NULL {proj} AND c.embed_model = :m AND c.embedding_vec IS NOT NULL "
                "ORDER BY c.embedding_vec <=> CAST(:q AS vector) LIMIT :lim"), args)).scalars().all()
        return list(ids)
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    import argparse
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    from app.core.config import get_settings
    ap = argparse.ArgumentParser(description="Recrée l'index vectoriel pour une autre dimension d'embedding")
    ap.add_argument("--dim", type=int, required=True)
    a = ap.parse_args()

    async def go():
        eng = create_async_engine(get_settings().database_url)
        async with eng.begin() as c:
            await c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            for q in ddl(a.dim, recreate=True):
                await c.execute(text(q))
        await eng.dispose()
    asyncio.run(go())
    print(f"Index HNSW recréé pour {a.dim} dimensions. Définissez EMBEDDING_DIM={a.dim}.")


if __name__ == "__main__":
    main()
