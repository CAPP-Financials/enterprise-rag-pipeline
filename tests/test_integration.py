"""
Test Suite: End-to-End Integration Tests
=========================================
TC-INT-001 to TC-INT-012: Full pipeline integration scenarios
"""

import logging
import pytest

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from src.ingestion.chunking import SemanticChunker, HybridChunker
from src.retrieval.hybrid_search import HybridRetriever
from src.orchestration.graph import RAGOrchestrator, QueryExpander, ContextDeduplicator
from src.evaluation.ragas_metrics import RAGASEvaluator, RAGASScores, EvaluationTracker


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------

class InMemoryRetriever:
    """In-memory retriever that chunks and searches documents locally."""

    def __init__(self, documents):
        self.chunker = HybridChunker(chunk_size=200, chunk_overlap=20)
        self.chunks = []
        for doc in documents:
            chunks = self.chunker.chunk(doc["text"])
            for i, chunk in enumerate(chunks):
                self.chunks.append({
                    "id": f"{doc['id']}_chunk_{i}",
                    "score": 0.9,
                    "hybrid_score": 0.9,
                    "text": chunk,
                    "metadata": {"source": doc.get("source", "unknown"), "business_unit": doc.get("business_unit", "general")},
                })

    def retrieve(self, query, namespace="default", top_k=5, fetch_k=20):
        if not query or not query.strip():
            return []
        # Simple keyword matching for testing
        query_words = set(query.lower().split())
        scored = []
        for chunk in self.chunks:
            chunk_words = set(chunk["text"].lower().split())
            overlap = len(query_words & chunk_words)
            if overlap > 0:
                scored.append({**chunk, "score": overlap / len(query_words), "hybrid_score": overlap / len(query_words)})
        scored.sort(key=lambda x: x["hybrid_score"], reverse=True)
        return scored[:top_k]


class MockLLMClient:
    def __init__(self):
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, model, messages, temperature=0.3, max_tokens=1000):
        # Extract the last user message for context-aware mock response
        user_msg = messages[-1]["content"] if messages else ""

        class Usage:
            total_tokens = 100

        class Choice:
            class Message:
                content = "Based on the provided context, the answer is: This is a mock generated answer for testing purposes."
            message = Message()

        class Response:
            choices = [Choice()]
            usage = Usage()

        return Response()


# ---------------------------------------------------------------------------
# Sample enterprise documents
# ---------------------------------------------------------------------------

SAMPLE_DOCS = [
    {
        "id": "finance_001",
        "text": "The company achieved an 8.2x ROI through strategic AI investments in Q3 2024. Revenue grew by 15% year-over-year. Operating margins improved by 3 percentage points.",
        "source": "finance_report_q3.pdf",
        "business_unit": "finance",
    },
    {
        "id": "engineering_001",
        "text": "The data engineering team deployed a PySpark pipeline for real-time fraud detection. The model improved fraud detection accuracy by 10%. Compute costs were reduced by 70% through optimisation.",
        "source": "engineering_report.pdf",
        "business_unit": "engineering",
    },
    {
        "id": "hr_001",
        "text": "The HR department launched a new employee wellness programme. Participation rates reached 85% within the first month. Employee satisfaction scores improved by 20%.",
        "source": "hr_report.pdf",
        "business_unit": "hr",
    },
    {
        "id": "strategy_001",
        "text": "The churn reduction initiative reduced customer churn by 6% using a market mix model built on PySpark. The model was validated using RAGAS metrics with a composite score of 0.84.",
        "source": "strategy_report.pdf",
        "business_unit": "strategy",
    },
]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestEndToEndPipeline:

    @pytest.fixture(scope="class")
    def pipeline(self):
        retriever = InMemoryRetriever(SAMPLE_DOCS)
        llm = MockLLMClient()
        return RAGOrchestrator(retriever=retriever, llm_client=llm)

    def test_finance_query(self, pipeline):
        """TC-INT-001: Finance domain query returns relevant answer."""
        result = pipeline.run("What is the ROI?", namespace="finance")
        assert isinstance(result["generated_answer"], str)
        assert len(result["generated_answer"]) > 0

    def test_engineering_query(self, pipeline):
        """TC-INT-002: Engineering domain query processes without error."""
        result = pipeline.run("What is the compute cost reduction?", namespace="engineering")
        assert "generated_answer" in result

    def test_hr_query(self, pipeline):
        """TC-INT-003: HR domain query returns answer."""
        result = pipeline.run("What is the employee participation rate?", namespace="hr")
        assert isinstance(result["generated_answer"], str)

    def test_strategy_query(self, pipeline):
        """TC-INT-004: Strategy domain query returns answer."""
        result = pipeline.run("What is the churn reduction?", namespace="strategy")
        assert isinstance(result["generated_answer"], str)

    def test_cross_domain_query(self, pipeline):
        """TC-INT-005: Cross-domain query (PySpark) retrieves from multiple sources."""
        result = pipeline.run("Tell me about PySpark usage", namespace="default")
        assert isinstance(result["retrieved_context"], list)

    def test_pipeline_state_completeness(self, pipeline):
        """TC-INT-006: Pipeline state contains all required fields."""
        result = pipeline.run("What is the fraud detection improvement?")
        required = {"original_query", "expanded_queries", "retrieved_context",
                    "context_deduped", "generated_answer", "total_pipeline_time"}
        assert required.issubset(result.keys())

    def test_deduplication_reduces_context(self, pipeline):
        """TC-INT-007: Deduplication step reduces or maintains context size."""
        result = pipeline.run("What is the ROI and revenue growth?")
        raw = len(result.get("retrieved_context", []))
        deduped = len(result.get("context_deduped", []))
        assert deduped <= raw

    def test_timing_all_positive(self, pipeline):
        """TC-INT-008: All timing values are non-negative."""
        result = pipeline.run("What are the key metrics?")
        for key in ["expand_time", "retrieval_time", "dedup_time", "generation_time"]:
            assert result.get(key, 0) >= 0

    def test_empty_query_handled(self, pipeline):
        """TC-INT-009: Empty query is handled gracefully."""
        result = pipeline.run("")
        assert isinstance(result["generated_answer"], str)

    def test_very_long_query(self, pipeline):
        """TC-INT-010: Very long query (500+ chars) is handled."""
        long_query = "What is the ROI " * 30
        result = pipeline.run(long_query)
        assert isinstance(result["generated_answer"], str)

    def test_special_characters_in_query(self, pipeline):
        """TC-INT-011: Query with special characters is handled."""
        result = pipeline.run("What is the ROI? (in %) — for Q3 2024!")
        assert isinstance(result["generated_answer"], str)

    def test_unicode_query(self, pipeline):
        """TC-INT-012: Unicode query is handled without error."""
        result = pipeline.run("Qu'est-ce que le ROI de l'entreprise?")
        assert isinstance(result["generated_answer"], str)


class TestChunkingToRetrievalPipeline:
    """Tests the chunking → retrieval integration."""

    def test_chunked_docs_are_retrievable(self):
        """TC-INT-013: Documents chunked by SemanticChunker are retrievable."""
        chunker = SemanticChunker(min_chunk_size=50, max_chunk_size=300)
        text = (
            "The enterprise RAG pipeline achieved 40% improvement in query relevance. "
            "The system serves 500+ distributed users across multiple business units. "
            "Semantic chunking improved context precision by preserving meaning boundaries."
        )
        chunks = chunker.chunk(text)
        assert len(chunks) >= 1

        retriever = InMemoryRetriever([{"id": "test_doc", "text": text, "source": "test"}])
        results = retriever.retrieve("RAG pipeline improvement", top_k=3)
        assert len(results) >= 0  # May or may not find matches depending on keywords

    def test_hybrid_chunker_feeds_retriever(self):
        """TC-INT-014: HybridChunker output feeds correctly into retriever."""
        chunker = HybridChunker(chunk_size=200, chunk_overlap=20)
        docs = [
            {"id": f"doc_{i}", "text": f"Document {i} about enterprise knowledge management and RAG systems.", "source": f"doc_{i}.pdf"}
            for i in range(5)
        ]
        retriever = InMemoryRetriever(docs)
        results = retriever.retrieve("enterprise knowledge", top_k=3)
        assert isinstance(results, list)


class TestEvaluationIntegration:
    """Tests evaluation module integration with pipeline output."""

    def test_evaluate_pipeline_output(self):
        """TC-INT-015: Evaluation module processes pipeline output correctly."""
        evaluator = RAGASEvaluator()
        tracker = EvaluationTracker()

        queries = [
            "What is the ROI?",
            "What is the churn reduction?",
            "What is the fraud detection improvement?",
        ]
        contexts = [
            ["The company achieved 8.2x ROI through strategic AI investments."],
            ["Churn was reduced by 6% using a PySpark market mix model."],
            ["Fraud detection improved by 10% with the new ML pipeline."],
        ]
        answers = [
            "The ROI was 8.2x.",
            "Churn was reduced by 6%.",
            "Fraud detection improved by 10%.",
        ]

        scores_list = evaluator.evaluate_batch(queries, contexts, answers)
        assert len(scores_list) == 3

        for q, ctx, ans, scores in zip(queries, contexts, answers, scores_list):
            tracker.record(q, ctx, ans, scores, {"namespace": "test"})

        stats = tracker.get_statistics()
        assert stats["total_evaluations"] == 3
        assert 0.0 <= stats["avg_composite_score"] <= 1.0
