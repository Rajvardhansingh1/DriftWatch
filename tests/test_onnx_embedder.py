import sys
import types

import numpy as np

from monitor.config import settings
from monitor.signals import embedding_drift as ed


def test_onnx_embedder_has_encode_shape(monkeypatch):
    class FakeTE:
        def __init__(self, name):
            pass

        def embed(self, texts):
            return (np.ones(384) for _ in texts)

    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTE))
    monkeypatch.setattr(settings, "embedder", "onnx")
    monkeypatch.setattr(ed, "_embedder", None)
    assert ed.embed_texts(["a", "b"]).shape == (2, 384)
