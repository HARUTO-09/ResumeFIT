"""Text embedders behind one small interface.

- OnnxEmbedder: the real model (all-MiniLM-L6-v2) through ONNX Runtime, using the
  model's official ONNX export. Same tokenizer, 256-token limit, mean pooling and
  normalisation as sentence-transformers, without PyTorch, so the API fits a
  512 MB free host. The default.
- SentenceTransformerEmbedder: the same model through sentence-transformers and
  PyTorch (installed separately, see requirements-torch.txt). Kept for comparison.
- HashingEmbedder: character n-gram hashing. No download, deterministic, fast.
  Used by the test suite and CI, and useful as a baseline; it does not
  understand meaning, so do not report results from it as "the model".

All return L2-normalised vectors, so a dot product is the cosine similarity.
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


class OnnxEmbedder:
    # The model repository commit the files are read from, so every machine and the
    # Docker image use identical weights and tokenizer.
    REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    MAX_TOKENS = 256  # sentence_bert_config.json: max_seq_length
    BATCH = 32

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        import onnxruntime as ort  # kept local: only this backend needs them
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        def fetch(filename: str) -> str:
            return hf_hub_download(model_name, filename, revision=self.REVISION)

        self.name = model_name.split("/")[-1] + "-onnx"
        self._tokenizer = Tokenizer.from_file(fetch("tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=self.MAX_TOKENS)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self._session = ort.InferenceSession(
            fetch("onnx/model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}
        self._dim = self._encode_batch(["warm up"]).shape[1]

    def _encode_batch(self, texts: list[str]) -> np.ndarray:
        encodings = self._tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feed)[0]  # (batch, tokens, dim)
        # mean pooling over real tokens, then L2 normalisation (as sentence-transformers)
        weights = mask[:, :, None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.clip(norms, 1e-12, None)).astype(np.float32)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        texts = list(texts)
        return np.vstack(
            [
                self._encode_batch(texts[i : i + self.BATCH])
                for i in range(0, len(texts), self.BATCH)
            ]
        )


def build_embedder(backend: str, model_name: str) -> Embedder:
    if backend == "hashing":
        return HashingEmbedder()
    if backend == "onnx":
        return OnnxEmbedder(model_name)
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
