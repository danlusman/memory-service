from __future__ import annotations

import hashlib
import math
import os
from collections import Counter

import httpx

from .memory_logic import tokenize

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "128"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small").strip()


def _norm(vec: list[float]) -> list[float]:
    mag = math.sqrt(sum(v * v for v in vec))
    if mag == 0:
        return vec
    return [v / mag for v in vec]


def _hash_embed(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vec
    counts = Counter(tokens)
    for token, count in counts.items():
        digest = hashlib.md5(token.encode("utf-8")).hexdigest()
        idx = int(digest[:8], 16) % dim
        sign = 1.0 if (int(digest[8:10], 16) % 2 == 0) else -1.0
        vec[idx] += sign * float(count)
    return _norm(vec)


def _openai_embed(text: str) -> list[float] | None:
    if not OPENAI_API_KEY:
        return None
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={"model": OPENAI_EMBEDDING_MODEL, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()["data"][0]["embedding"]
            return _norm([float(v) for v in data])
    except Exception:
        return None


def embed_text(text: str) -> list[float]:
    ext = _openai_embed(text)
    if ext is not None:
        return ext
    return _hash_embed(text)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(a[i] * b[i] for i in range(n))

