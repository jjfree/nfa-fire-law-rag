from app.embedding import HashEmbedder


def test_hash_embedding_is_deterministic_and_normalized():
    e = HashEmbedder(64)
    a = e.embed(["消防安全設備"])[0]
    b = e.embed(["消防安全設備"])[0]
    assert a == b
    assert len(a) == 64
    norm = sum(x * x for x in a) ** 0.5
    assert abs(norm - 1.0) < 1e-8
