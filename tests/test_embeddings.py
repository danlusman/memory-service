from __future__ import annotations

from src.embeddings import cosine_similarity, embed_text


def test_embedding_generation_non_empty():
    vec = embed_text("I just moved to Berlin and adopted a dog named Biscuit.")
    assert isinstance(vec, list)
    assert len(vec) > 0


def test_embedding_similarity_prefers_related_text():
    q = embed_text("Where does the user live?")
    rel = embed_text("Lives in Berlin")
    irr = embed_text("How to bake sourdough bread")
    assert cosine_similarity(q, rel) >= cosine_similarity(q, irr)

