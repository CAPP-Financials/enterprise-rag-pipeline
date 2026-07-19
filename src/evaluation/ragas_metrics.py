"""
RAGAS Evaluation Framework
==========================

Implements RAGAS metrics for evaluating RAG pipeline quality:
- Context Relevance  : Are retrieved chunks relevant to the query?
- Faithfulness       : Is the answer grounded in the retrieved context?
- Answer Relevance   : Does the answer address the query?
- Context Precision  : Are the most relevant documents ranked highest?

Compatibility:
- RAGAS 0.4.x (current): uses old-style metric singletons with llm_factory
- RAGAS 0.1.x (legacy): uses ragas.metrics module-level instances
- Graceful fallback to zero scores if RAGAS is unavailable

Edge cases handled:
- RAGAS API version differences (0.1.x vs 0.4.x)
- Empty context list
- Empty answer string
- Empty query string
- Mismatched lengths in batch evaluation
- NaN/Inf scores from RAGAS (replaced with 0.0)
- RAGAS evaluation failure (returns zero scores, logs error)
- CSV export with no evaluations
- RAGAS analytics batcher teardown noise (suppressed)
"""

import csv
import logging
import math
import os
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RAGAS import with version compatibility
# ---------------------------------------------------------------------------
_RAGAS_AVAILABLE = False
_RAGAS_VERSION = "unknown"
_RAGAS_API = "none"

try:
    import ragas
    _RAGAS_VERSION = getattr(ragas, "__version__", "unknown")
    logger.info("RAGAS version detected: %s", _RAGAS_VERSION)

    # RAGAS 0.4.x API — use old-style metric singletons with llm_factory
    try:
        from ragas.metrics._faithfulness import faithfulness as _faithfulness_metric
        from ragas.metrics._answer_relevance import answer_relevancy as _answer_relevancy_metric
        from ragas import evaluate as _ragas_evaluate, EvaluationDataset as _EvaluationDataset
        from ragas.dataset_schema import SingleTurnSample as _SingleTurnSample
        _RAGAS_AVAILABLE = True
        _RAGAS_API = "v0.4"
        logger.info("RAGAS v0.4.x API loaded (faithfulness + answer_relevancy via old-style singletons)")
    except ImportError as exc:
        logger.warning("RAGAS v0.4.x import failed: %s; trying legacy API", exc)
        # RAGAS 0.1.x / 0.2.x legacy API
        try:
            from ragas.metrics import (
                context_relevancy as _ctx_rel,
                faithfulness as _faithfulness_metric,
                answer_relevancy as _answer_relevancy_metric,
                context_precision as _ctx_prec,
            )
            from ragas import evaluate as _ragas_evaluate
            from datasets import Dataset as _LegacyDataset
            _RAGAS_AVAILABLE = True
            _RAGAS_API = "v0.1"
            logger.info("RAGAS v0.1.x API loaded")
        except ImportError as exc2:
            logger.warning("RAGAS metrics import failed: %s; evaluation will use mock scores", exc2)

except ImportError:
    logger.warning("ragas package not installed; evaluation will use mock scores")


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float, replacing NaN/None/Inf with default."""
    try:
        f = float(value)
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RAGASScores:
    """Container for RAGAS evaluation scores, all clamped to [0, 1]."""

    context_relevance: float = 0.0
    faithfulness: float = 0.0
    answer_relevance: float = 0.0
    context_precision: float = 0.0

    def __post_init__(self):
        # Clamp all scores to [0, 1] and sanitise NaN/Inf
        self.context_relevance = max(0.0, min(1.0, _safe_float(self.context_relevance)))
        self.faithfulness = max(0.0, min(1.0, _safe_float(self.faithfulness)))
        self.answer_relevance = max(0.0, min(1.0, _safe_float(self.answer_relevance)))
        self.context_precision = max(0.0, min(1.0, _safe_float(self.context_precision)))

    @property
    def composite_score(self) -> float:
        """Weighted average of all four metrics."""
        return (
            self.context_relevance
            + self.faithfulness
            + self.answer_relevance
            + self.context_precision
        ) / 4.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "context_relevance": self.context_relevance,
            "faithfulness": self.faithfulness,
            "answer_relevance": self.answer_relevance,
            "context_precision": self.context_precision,
            "composite_score": self.composite_score,
        }


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class RAGASEvaluator:
    """
    Evaluates RAG pipeline output using RAGAS metrics.

    Falls back to mock scores (all 0.0) if RAGAS is not available,
    logging a clear warning so the user knows evaluation is degraded.

    When RAGAS is available, uses:
    - Faithfulness      : LLM-based grounding check
    - Answer Relevancy  : Embedding-based query alignment
    - Context Relevance : Proxy via faithfulness score (no reference needed)
    - Context Precision : Proxy via answer relevancy score (no reference needed)
    """

    def __init__(self, llm_client=None, model: str = "gpt-5-mini"):
        """
        Initialise RAGAS evaluator.

        Args:
            llm_client: Optional pre-built OpenAI client. If None, one is
                        created from OPENAI_API_KEY / OPENAI_API_BASE env vars.
            model     : LLM model name for RAGAS evaluation (default: gpt-5-mini).
        """
        self.llm_client = llm_client
        self.model = model
        self._ragas_llm = None
        self._ragas_emb = None

        if not _RAGAS_AVAILABLE:
            logger.warning(
                "RAGASEvaluator: RAGAS not available; all scores will be 0.0. "
                "Install with: pip install ragas"
            )
        else:
            logger.info("RAGASEvaluator ready (RAGAS v%s, API=%s, model=%s)",
                        _RAGAS_VERSION, _RAGAS_API, model)

    def _get_ragas_llm(self):
        """Lazily initialise RAGAS LLM wrapper."""
        if self._ragas_llm is not None:
            return self._ragas_llm
        from openai import OpenAI
        from ragas.llms import llm_factory
        client = self.llm_client or OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY", "placeholder"),
            base_url=os.environ.get("OPENAI_API_BASE") or None,
        )
        self._ragas_llm = llm_factory(self.model, client=client)
        logger.debug("RAGAS LLM initialised: %s", type(self._ragas_llm).__name__)
        return self._ragas_llm

    def _get_ragas_emb(self):
        """Lazily initialise RAGAS embeddings wrapper."""
        if self._ragas_emb is not None:
            return self._ragas_emb
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from ragas.embeddings.base import LangchainEmbeddingsWrapper
            from langchain_huggingface import HuggingFaceEmbeddings
        self._ragas_emb = LangchainEmbeddingsWrapper(
            HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        )
        logger.debug("RAGAS embeddings initialised: HuggingFace all-MiniLM-L6-v2")
        return self._ragas_emb

    def _zero_scores(self) -> "RAGASScores":
        return RAGASScores(0.0, 0.0, 0.0, 0.0)

    def evaluate_single(
        self,
        query: str,
        context: List[str],
        answer: str,
    ) -> "RAGASScores":
        """
        Evaluate a single query-context-answer triple.

        Args:
            query  : User query string.
            context: List of retrieved context strings.
            answer : Generated answer string.

        Returns:
            RAGASScores object with all metrics clamped to [0, 1].
        """
        # --- Input guards ---
        if not query or not query.strip():
            logger.warning("evaluate_single: empty query; returning zero scores")
            return self._zero_scores()
        if not answer or not answer.strip():
            logger.warning("evaluate_single: empty answer; returning zero scores")
            return self._zero_scores()
        if not context:
            logger.warning("evaluate_single: empty context list; returning zero scores")
            return self._zero_scores()

        if not _RAGAS_AVAILABLE:
            logger.warning("evaluate_single: RAGAS unavailable; returning zero scores")
            return self._zero_scores()

        logger.info("evaluate_single: evaluating query='%s...'", query[:60])

        # Filter empty context strings
        clean_context = [c for c in context if c and c.strip()]
        if not clean_context:
            logger.warning("evaluate_single: all context strings are empty; returning zero scores")
            return self._zero_scores()

        try:
            if _RAGAS_API == "v0.4":
                return self._evaluate_v04(query, clean_context, answer)
            else:
                return self._evaluate_legacy(query, clean_context, answer)

        except Exception as exc:
            logger.error("evaluate_single: RAGAS evaluation failed: %s", exc, exc_info=True)
            return self._zero_scores()

    def _evaluate_v04(self, query: str, context: List[str], answer: str) -> "RAGASScores":
        """RAGAS 0.4.x evaluation path using old-style metric singletons."""
        llm = self._get_ragas_llm()
        emb = self._get_ragas_emb()

        # Configure metric singletons with our LLM/embeddings
        _faithfulness_metric.llm = llm
        _answer_relevancy_metric.llm = llm
        _answer_relevancy_metric.embeddings = emb

        sample = _SingleTurnSample(
            user_input=query,
            retrieved_contexts=context,
            response=answer,
        )
        dataset = _EvaluationDataset(samples=[sample])

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = _ragas_evaluate(
                dataset=dataset,
                metrics=[_faithfulness_metric, _answer_relevancy_metric],
            )

        df = results.to_pandas()
        logger.debug("RAGAS 0.4.x result columns: %s", list(df.columns))

        def _get(col: str) -> float:
            try:
                return _safe_float(df[col].iloc[0])
            except Exception:
                return 0.0

        faithfulness_score = _get("faithfulness")
        answer_rel_score = _get("answer_relevancy")

        # Context relevance and precision are proxied from the two LLM-evaluated metrics
        # (no reference document required for these proxies)
        scores = RAGASScores(
            context_relevance=faithfulness_score,      # proxy: grounding ≈ context relevance
            faithfulness=faithfulness_score,
            answer_relevance=answer_rel_score,
            context_precision=answer_rel_score,        # proxy: answer alignment ≈ precision
        )

        logger.info(
            "evaluate_single: composite=%.3f (F=%.3f, AR=%.3f)",
            scores.composite_score, faithfulness_score, answer_rel_score,
        )
        return scores

    def _evaluate_legacy(self, query: str, context: List[str], answer: str) -> "RAGASScores":
        """RAGAS 0.1.x legacy evaluation path."""
        context_joined = "\n\n".join(context)
        eval_data = {
            "question": [query],
            "contexts": [[context_joined]],
            "answer": [answer],
        }
        from datasets import Dataset as _Dataset
        dataset = _Dataset.from_dict(eval_data)
        results = _ragas_evaluate(
            dataset,
            metrics=[_ctx_rel, _faithfulness_metric, _answer_relevancy_metric, _ctx_prec],
        )

        def _get(key: str) -> float:
            try:
                val = results[key]
                if hasattr(val, "__iter__") and not isinstance(val, str):
                    val = list(val)[0]
                return _safe_float(val)
            except Exception:
                return 0.0

        scores = RAGASScores(
            context_relevance=_get("context_relevancy"),
            faithfulness=_get("faithfulness"),
            answer_relevance=_get("answer_relevancy"),
            context_precision=_get("context_precision"),
        )
        logger.info(
            "evaluate_single (legacy): composite=%.3f (CR=%.3f, F=%.3f, AR=%.3f, CP=%.3f)",
            scores.composite_score,
            scores.context_relevance,
            scores.faithfulness,
            scores.answer_relevance,
            scores.context_precision,
        )
        return scores

    def evaluate_batch(
        self,
        queries: List[str],
        contexts: List[List[str]],
        answers: List[str],
    ) -> List["RAGASScores"]:
        """
        Evaluate multiple query-context-answer triples.

        Args:
            queries : List of query strings.
            contexts: List of context lists (one per query).
            answers : List of answer strings.

        Returns:
            List of RAGASScores (one per query).

        Raises:
            ValueError: If queries/contexts/answers have different lengths.
        """
        if not (len(queries) == len(contexts) == len(answers)):
            raise ValueError(
                f"Length mismatch: queries={len(queries)}, "
                f"contexts={len(contexts)}, answers={len(answers)}"
            )

        if not queries:
            logger.warning("evaluate_batch: empty input; returning []")
            return []

        logger.info("evaluate_batch: evaluating %d query-answer pairs", len(queries))

        scores_list = []
        for i, (q, ctx, ans) in enumerate(zip(queries, contexts, answers)):
            logger.info("evaluate_batch: item %d/%d", i + 1, len(queries))
            scores_list.append(self.evaluate_single(q, ctx, ans))

        avg = sum(s.composite_score for s in scores_list) / len(scores_list)
        logger.info("evaluate_batch: complete. Average composite score: %.3f", avg)
        return scores_list

    def get_evaluation_report(self, scores: List["RAGASScores"]) -> Dict[str, float]:
        """
        Aggregate evaluation scores into a summary report.

        Args:
            scores: List of RAGASScores objects.

        Returns:
            Dict with per-metric averages and composite score range.
        """
        if not scores:
            logger.warning("get_evaluation_report: empty scores list")
            return {
                "avg_context_relevance": 0.0,
                "avg_faithfulness": 0.0,
                "avg_answer_relevance": 0.0,
                "avg_context_precision": 0.0,
                "avg_composite_score": 0.0,
                "min_composite_score": 0.0,
                "max_composite_score": 0.0,
                "num_queries": 0,
            }

        n = len(scores)
        composites = [s.composite_score for s in scores]

        report = {
            "avg_context_relevance": sum(s.context_relevance for s in scores) / n,
            "avg_faithfulness": sum(s.faithfulness for s in scores) / n,
            "avg_answer_relevance": sum(s.answer_relevance for s in scores) / n,
            "avg_context_precision": sum(s.context_precision for s in scores) / n,
            "avg_composite_score": sum(composites) / n,
            "min_composite_score": min(composites),
            "max_composite_score": max(composites),
            "num_queries": n,
        }

        logger.info(
            "Evaluation Report (%d queries): composite avg=%.3f, min=%.3f, max=%.3f",
            n, report["avg_composite_score"],
            report["min_composite_score"],
            report["max_composite_score"],
        )
        return report


# ---------------------------------------------------------------------------
# Evaluation Tracker
# ---------------------------------------------------------------------------

class EvaluationTracker:
    """
    Tracks evaluation results over time for monitoring and export.

    Edge cases handled:
    - export_to_csv with no evaluations → creates empty CSV with headers only
    - get_statistics with no evaluations → returns zeroed dict with warning
    """

    def __init__(self):
        self.evaluations: List[Dict[str, Any]] = []

    def record(
        self,
        query: str,
        context: List[str],
        answer: str,
        scores: "RAGASScores",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record an evaluation result.

        Args:
            query   : Query that was evaluated.
            context : Retrieved context list.
            answer  : Generated answer.
            scores  : RAGASScores for this evaluation.
            metadata: Optional extra metadata dict.
        """
        entry = {
            "query": query,
            "context": context,
            "answer": answer,
            "scores": scores.to_dict(),
            "metadata": metadata or {},
        }
        self.evaluations.append(entry)
        logger.info(
            "EvaluationTracker: recorded eval #%d | composite=%.3f | query='%s...'",
            len(self.evaluations),
            scores.composite_score,
            query[:40],
        )

    def get_statistics(self) -> Dict[str, Any]:
        """
        Return aggregate statistics across all recorded evaluations.

        Returns:
            Empty dict if no evaluations recorded.
            Dict with total_evaluations, avg/min/max composite scores otherwise.
        """
        if not self.evaluations:
            logger.warning("EvaluationTracker.get_statistics: no evaluations recorded")
            return {}

        scores = [e["scores"] for e in self.evaluations]
        composites = [s["composite_score"] for s in scores]
        n = len(composites)

        stats = {
            "total_evaluations": n,
            "avg_composite_score": sum(composites) / n,
            "min_composite_score": min(composites),
            "max_composite_score": max(composites),
        }
        logger.info(
            "EvaluationTracker stats: %d evals, avg composite=%.3f",
            n, stats["avg_composite_score"],
        )
        return stats

    def export_to_csv(self, filepath: str) -> None:
        """
        Export all recorded evaluations to a CSV file.

        Args:
            filepath: Destination CSV file path.

        Edge cases:
            - Creates file with headers even if no evaluations recorded.
        """
        logger.info(
            "EvaluationTracker.export_to_csv: %d records → %s",
            len(self.evaluations), filepath,
        )
        fieldnames = [
            "query", "answer",
            "context_relevance", "faithfulness",
            "answer_relevance", "context_precision", "composite_score",
        ]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in self.evaluations:
                scores = entry["scores"]
                writer.writerow({
                    "query": entry["query"],
                    "answer": entry["answer"],
                    "context_relevance": scores.get("context_relevance", 0.0),
                    "faithfulness": scores.get("faithfulness", 0.0),
                    "answer_relevance": scores.get("answer_relevance", 0.0),
                    "context_precision": scores.get("context_precision", 0.0),
                    "composite_score": scores.get("composite_score", 0.0),
                })
        logger.info("EvaluationTracker.export_to_csv: export complete")
