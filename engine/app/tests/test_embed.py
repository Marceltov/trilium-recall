import os
from pathlib import Path

import numpy as np
import pytest

from embed import HashEmbedder, OnnxEmbedder

MODEL_DIR = Path(os.environ.get("RECALL_TEST_MODEL_DIR", Path(__file__).parents[2] / ".models" / "e5-small"))


def test_hash_embedder_shape_and_norm():
    v = HashEmbedder().embed_passages(["proxmox lxc swap", "a"])
    assert v.shape == (2, 384) and v.dtype == np.float32
    assert np.allclose(np.linalg.norm(v, axis=1), 1)


def test_hash_embedder_overlap_scores_higher():
    e = HashEmbedder()
    q = e.embed_queries(["proxmox swap"])[0]
    a, b = e.embed_passages(["proxmox lxc swap limit", "pizza dough recipe"])
    assert q @ a > q @ b


def test_hash_embedder_empty_text_is_finite():
    v = HashEmbedder().embed_queries([""])
    assert np.isfinite(v).all()


@pytest.mark.skipif(not (MODEL_DIR / "model.onnx").exists(), reason="model not fetched")
def test_onnx_cross_lingual():
    e = OnnxEmbedder(MODEL_DIR)
    assert e.dim == 384 and e.name == "multilingual-e5-small-int8"
    q = e.embed_queries(["Wie viel Arbeitsspeicher hat der Container?"])[0]
    a, b = e.embed_passages(["The container has 2 GB of RAM and no swap.", "Pizza dough needs 48 hours."])
    assert q @ a > q @ b
    assert np.isclose(np.linalg.norm(a), 1, atol=1e-4)


@pytest.mark.skipif(not (MODEL_DIR / "model.onnx").exists(), reason="model not fetched")
def test_onnx_truncates_long_input():
    e = OnnxEmbedder(MODEL_DIR)
    v = e.embed_queries(["word " * 5000])
    assert v.shape == (1, 384) and np.isfinite(v).all()
