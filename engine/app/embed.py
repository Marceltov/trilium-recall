"""Text embedders: the real ONNX model, and a deterministic hashing stand-in for tests."""

import hashlib
import re
from pathlib import Path
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int
    name: str

    def embed_queries(self, texts: list[str]) -> np.ndarray: ...

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...


def _normalise(v: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return (v / norms).astype(np.float32)


def token_batches(lengths: list[int], budget: int) -> list[list[int]]:
    """Group indices so each batch's padded size (count × longest) stays within budget.

    Memory at inference grows with the padded batch, so long passages go alone or in pairs
    while short ones share a batch. Sorting by length keeps padding small.
    """
    batches: list[list[int]] = []
    current: list[int] = []
    for i in sorted(range(len(lengths)), key=lambda i: lengths[i]):
        if current and (len(current) + 1) * lengths[i] > budget:
            batches.append(current)
            current = []
        current.append(i)
    if current:
        batches.append(current)
    return batches


class OnnxEmbedder:
    """intfloat/multilingual-e5-small, int8 ONNX: mean pooling over the attention mask, L2-normalised."""

    name = "multilingual-e5-small-int8"
    dim = 384
    max_tokens = 512
    # Padded tokens per inference call: 1024 keeps peak RSS near 310 MB (8 × 512 reached 550 MB).
    token_budget = 1024

    def __init__(self, model_dir: Path, threads: int = 4):
        import onnxruntime as ort
        import sentencepiece as spm

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        # The arena would keep the largest batch's peak reserved for the life of the process.
        options.enable_cpu_mem_arena = False
        self._session = ort.InferenceSession(str(Path(model_dir) / "model.onnx"), options,
                                             providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}
        # The SentencePiece model gives the same ids as the HF tokenizer.json at ~60 MB instead of ~280 MB.
        self._sp = spm.SentencePieceProcessor(model_file=str(Path(model_dir) / "sentencepiece.bpe.model"))

    def _encode(self, text: str) -> list[int]:
        # XLM-R ids: fairseq offset of 1 over SentencePiece, its <unk> (0) is 3, wrapped in <s> (0) … </s> (2).
        ids = [3 if i == 0 else i + 1 for i in self._sp.encode(text)][: self.max_tokens - 2]
        return [0, *ids, 2]

    def _embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        all_encoded = [self._encode(t) for t in texts]
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for batch in token_batches([len(e) for e in all_encoded], self.token_budget):
            encoded = [all_encoded[i] for i in batch]
            width = max(len(e) for e in encoded)
            ids = np.full((len(encoded), width), 1, dtype=np.int64)  # 1 = <pad>
            mask = np.zeros((len(encoded), width), dtype=np.int64)
            for row, e in enumerate(encoded):
                ids[row, : len(e)] = e
                mask[row, : len(e)] = 1
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self._session.run(None, feed)[0]
            weights = mask[..., None].astype(np.float32)
            out[batch] = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
        return _normalise(out)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._embed([f"query: {t}" for t in texts])

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._embed([f"passage: {t}" for t in texts])


class HashEmbedder:
    """Bag of lower-cased words hashed into buckets: overlap in words means similarity. Tests only."""

    name = "hash-test"

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _embed(self, texts: list[str]) -> np.ndarray:
        v = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                bucket = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=4).digest(), "big")
                v[row, bucket % self.dim] += 1
        return _normalise(v)

    embed_queries = _embed
    embed_passages = _embed
