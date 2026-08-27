"""
Tests for app/rag/sparse_embeddings.py — real fastembed/ONNX model (local,
no network beyond the one-time model download already cached on disk), no
mocking needed: unlike Ollama-backed dense embeddings, this has no external
service to fake.
"""
from qdrant_client.models import SparseVector

from app.rag import sparse_embeddings as sparse_module


def test_embed_texts_sparse_returns_one_vector_per_text():
    vectors = sparse_module.embed_texts_sparse(["The demo namespace has 3 pods.", "nginx deployment"])
    assert len(vectors) == 2
    for v in vectors:
        assert isinstance(v, SparseVector)
        assert len(v.indices) == len(v.values)
        assert len(v.indices) > 0


def test_embed_texts_sparse_empty_input_returns_empty_list():
    assert sparse_module.embed_texts_sparse([]) == []


def test_embed_query_sparse_returns_a_sparse_vector():
    v = sparse_module.embed_query_sparse("how many pods are running?")
    assert isinstance(v, SparseVector)
    assert len(v.indices) == len(v.values)
    assert len(v.indices) > 0


def test_shared_keyword_produces_overlapping_indices():
    """A document and a query sharing an exact keyword should share at
    least one index — the whole reason sparse search catches exact
    keyword/identifier matches dense embeddings can miss."""
    [doc_vector] = sparse_module.embed_texts_sparse(["The kubeconfig secret rotation runbook."])
    query_vector = sparse_module.embed_query_sparse("kubeconfig rotation")
    assert set(doc_vector.indices) & set(query_vector.indices)


def test_model_singleton_is_reused_across_calls():
    sparse_module.reset_model()
    sparse_module.embed_query_sparse("warm up")
    model_after_first_call = sparse_module._model
    sparse_module.embed_query_sparse("second call")
    assert sparse_module._model is model_after_first_call
