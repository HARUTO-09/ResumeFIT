"""OnnxEmbedder's pooling and batching, with a fake tokenizer and session (no download).

That its vectors match sentence-transformers was checked against the real model on
17 Nov 2026 (cosine 1.000000 on 79 texts); see README "How it works".
"""

from types import SimpleNamespace

import numpy as np

from app.core.embeddings import OnnxEmbedder


class FakeTokenizer:
    def encode_batch(self, texts):
        # one token per word, padded to the longest text
        width = max(len(t.split()) for t in texts)
        out = []
        for t in texts:
            n = len(t.split())
            out.append(
                SimpleNamespace(
                    ids=[1] * n + [0] * (width - n), attention_mask=[1] * n + [0] * (width - n)
                )
            )
        return out


class FakeSession:
    def __init__(self):
        self.batches = []

    def run(self, _outputs, feed):
        ids = feed["input_ids"]
        self.batches.append(ids.shape[0])
        batch, tokens = ids.shape
        hidden = np.zeros((batch, tokens, 2), dtype=np.float32)
        hidden[:, :, 0] = np.arange(1, tokens + 1)  # real tokens 1..n, padding after
        hidden[:, :, 1] = 1.0
        hidden[feed["attention_mask"] == 0] = 1000.0  # padding must be ignored
        return [hidden]


def make():
    emb = OnnxEmbedder.__new__(OnnxEmbedder)
    emb._tokenizer = FakeTokenizer()
    emb._session = FakeSession()
    emb._inputs = {"input_ids", "attention_mask", "token_type_ids"}
    emb._dim = 2
    return emb


def test_mean_pools_real_tokens_only_and_normalises():
    v = make().encode(["one two three", "one"])
    # "one two three": mean of [1,1],[2,1],[3,1] = [2,1]; "one": [1,1]; then unit length
    np.testing.assert_allclose(v[0], np.array([2, 1]) / np.sqrt(5), rtol=1e-6)
    np.testing.assert_allclose(v[1], np.array([1, 1]) / np.sqrt(2), rtol=1e-6)
    assert v.dtype == np.float32


def test_encodes_in_batches_and_handles_empty_input():
    emb = make()
    texts = [f"text {i}" for i in range(70)]
    assert emb.encode(texts).shape == (70, 2)
    assert emb._session.batches == [32, 32, 6]
    assert emb.encode([]).shape == (0, 2)
