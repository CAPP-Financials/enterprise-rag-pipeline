"""
Test Suite: Hybrid Retrieval Module
=====================================
TC-BM25-001 to TC-BM25-004 : BM25RetrieverWrapper edge cases
TC-HYB-001 to TC-HYB-015   : HybridRetriever edge cases
TC-MMR-001 to TC-MMR-008   : MMR filtering edge cases
"""

import logging
import pytest
import numpy as np

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from src.retrieval.hybrid_search import HybridRetriever


# ---------------------------------------------------------------------------
# Mock dense retriever for testing without Pinecone
# ---------------------------------------------------------------------------

class MockDenseRetriever:
    """Simulates a Pinecone vector store for testing."""

    def __init__(self, docs=None):
        self.docs = docs or [
            {"id": f"doc_{i}", "score": 1.0 - i * 0.05, "text": f"Document {i} about enterprise RAG pipelines and knowledge retrieval systems.", "metadata": {"source": f"src_{i}"}}
            for i in range(20)
        ]

    def search(self, query, namespace="default", top_k=5, filters=None):
        if not query or not query.strip():
            return []
        return self.docs[:top_k]


class MockEmptyRetriever:
    """Always returns empty results."""
    def search(self, query, namespace="default", top_k=5, filters=None):
        return []


class MockFailingRetriever:
    """Always raises an exception."""
    def search(self, query, namespace="default", top_k=5, filters=None):
        raise ConnectionError("Pinecone connection failed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def retriever():
    return HybridRetriever(
        dense_retriever=MockDenseRetriever(),
        embedding_model="huggingface",
        alpha=0.5,
        use_mmr=True,
    )


@pytest.fixture(scope="module")
def retriever_no_mmr():
    return HybridRetriever(
        dense_retriever=MockDenseRetriever(),
        embedding_model="huggingface",
        alpha=0.5,
        use_mmr=False,
    )


# ---------------------------------------------------------------------------
# HybridRetriever — Constructor validation
# ---------------------------------------------------------------------------

class TestHybridRetrieverInit:

    def test_valid_init_huggingface(self):
        """TC-HYB-001: Valid init with huggingface embedding model."""
        hr = HybridRetriever(dense_retriever=MockDenseRetriever(), embedding_model="huggingface")
        assert hr is not None

    def test_invalid_embedding_model(self):
        """TC-HYB-002: Unknown embedding model raises ValueError."""
        with pytest.raises(ValueError, match="Unknown embedding_model"):
            HybridRetriever(dense_retriever=MockDenseRetriever(), embedding_model="bert")

    def test_alpha_clamped_above_one(self):
        """TC-HYB-003: alpha > 1.0 is clamped to 1.0."""
        hr = HybridRetriever(dense_retriever=MockDenseRetriever(), embedding_model="huggingface", alpha=1.5)
        assert hr.alpha == 1.0

    def test_alpha_clamped_below_zero(self):
        """TC-HYB-004: alpha < 0.0 is clamped to 0.0."""
        hr = HybridRetriever(dense_retriever=MockDenseRetriever(), embedding_model="huggingface", alpha=-0.3)
        assert hr.alpha == 0.0


# ---------------------------------------------------------------------------
# retrieve() — edge cases
# ---------------------------------------------------------------------------

class TestRetrieve:

    def test_empty_query(self, retriever):
        """TC-HYB-005: Empty query returns []."""
        assert retriever.retrieve("") == []

    def test_whitespace_query(self, retriever):
        """TC-HYB-006: Whitespace-only query returns []."""
        assert retriever.retrieve("   ") == []

    def test_normal_query(self, retriever):
        """TC-HYB-007: Normal query returns top_k results."""
        results = retriever.retrieve("enterprise RAG pipeline", top_k=3)
        assert len(results) <= 3
        assert all("text" in r for r in results)

    def test_top_k_one(self, retriever):
        """TC-HYB-008: top_k=1 returns exactly one result."""
        results = retriever.retrieve("knowledge retrieval", top_k=1)
        assert len(results) == 1

    def test_fetch_k_less_than_top_k(self, retriever):
        """TC-HYB-009: fetch_k < top_k is auto-corrected."""
        results = retriever.retrieve("test query", top_k=5, fetch_k=2)
        assert len(results) <= 5

    def test_empty_retriever(self):
        """TC-HYB-010: Empty retriever returns []."""
        hr = HybridRetriever(dense_retriever=MockEmptyRetriever(), embedding_model="huggingface")
        assert hr.retrieve("test query") == []

    def test_failing_retriever(self):
        """TC-HYB-011: Retriever that raises exception returns [] gracefully."""
        hr = HybridRetriever(dense_retriever=MockFailingRetriever(), embedding_model="huggingface")
        result = hr.retrieve("test query")
        assert result == []

    def test_results_have_hybrid_score(self, retriever):
        """TC-HYB-012: All results contain hybrid_score field."""
        results = retriever.retrieve("enterprise knowledge base", top_k=3)
        assert all("hybrid_score" in r for r in results)

    def test_without_mmr(self, retriever_no_mmr):
        """TC-HYB-013: Without MMR, results are still returned correctly."""
        results = retriever_no_mmr.retrieve("RAG pipeline", top_k=5)
        assert len(results) <= 5

    def test_results_sorted_by_score(self, retriever_no_mmr):
        """TC-HYB-014: Results without MMR are sorted by hybrid_score descending."""
        results = retriever_no_mmr.retrieve("knowledge retrieval", top_k=5)
        if len(results) > 1:
            scores = [r["hybrid_score"] for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_namespace_parameter_accepted(self, retriever):
        """TC-HYB-015: Namespace parameter is accepted without error."""
        results = retriever.retrieve("test", namespace="finance", top_k=3)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# batch_retrieve() — edge cases
# ---------------------------------------------------------------------------

class TestBatchRetrieve:

    def test_empty_queries_list(self, retriever):
        """TC-BATCH-001: Empty queries list returns []."""
        assert retriever.batch_retrieve([]) == []

    def test_single_query(self, retriever):
        """TC-BATCH-002: Single query returns list of one result-list."""
        results = retriever.batch_retrieve(["enterprise RAG"])
        assert len(results) == 1
        assert isinstance(results[0], list)

    def test_multiple_queries(self, retriever):
        """TC-BATCH-003: Multiple queries return one result-list per query."""
        queries = ["RAG pipeline", "knowledge base", "semantic search"]
        results = retriever.batch_retrieve(queries, top_k=3)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# MMR filtering — edge cases
# ---------------------------------------------------------------------------

class TestMMRFiltering:

    def _make_docs(self, n, identical=False):
        text = "Enterprise RAG pipeline for knowledge retrieval." if identical else None
        return [
            {
                "id": f"doc_{i}",
                "score": 1.0 - i * 0.05,
                "hybrid_score": 1.0 - i * 0.05,
                "text": text or f"Document {i}: {'enterprise RAG' if i % 2 == 0 else 'data engineering PySpark'} pipeline.",
                "metadata": {},
            }
            for i in range(n)
        ]

    def test_empty_candidates(self, retriever):
        """TC-MMR-001: Empty candidates returns []."""
        result = retriever._mmr_filtering([], "test query", top_k=5)
        assert result == []

    def test_fewer_candidates_than_top_k(self, retriever):
        """TC-MMR-002: Fewer candidates than top_k returns all candidates."""
        docs = self._make_docs(3)
        result = retriever._mmr_filtering(docs, "test query", top_k=5)
        assert len(result) == 3

    def test_exact_top_k(self, retriever):
        """TC-MMR-003: Exactly top_k candidates returns all."""
        docs = self._make_docs(5)
        result = retriever._mmr_filtering(docs, "test query", top_k=5)
        assert len(result) == 5

    def test_more_candidates_than_top_k(self, retriever):
        """TC-MMR-004: More candidates than top_k returns exactly top_k."""
        docs = self._make_docs(15)
        result = retriever._mmr_filtering(docs, "test query", top_k=5)
        assert len(result) == 5

    def test_mmr_rank_assigned(self, retriever):
        """TC-MMR-005: All returned documents have mmr_rank field."""
        docs = self._make_docs(10)
        result = retriever._mmr_filtering(docs, "test query", top_k=5)
        assert all("mmr_rank" in r for r in result)

    def test_identical_candidates(self, retriever):
        """TC-MMR-006: Identical candidates are handled without error."""
        docs = self._make_docs(10, identical=True)
        result = retriever._mmr_filtering(docs, "test query", top_k=5)
        assert len(result) <= 5

    def test_empty_text_candidates(self, retriever):
        """TC-MMR-007: Candidates with empty text use zero vectors (no crash)."""
        docs = [
            {"id": f"doc_{i}", "hybrid_score": 0.9, "text": "", "metadata": {}}
            for i in range(10)
        ]
        result = retriever._mmr_filtering(docs, "test query", top_k=3)
        assert isinstance(result, list)

    def test_lambda_zero_maximises_diversity(self, retriever):
        """TC-MMR-008: lambda=0 emphasises diversity (no crash)."""
        docs = self._make_docs(10)
        result = retriever._mmr_filtering(docs, "test query", top_k=5, lambda_param=0.0)
        assert len(result) <= 5
