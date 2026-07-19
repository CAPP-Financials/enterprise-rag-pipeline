"""
Test Suite: RAGAS Evaluation Module
=====================================
TC-EVAL-001 to TC-EVAL-015  : RAGASEvaluator edge cases
TC-SCORE-001 to TC-SCORE-006 : RAGASScores data class
TC-TRACK-001 to TC-TRACK-006 : EvaluationTracker
"""

import logging
import os
import pytest
import tempfile

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from src.evaluation.ragas_metrics import RAGASScores, RAGASEvaluator, EvaluationTracker


# ---------------------------------------------------------------------------
# RAGASScores
# ---------------------------------------------------------------------------

class TestRAGASScores:

    def test_valid_scores(self):
        """TC-SCORE-001: Valid scores are stored and composite is average."""
        s = RAGASScores(0.8, 0.9, 0.7, 0.85)
        assert abs(s.composite_score - (0.8 + 0.9 + 0.7 + 0.85) / 4) < 1e-6

    def test_scores_clamped_above_one(self):
        """TC-SCORE-002: Scores > 1.0 are clamped to 1.0."""
        s = RAGASScores(1.5, 2.0, 0.9, 1.1)
        assert s.context_relevance == 1.0
        assert s.faithfulness == 1.0
        assert s.context_precision == 1.0

    def test_scores_clamped_below_zero(self):
        """TC-SCORE-003: Scores < 0.0 are clamped to 0.0."""
        s = RAGASScores(-0.5, -1.0, 0.5, -0.1)
        assert s.context_relevance == 0.0
        assert s.faithfulness == 0.0
        assert s.context_precision == 0.0

    def test_nan_replaced_with_zero(self):
        """TC-SCORE-004: NaN scores are replaced with 0.0."""
        import math
        s = RAGASScores(float("nan"), 0.5, 0.5, 0.5)
        assert s.context_relevance == 0.0

    def test_to_dict_has_all_keys(self):
        """TC-SCORE-005: to_dict() contains all required keys."""
        s = RAGASScores(0.7, 0.8, 0.75, 0.9)
        d = s.to_dict()
        required_keys = {"context_relevance", "faithfulness", "answer_relevance",
                         "context_precision", "composite_score"}
        assert required_keys.issubset(d.keys())

    def test_zero_scores(self):
        """TC-SCORE-006: All-zero scores produce composite of 0.0."""
        s = RAGASScores(0.0, 0.0, 0.0, 0.0)
        assert s.composite_score == 0.0


# ---------------------------------------------------------------------------
# RAGASEvaluator
# ---------------------------------------------------------------------------

class TestRAGASEvaluator:

    @pytest.fixture(scope="class")
    def evaluator(self):
        return RAGASEvaluator()

    def test_init_without_llm(self, evaluator):
        """TC-EVAL-001: Evaluator initialises without LLM client."""
        assert evaluator is not None

    def test_empty_query(self, evaluator):
        """TC-EVAL-002: Empty query returns zero scores."""
        scores = evaluator.evaluate_single("", ["some context"], "some answer")
        assert scores.composite_score == 0.0

    def test_empty_answer(self, evaluator):
        """TC-EVAL-003: Empty answer returns zero scores."""
        scores = evaluator.evaluate_single("What is RAG?", ["context"], "")
        assert scores.composite_score == 0.0

    def test_empty_context(self, evaluator):
        """TC-EVAL-004: Empty context list returns zero scores."""
        scores = evaluator.evaluate_single("What is RAG?", [], "RAG is retrieval-augmented generation.")
        assert scores.composite_score == 0.0

    def test_whitespace_query(self, evaluator):
        """TC-EVAL-005: Whitespace-only query returns zero scores."""
        scores = evaluator.evaluate_single("   ", ["context"], "answer")
        assert scores.composite_score == 0.0

    def test_returns_ragas_scores_type(self, evaluator):
        """TC-EVAL-006: evaluate_single always returns RAGASScores instance."""
        scores = evaluator.evaluate_single("test query", ["context text"], "test answer")
        assert isinstance(scores, RAGASScores)

    def test_scores_in_valid_range(self, evaluator):
        """TC-EVAL-007: All scores are in [0, 1] range."""
        scores = evaluator.evaluate_single(
            "What is the ROI?",
            ["The ROI was 8.2x as measured by revenue growth."],
            "The ROI was 8.2x."
        )
        assert 0.0 <= scores.context_relevance <= 1.0
        assert 0.0 <= scores.faithfulness <= 1.0
        assert 0.0 <= scores.answer_relevance <= 1.0
        assert 0.0 <= scores.context_precision <= 1.0

    def test_batch_length_mismatch(self, evaluator):
        """TC-EVAL-008: Mismatched batch lengths raise ValueError."""
        with pytest.raises(ValueError, match="Length mismatch"):
            evaluator.evaluate_batch(
                ["q1", "q2"],
                [["ctx1"]],  # Only 1 context for 2 queries
                ["a1", "a2"]
            )

    def test_batch_empty_input(self, evaluator):
        """TC-EVAL-009: Empty batch returns []."""
        result = evaluator.evaluate_batch([], [], [])
        assert result == []

    def test_batch_single_item(self, evaluator):
        """TC-EVAL-010: Single-item batch returns list of one RAGASScores."""
        result = evaluator.evaluate_batch(
            ["What is PySpark?"],
            [["PySpark is a Python API for Apache Spark."]],
            ["PySpark is a Python interface for Spark."]
        )
        assert len(result) == 1
        assert isinstance(result[0], RAGASScores)

    def test_batch_multiple_items(self, evaluator):
        """TC-EVAL-011: Multi-item batch returns correct number of scores."""
        queries = ["What is RAG?", "What is MMR?", "What is BM25?"]
        contexts = [["RAG context"], ["MMR context"], ["BM25 context"]]
        answers = ["RAG answer", "MMR answer", "BM25 answer"]
        result = evaluator.evaluate_batch(queries, contexts, answers)
        assert len(result) == 3

    def test_get_evaluation_report_empty(self, evaluator):
        """TC-EVAL-012: Empty scores list returns report with zeros."""
        report = evaluator.get_evaluation_report([])
        assert report["num_queries"] == 0

    def test_get_evaluation_report_single(self, evaluator):
        """TC-EVAL-013: Single score produces valid report."""
        scores = [RAGASScores(0.8, 0.9, 0.7, 0.85)]
        report = evaluator.get_evaluation_report(scores)
        assert report["num_queries"] == 1
        assert abs(report["avg_composite_score"] - scores[0].composite_score) < 1e-6

    def test_get_evaluation_report_multiple(self, evaluator):
        """TC-EVAL-014: Multiple scores produce correct averages."""
        scores = [
            RAGASScores(0.8, 0.9, 0.7, 0.85),
            RAGASScores(0.6, 0.7, 0.65, 0.75),
        ]
        report = evaluator.get_evaluation_report(scores)
        assert report["num_queries"] == 2
        expected_avg = sum(s.composite_score for s in scores) / 2
        assert abs(report["avg_composite_score"] - expected_avg) < 1e-6

    def test_context_with_multiple_chunks(self, evaluator):
        """TC-EVAL-015: Context with multiple chunks is handled correctly."""
        scores = evaluator.evaluate_single(
            "What is the churn reduction?",
            [
                "The company reduced churn by 6% using a PySpark market mix model.",
                "The model was deployed in Q2 2024 and monitored weekly.",
                "ROI from the churn reduction initiative was 8.2x.",
            ],
            "Churn was reduced by 6%."
        )
        assert isinstance(scores, RAGASScores)


# ---------------------------------------------------------------------------
# EvaluationTracker
# ---------------------------------------------------------------------------

class TestEvaluationTracker:

    @pytest.fixture
    def tracker(self):
        return EvaluationTracker()

    def test_init_empty(self, tracker):
        """TC-TRACK-001: Fresh tracker has no evaluations."""
        assert len(tracker.evaluations) == 0

    def test_record_single(self, tracker):
        """TC-TRACK-002: Recording one evaluation stores it correctly."""
        scores = RAGASScores(0.8, 0.9, 0.7, 0.85)
        tracker.record("test query", ["context"], "answer", scores)
        assert len(tracker.evaluations) == 1

    def test_get_statistics_empty(self, tracker):
        """TC-TRACK-003: Statistics on empty tracker returns empty dict."""
        assert tracker.get_statistics() == {}

    def test_get_statistics_populated(self, tracker):
        """TC-TRACK-004: Statistics on populated tracker returns correct values."""
        scores = RAGASScores(0.8, 0.9, 0.7, 0.85)
        tracker.record("q1", ["ctx"], "ans", scores, {"user_id": "u1"})
        stats = tracker.get_statistics()
        assert stats["total_evaluations"] == 1
        assert abs(stats["avg_composite_score"] - scores.composite_score) < 1e-6

    def test_export_to_csv_empty(self, tracker):
        """TC-TRACK-005: Export with no evaluations creates CSV with headers only."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = f.name
        tracker.export_to_csv(path)
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 1  # header only
        assert "query" in lines[0]
        os.unlink(path)

    def test_export_to_csv_with_data(self, tracker):
        """TC-TRACK-006: Export with data creates correct CSV rows."""
        scores = RAGASScores(0.8, 0.9, 0.7, 0.85)
        tracker.record("What is ROI?", ["context"], "8.2x", scores, {"user_id": "u1", "namespace": "finance"})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = f.name
        tracker.export_to_csv(path)
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 2  # header + 1 data row
        assert "What is ROI?" in lines[1]
        os.unlink(path)
