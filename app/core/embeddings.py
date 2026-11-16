"""Text embedders behind one small interface.

- SentenceTransformerEmbedder: the real model (default all-MiniLM-L6-v2), CPU.
- HashingEmbedder: character n-gram hashing. No download, deterministic, fast.
  Used by the test suite and CI, and useful as a baseline; it does not
  understand meaning, so do not report results from it as "the model".

Both return L2-normalised vectors, so a dot product is the cosine similarity.
"""

import hashlib
from collections import OrderedDict
from collections.abc import Sequence
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    name: str

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class HashingEmbedder:
    def __init__(self, n_features: int = 4096):
        from sklearn.feature_extraction.text import HashingVectorizer

        self.name = f"hashing-char-{n_features}"
        self._dim = n_features
        self._vectorizer = HashingVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            n_features=n_features,
            norm="l2",
            alternate_sign=False,
            lowercase=True,
        )

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return self._vectorizer.transform(list(texts)).toarray().astype(np.float32)


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer  # heavy import, kept local

        self.name = model_name.split("/")[-1]
        self._model = SentenceTransformer(model_name, device="cpu")
        self._dim = len(self._model.encode(["warm up"])[0])

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return self._model.encode(
            list(texts),
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype(np.float32)


def build_embedder(backend: str, model_name: str) -> Embedder:
    if backend == "hashing":
        return HashingEmbedder()
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model_name)
    raise ValueError(f"Unknown embedding backend: {backend!r}")


class EmbeddingCache:
    """Small LRU cache: JD sentence embeddings keyed by a hash of the JD text."""

    def __init__(self, max_items: int = 128):
        self._items: OrderedDict[str, np.ndarray] = OrderedDict()
        self._max = max_items
        self.hits = 0

    @staticmethod
    def key(embedder_name: str, texts: Sequence[str]) -> str:
        digest = hashlib.sha256("\x1f".join(texts).encode("utf-8")).hexdigest()
        return f"{embedder_name}:{digest}"

    def encode(self, embedder: Embedder, texts: Sequence[str]) -> np.ndarray:
        key = self.key(embedder.name, texts)
        if key in self._items:
            self._items.move_to_end(key)
            self.hits += 1
            return self._items[key]
        vectors = embedder.encode(texts)
        self._items[key] = vectors
        if len(self._items) > self._max:
            self._items.popitem(last=False)
        return vectors
