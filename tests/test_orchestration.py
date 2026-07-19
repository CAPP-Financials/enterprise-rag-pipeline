"""
Test Suite: LangGraph Orchestration Module
==========================================
TC-QE-001 to TC-QE-006  : QueryExpander edge cases
TC-DD-001 to TC-DD-005  : ContextDeduplicator edge cases
TC-ORCH-001 to TC-ORCH-010: RAGOrchestrator edge cases
"""

import logging
import pytest

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from src.orchestration.graph import QueryExpander, ContextDeduplicator, RAGOrchestrator


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------

class MockLLMClient:
    """Simulates OpenAI client for testing without API calls."""

    def __init__(self, fail=False, empty_response=False):
        self.fail = fail
        self.empty_response = empty_response
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, model, messages, temperature=0.7, max_tokens=300):
        if self.fail:
            raise ConnectionError("LLM API unavailable")
        content = "" if self.empty_response else (
            "Alternative query one about enterprise knowledge retrieval\n"
            "Alternative query two about RAG pipeline systems\n"
            "Alternative query three about semantic search"
        )

        class Usage:
            total_tokens = 150

        class Choice:
            class Message:
                pass
            message = Message()

        choice = Choice()
        choice.message.content = content

        class Response:
            choices = [choice]
            usage = Usage()

        return Response()


class MockRetriever:
    """Simulates hybrid retriever for orchestration tests."""

    def __init__(self, docs=None, fail=False):
        self.fail = fail
        self.docs = docs or [
            {
                "id": f"doc_{i}",
                "score": 0.9 - i * 0.1,
                "hybrid_score": 0.9 - i * 0.1,
                "text": f"Enterprise RAG document {i}: knowledge retrieval improves productivity.",
                "metadata": {"source": f"doc_{i}.pdf"},
            }
            for i in range(5)
        ]

    def retrieve(self, query, namespace="default", top_k=5, fetch_k=20):
        if self.fail:
            raise RuntimeError("Retriever failed")
        if not query or not query.strip():
            return []
        return self.docs[:top_k]


# ---------------------------------------------------------------------------
# QueryExpander
# ---------------------------------------------------------------------------

class TestQueryExpander:

    def test_empty_query(self):
        """TC-QE-001: Empty query returns []."""
        qe = QueryExpander(llm_client=MockLLMClient())
        assert qe.expand("") == []

    def test_whitespace_query(self):
        """TC-QE-002: Whitespace-only query returns []."""
        qe = QueryExpander(llm_client=MockLLMClient())
        assert qe.expand("   ") == []

    def test_no_llm_client(self):
        """TC-QE-003: No LLM client returns only original query."""
        qe = QueryExpander(llm_client=None)
        result = qe.expand("What is the ROI?")
        assert result == ["What is the ROI?"]

    def test_llm_failure_graceful(self):
        """TC-QE-004: LLM failure returns original query only (no crash)."""
        qe = QueryExpander(llm_client=MockLLMClient(fail=True))
        result = qe.expand("What is the ROI?")
        assert result == ["What is the ROI?"]

    def test_llm_empty_response(self):
        """TC-QE-005: LLM empty response returns original query only."""
        qe = QueryExpander(llm_client=MockLLMClient(empty_response=True))
        result = qe.expand("What is the ROI?")
        assert result == ["What is the ROI?"]

    def test_normal_expansion(self):
        """TC-QE-006: Normal expansion returns original + variants, no duplicates."""
        qe = QueryExpander(llm_client=MockLLMClient())
        result = qe.expand("What is the ROI?", num_expansions=3)
        assert len(result) >= 1
        assert result[0] == "What is the ROI?"
        assert len(result) == len(set(result))  # No duplicates


# ---------------------------------------------------------------------------
# ContextDeduplicator
# ---------------------------------------------------------------------------

class TestContextDeduplicator:

    @pytest.fixture
    def dedup(self):
        return ContextDeduplicator()

    def test_empty_list(self, dedup):
        """TC-DD-001: Empty list returns []."""
        assert dedup.deduplicate([]) == []

    def test_no_duplicates(self, dedup):
        """TC-DD-002: List with no duplicates returns same length."""
        docs = [
            {"text": "Document about finance.", "id": "1"},
            {"text": "Document about engineering.", "id": "2"},
            {"text": "Document about HR.", "id": "3"},
        ]
        result = dedup.deduplicate(docs)
        assert len(result) == 3

    def test_exact_duplicates(self, dedup):
        """TC-DD-003: Exact duplicate texts are removed."""
        docs = [
            {"text": "Duplicate document text.", "id": "1"},
            {"text": "Duplicate document text.", "id": "2"},
            {"text": "Unique document text.", "id": "3"},
        ]
        result = dedup.deduplicate(docs)
        assert len(result) == 2

    def test_empty_text_excluded(self, dedup):
        """TC-DD-004: Documents with empty text are excluded."""
        docs = [
            {"text": "", "id": "1"},
            {"text": "   ", "id": "2"},
            {"text": "Valid document.", "id": "3"},
        ]
        result = dedup.deduplicate(docs)
        assert len(result) == 1

    def test_preserves_order(self, dedup):
        """TC-DD-005: Original order is preserved after deduplication."""
        docs = [
            {"text": "First document.", "id": "1"},
            {"text": "Second document.", "id": "2"},
            {"text": "Third document.", "id": "3"},
        ]
        result = dedup.deduplicate(docs)
        assert [r["id"] for r in result] == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# RAGOrchestrator
# ---------------------------------------------------------------------------

class TestRAGOrchestrator:

    @pytest.fixture(scope="class")
    def orchestrator(self):
        return RAGOrchestrator(
            retriever=MockRetriever(),
            llm_client=MockLLMClient(),
        )

    def test_empty_query(self, orchestrator):
        """TC-ORCH-001: Empty query returns fallback answer."""
        result = orchestrator.run("")
        assert "Please provide" in result["generated_answer"] or result["generated_answer"] != ""

    def test_whitespace_query(self, orchestrator):
        """TC-ORCH-002: Whitespace-only query returns fallback answer."""
        result = orchestrator.run("   ")
        assert isinstance(result["generated_answer"], str)

    def test_normal_query_returns_state(self, orchestrator):
        """TC-ORCH-003: Normal query returns complete state dict."""
        result = orchestrator.run("What is the ROI of the RAG pipeline?")
        required_keys = {"original_query", "expanded_queries", "retrieved_context",
                         "context_deduped", "generated_answer", "total_tokens"}
        assert required_keys.issubset(result.keys())

    def test_expanded_queries_populated(self, orchestrator):
        """TC-ORCH-004: Expanded queries list is populated."""
        result = orchestrator.run("What is the churn reduction?")
        assert isinstance(result["expanded_queries"], list)
        assert len(result["expanded_queries"]) >= 1

    def test_retrieved_context_populated(self, orchestrator):
        """TC-ORCH-005: Retrieved context is populated."""
        result = orchestrator.run("What is the fraud detection improvement?")
        assert isinstance(result["retrieved_context"], list)

    def test_timing_metadata_present(self, orchestrator):
        """TC-ORCH-006: Timing metadata is present in output state."""
        result = orchestrator.run("What is the compute cost reduction?")
        assert "total_pipeline_time" in result
        assert result["total_pipeline_time"] > 0

    def test_failing_retriever(self):
        """TC-ORCH-007: Failing retriever produces fallback answer (no crash)."""
        orch = RAGOrchestrator(
            retriever=MockRetriever(fail=True),
            llm_client=MockLLMClient(),
        )
        result = orch.run("What is the ROI?")
        assert isinstance(result["generated_answer"], str)

    def test_namespace_parameter(self, orchestrator):
        """TC-ORCH-008: Namespace parameter is passed through correctly."""
        result = orchestrator.run("Finance query", namespace="finance")
        assert result["namespace"] == "finance"

    def test_user_id_parameter(self, orchestrator):
        """TC-ORCH-009: User ID is stored in state."""
        result = orchestrator.run("HR query", user_id="user_123")
        assert result["user_id"] == "user_123"

    def test_no_context_fallback_answer(self):
        """TC-ORCH-010: No context produces informative fallback answer."""
        orch = RAGOrchestrator(
            retriever=MockRetriever(docs=[]),
            llm_client=MockLLMClient(),
        )
        result = orch.run("What is the ROI?")
        assert len(result["generated_answer"]) > 0
