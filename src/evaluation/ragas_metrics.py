"""
RAGAS Evaluation Framework

Implements RAGAS metrics for evaluating RAG pipeline quality:
- Context Relevance: How relevant is the retrieved context to the query?
- Faithfulness: Is the generated answer grounded in the context?
- Answer Relevance: Does the answer address the query?
- Context Precision: Are the most relevant documents ranked highest?
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging
from ragas.metrics import (
    context_relevance,
    faithfulness,
    answer_relevance,
    context_precision,
)
from ragas import evaluate
from datasets import Dataset

logger = logging.getLogger(__name__)


@dataclass
class RAGASScores:
    """Container for RAGAS evaluation scores."""
    
    context_relevance: float
    faithfulness: float
    answer_relevance: float
    context_precision: float
    
    @property
    def composite_score(self) -> float:
        """Calculate composite score (average of all metrics)."""
        scores = [
            self.context_relevance,
            self.faithfulness,
            self.answer_relevance,
            self.context_precision,
        ]
        return sum(scores) / len(scores)
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary."""
        return {
            "context_relevance": self.context_relevance,
            "faithfulness": self.faithfulness,
            "answer_relevance": self.answer_relevance,
            "context_precision": self.context_precision,
            "composite_score": self.composite_score,
        }


class RAGASEvaluator:
    """
    Evaluates RAG pipeline using RAGAS metrics.
    
    RAGAS (Retrieval-Augmented Generation Assessment) provides reference-free
    evaluation of RAG systems, measuring the quality of retrieval and generation.
    """
    
    def __init__(self, llm_client=None):
        """
        Initialize RAGAS evaluator.
        
        Args:
            llm_client: Optional LLM client for custom evaluation
        """
        self.llm_client = llm_client
    
    def evaluate_single(
        self,
        query: str,
        context: List[str],
        answer: str,
    ) -> RAGASScores:
        """
        Evaluate a single query-context-answer triple.
        
        Args:
            query: User query
            context: List of retrieved context documents
            answer: Generated answer
            
        Returns:
            RAGASScores object with evaluation results
        """
        logger.info("Evaluating single query-answer pair...")
        
        # Prepare data for RAGAS
        context_str = "\n\n".join(context)
        
        eval_data = {
            "question": [query],
            "contexts": [[context_str]],
            "answer": [answer],
        }
        
        dataset = Dataset.from_dict(eval_data)
        
        try:
            # Run evaluation
            results = evaluate(
                dataset,
                metrics=[
                    context_relevance,
                    faithfulness,
                    answer_relevance,
                    context_precision,
                ],
            )
            
            scores = RAGASScores(
                context_relevance=results["context_relevance"][0],
                faithfulness=results["faithfulness"][0],
                answer_relevance=results["answer_relevance"][0],
                context_precision=results["context_precision"][0],
            )
            
            logger.info(f"Evaluation complete. Composite score: {scores.composite_score:.3f}")
            return scores
            
        except Exception as e:
            logger.error(f"RAGAS evaluation failed: {e}")
            # Return zero scores on failure
            return RAGASScores(
                context_relevance=0.0,
                faithfulness=0.0,
                answer_relevance=0.0,
                context_precision=0.0,
            )
    
    def evaluate_batch(
        self,
        queries: List[str],
        contexts: List[List[str]],
        answers: List[str],
    ) -> List[RAGASScores]:
        """
        Evaluate multiple query-context-answer triples.
        
        Args:
            queries: List of queries
            contexts: List of context lists (one per query)
            answers: List of answers
            
        Returns:
            List of RAGASScores objects
        """
        logger.info(f"Evaluating batch of {len(queries)} queries...")
        
        if not (len(queries) == len(contexts) == len(answers)):
            raise ValueError("Queries, contexts, and answers must have same length")
        
        # Prepare data for RAGAS
        eval_data = {
            "question": queries,
            "contexts": [["\n\n".join(ctx)] for ctx in contexts],
            "answer": answers,
        }
        
        dataset = Dataset.from_dict(eval_data)
        
        try:
            # Run evaluation
            results = evaluate(
                dataset,
                metrics=[
                    context_relevance,
                    faithfulness,
                    answer_relevance,
                    context_precision,
                ],
            )
            
            # Convert results to RAGASScores objects
            scores_list = []
            for i in range(len(queries)):
                scores = RAGASScores(
                    context_relevance=results["context_relevance"][i],
                    faithfulness=results["faithfulness"][i],
                    answer_relevance=results["answer_relevance"][i],
                    context_precision=results["context_precision"][i],
                )
                scores_list.append(scores)
            
            logger.info(f"Batch evaluation complete. Average composite score: {sum(s.composite_score for s in scores_list) / len(scores_list):.3f}")
            return scores_list
            
        except Exception as e:
            logger.error(f"Batch RAGAS evaluation failed: {e}")
            # Return zero scores for all queries on failure
            return [
                RAGASScores(
                    context_relevance=0.0,
                    faithfulness=0.0,
                    answer_relevance=0.0,
                    context_precision=0.0,
                )
                for _ in queries
            ]
    
    def get_evaluation_report(
        self,
        scores: List[RAGASScores],
    ) -> Dict[str, float]:
        """
        Generate evaluation report from scores.
        
        Args:
            scores: List of RAGASScores objects
            
        Returns:
            Dictionary with aggregated metrics
        """
        if not scores:
            return {
                "avg_context_relevance": 0.0,
                "avg_faithfulness": 0.0,
                "avg_answer_relevance": 0.0,
                "avg_context_precision": 0.0,
                "avg_composite_score": 0.0,
                "min_composite_score": 0.0,
                "max_composite_score": 0.0,
            }
        
        context_relevances = [s.context_relevance for s in scores]
        faithfulnesses = [s.faithfulness for s in scores]
        answer_relevances = [s.answer_relevance for s in scores]
        context_precisions = [s.context_precision for s in scores]
        composite_scores = [s.composite_score for s in scores]
        
        report = {
            "avg_context_relevance": sum(context_relevances) / len(context_relevances),
            "avg_faithfulness": sum(faithfulnesses) / len(faithfulnesses),
            "avg_answer_relevance": sum(answer_relevances) / len(answer_relevances),
            "avg_context_precision": sum(context_precisions) / len(context_precisions),
            "avg_composite_score": sum(composite_scores) / len(composite_scores),
            "min_composite_score": min(composite_scores),
            "max_composite_score": max(composite_scores),
            "num_queries": len(scores),
        }
        
        logger.info(f"Evaluation Report:\n{self._format_report(report)}")
        return report
    
    @staticmethod
    def _format_report(report: Dict[str, float]) -> str:
        """Format evaluation report for logging."""
        lines = [
            f"  Context Relevance:    {report['avg_context_relevance']:.3f}",
            f"  Faithfulness:         {report['avg_faithfulness']:.3f}",
            f"  Answer Relevance:     {report['avg_answer_relevance']:.3f}",
            f"  Context Precision:    {report['avg_context_precision']:.3f}",
            f"  Composite Score:      {report['avg_composite_score']:.3f}",
            f"  Score Range:          {report['min_composite_score']:.3f} - {report['max_composite_score']:.3f}",
            f"  Queries Evaluated:    {report['num_queries']}",
        ]
        return "\n".join(lines)


class EvaluationTracker:
    """
    Tracks evaluation metrics over time for monitoring pipeline performance.
    """
    
    def __init__(self):
        """Initialize evaluation tracker."""
        self.evaluations: List[Dict] = []
    
    def record(
        self,
        query: str,
        context: List[str],
        answer: str,
        scores: RAGASScores,
        metadata: Optional[Dict] = None,
    ) -> None:
        """
        Record an evaluation result.
        
        Args:
            query: Query that was evaluated
            context: Context that was retrieved
            answer: Answer that was generated
            scores: RAGAS scores
            metadata: Optional metadata (user_id, namespace, timestamp, etc.)
        """
        record = {
            "query": query,
            "context": context,
            "answer": answer,
            "scores": scores.to_dict(),
            "metadata": metadata or {},
        }
        self.evaluations.append(record)
    
    def get_statistics(self) -> Dict[str, float]:
        """
        Get statistics from recorded evaluations.
        
        Returns:
            Dictionary with aggregated statistics
        """
        if not self.evaluations:
            return {}
        
        composite_scores = [e["scores"]["composite_score"] for e in self.evaluations]
        
        return {
            "total_evaluations": len(self.evaluations),
            "avg_composite_score": sum(composite_scores) / len(composite_scores),
            "min_composite_score": min(composite_scores),
            "max_composite_score": max(composite_scores),
            "avg_context_relevance": sum(e["scores"]["context_relevance"] for e in self.evaluations) / len(self.evaluations),
            "avg_faithfulness": sum(e["scores"]["faithfulness"] for e in self.evaluations) / len(self.evaluations),
            "avg_answer_relevance": sum(e["scores"]["answer_relevance"] for e in self.evaluations) / len(self.evaluations),
            "avg_context_precision": sum(e["scores"]["context_precision"] for e in self.evaluations) / len(self.evaluations),
        }
    
    def export_to_csv(self, filepath: str) -> None:
        """
        Export evaluation records to CSV.
        
        Args:
            filepath: Path to save CSV file
        """
        import csv
        
        if not self.evaluations:
            logger.warning("No evaluations to export")
            return
        
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "query",
                    "context_relevance",
                    "faithfulness",
                    "answer_relevance",
                    "context_precision",
                    "composite_score",
                    "user_id",
                    "namespace",
                ]
            )
            writer.writeheader()
            
            for eval_record in self.evaluations:
                scores = eval_record["scores"]
                metadata = eval_record["metadata"]
                writer.writerow({
                    "query": eval_record["query"],
                    "context_relevance": scores["context_relevance"],
                    "faithfulness": scores["faithfulness"],
                    "answer_relevance": scores["answer_relevance"],
                    "context_precision": scores["context_precision"],
                    "composite_score": scores["composite_score"],
                    "user_id": metadata.get("user_id", ""),
                    "namespace": metadata.get("namespace", ""),
                })
        
        logger.info(f"Exported {len(self.evaluations)} evaluations to {filepath}")
