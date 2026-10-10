import asyncio

from app.services import vector_index as VI


class FakeDb:
    """Session factice : ni PostgreSQL ni pgvector ; on vérifie que rien n'est tenté."""
    def __init__(self, dialect="sqlite"):
        self.bind = type("B", (), {"dialect": type("D", (), {"name": dialect})()})()

    async def execute(self, *a, **k):
        raise AssertionError("aucune requête attendue")


def run(c):
    return asyncio.run(c)


def test_valid_dim_bounds():
    assert VI.valid_dim(1536) and VI.valid_dim(2000) and VI.valid_dim(1)
    assert not VI.valid_dim(0) and not VI.valid_dim(2001) and not VI.valid_dim(-5)


def test_ddl_creates_column_backfill_and_hnsw_cosine_index():
    q = VI.ddl(768)
    assert q[0] == "ALTER TABLE file_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector(768)"
    assert "json_array_length(embedding)" in q[1] and "= 768" in q[1] and "json_typeof(embedding) = 'array'" in q[1]
    assert "USING hnsw (embedding_vec vector_cosine_ops)" in q[2]
    r = VI.ddl(768, recreate=True)
    assert r[0].startswith("DROP INDEX") and r[1].startswith("ALTER TABLE file_chunks DROP COLUMN") and len(r) == 5
    for bad in (0, 5000):
        try:
            VI.ddl(bad); assert False
        except ValueError:
            pass


def test_vec_literal_is_pgvector_syntax_and_cannot_inject():
    assert VI.vec_literal([0.5, 1, -2.25]) == "[0.5,1,-2.25]"
    try:
        VI.vec_literal(["1); DROP TABLE x;--"]); assert False
    except ValueError:
        pass


def test_store_and_nearest_are_inert_outside_postgres_or_on_dimension_mismatch():
    db = FakeDb("sqlite")
    assert run(VI.store(db, [(1, [0.1] * 4)], 4)) == 0
    assert run(VI.nearest(db, "org", [0.1] * 4, "m", None, 4)) is None
    pg = FakeDb("postgresql")                                   # PostgreSQL mais dimension différente : aucune requête
    assert run(VI.nearest(pg, "org", [0.1] * 3, "m", None, 4)) is None
    assert run(VI.store(pg, [(1, [0.1] * 3)], 4)) == 0
    assert run(VI.nearest(pg, "org", [0.1] * 4, "m", None, 0)) is None


def test_migration_0005_chains_after_0004():
    import importlib.util, pathlib
    p = pathlib.Path(__file__).resolve().parents[1] / "alembic/versions/0005_vector_index.py"
    src = p.read_text()
    assert 'revision = "0005"' in src and 'down_revision = "0004"' in src
