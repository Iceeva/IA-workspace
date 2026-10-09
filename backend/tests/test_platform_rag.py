import asyncio
import math

from app.rag.embedder import EmbeddingError, HashingEmbedder, OpenAICompatEmbedder
from app.rag.search import Doc, cosine, hybrid_search


def run(c): return asyncio.run(c)


def test_hashing_embedder_is_deterministic_normalized_and_lexically_meaningful():
    e = HashingEmbedder(256)
    a, b, c = run(e.embed(["La sécurité des mots de passe", "Sécuriser les mots de passe utilisateurs",
                           "Recette de tarte aux pommes"]))
    assert len(a) == 256 and abs(math.sqrt(sum(x * x for x in a)) - 1) < 1e-9
    assert run(e.embed(["La sécurité des mots de passe"]))[0] == a
    assert cosine(a, b) > cosine(a, c) + 0.2
    assert run(e.embed([""]))[0] == [0.0] * 256                      # texte vide : vecteur nul, pas d'erreur
    try:
        HashingEmbedder(4); assert False
    except ValueError:
        pass


def test_hybrid_search_combines_keyword_and_vector_rankings():
    e = HashingEmbedder(256)
    texts = ["Politique de rotation des clés API et des secrets", "Menu de la cantine de la semaine",
             "Guide: chiffrer les secrets avec AES-GCM", "Résultats du tournoi de football", "PostgreSQL: index et vacuum"]
    vecs = run(e.embed(texts))
    docs = [Doc(i, t, v) for i, (t, v) in enumerate(zip(texts, vecs))]
    q = "comment protéger les secrets"
    hits = hybrid_search(q, run(e.embed([q]))[0], docs, k=2)
    assert {h.doc.id for h in hits} == {0, 2} and all(h.score > 0 for h in hits)
    unrelated = hybrid_search("xylophone quantique", None, docs)
    assert unrelated == []                                                      # aucun mot en commun : aucun résultat
    only_kw = hybrid_search("PostgreSQL vacuum", None, docs)                    # sans vecteur : lexical seul
    assert [h.doc.id for h in only_kw] == [4] and only_kw[0].vector_rank is None
    assert hybrid_search("x", None, []) == []


def test_openai_compatible_embedder_batches_orders_and_validates():
    calls = []
    async def post(url, headers, payload):
        calls.append((url, headers, len(payload["input"])))
        n = len(payload["input"])
        return {"data": [{"index": i, "embedding": [float(i + 1), 0.0, 0.0]} for i in reversed(range(n))]}  # désordre voulu
    e = OpenAICompatEmbedder("http://x/v1/", "emb", "k", batch=2, post=post)
    out = run(e.embed(["a", "b", "c"]))
    assert [c[2] for c in calls] == [2, 1] and calls[0][0] == "http://x/v1/embeddings"
    assert calls[0][1] == {"Authorization": "Bearer k"} and out[0] == [1.0, 0.0, 0.0] and out[1] == [1.0, 0.0, 0.0]
    async def broken(url, headers, payload): return {"data": []}
    try:
        run(OpenAICompatEmbedder("http://x", "m", post=broken).embed(["a"])); assert False
    except EmbeddingError:
        pass
