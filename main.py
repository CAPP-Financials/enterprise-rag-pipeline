#!/usr/bin/env python3
"""
Enterprise RAG Pipeline CLI

Main entrypoint for the RAG pipeline with command-line interface.
Supports ingestion, querying, and evaluation workflows.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from src.config import ConfigManager
from src.ingestion.chunking import HybridChunker
from src.retrieval.pinecone_store import PineconeVectorStore
from src.retrieval.hybrid_search import HybridRetriever, BM25RetrieverWrapper
from src.orchestration.graph import RAGOrchestrator, QueryExpander
from src.evaluation.ragas_metrics import RAGASEvaluator, EvaluationTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class RAGPipeline:
    """Main RAG pipeline class."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize RAG pipeline.
        
        Args:
            config_path: Path to YAML config file (uses env vars if not provided)
        """
        # Load configuration
        if config_path:
            self.config = ConfigManager.from_yaml(config_path)
        else:
            self.config = ConfigManager.from_env()
        
        # Set logging level
        logging.getLogger().setLevel(self.config.log_level)
        
        logger.info("Initializing RAG Pipeline...")
        
        # Initialize vector store
        self.vector_store = PineconeVectorStore(
            api_key=self.config.pinecone.api_key,
            index_name=self.config.pinecone.index_name,
            embedding_model=self.config.embedding.model_type,
        )
        
        # Initialize hybrid retriever
        self.retriever = HybridRetriever(
            dense_retriever=self.vector_store,
            embedding_model=self.config.embedding.model_type,
            alpha=self.config.retrieval.alpha,
            use_mmr=self.config.retrieval.use_mmr,
        )
        
        # Initialize chunker
        self.chunker = HybridChunker(
            chunk_size=self.config.chunking.chunk_size,
            chunk_overlap=self.config.chunking.chunk_overlap,
            use_semantic_refinement=self.config.chunking.use_semantic_refinement,
        )
        
        # Initialize evaluator
        self.evaluator = RAGASEvaluator()
        self.eval_tracker = EvaluationTracker()
        
        # Initialize orchestrator (requires LLM client)
        # Note: In production, inject actual LLM client
        try:
            from openai import OpenAI
            llm_client = OpenAI()
            
            self.orchestrator = RAGOrchestrator(
                retriever=self.retriever,
                llm_client=llm_client,
                query_expander=QueryExpander(llm_client) if self.config.enable_query_expansion else None,
            )
        except Exception as e:
            logger.warning(f"Could not initialize orchestrator: {e}. Query expansion disabled.")
            self.orchestrator = None
        
        logger.info("RAG Pipeline initialized successfully")
    
    def ingest_documents(
        self,
        documents_path: str,
        namespace: str = "default",
        batch_size: int = 100,
    ) -> int:
        """
        Ingest documents into the vector store.
        
        Args:
            documents_path: Path to JSON file with documents
            namespace: Namespace for data isolation
            batch_size: Batch size for ingestion
            
        Returns:
            Number of documents ingested
        """
        logger.info(f"Ingesting documents from {documents_path}...")
        
        # Load documents
        with open(documents_path, "r") as f:
            documents = json.load(f)
        
        if not isinstance(documents, list):
            documents = [documents]
        
        # Chunk documents
        chunked_docs = []
        for doc in documents:
            text = doc.get("text", "")
            chunks = self.chunker.chunk(text)
            
            for i, chunk in enumerate(chunks):
                chunked_docs.append({
                    "id": f"{doc.get('id', 'doc')}_chunk_{i}",
                    "text": chunk,
                    "metadata": {
                        "source": doc.get("source", "unknown"),
                        "business_unit": doc.get("business_unit", "general"),
                        "timestamp": doc.get("timestamp", ""),
                        **{k: v for k, v in doc.items() 
                           if k not in ["id", "text", "source", "business_unit", "timestamp"]}
                    }
                })
        
        # Ingest into vector store
        num_ingested = self.vector_store.ingest_documents(
            chunked_docs,
            namespace=namespace,
            batch_size=batch_size,
        )
        
        logger.info(f"Successfully ingested {num_ingested} chunks from {len(documents)} documents")
        return num_ingested
    
    def query(
        self,
        query: str,
        namespace: str = "default",
        user_id: str = "default",
        use_orchestrator: bool = True,
    ) -> dict:
        """
        Query the RAG pipeline.
        
        Args:
            query: User query
            namespace: Namespace to search within
            user_id: User identifier
            use_orchestrator: Whether to use full orchestration (with query expansion)
            
        Returns:
            Dictionary with answer and metadata
        """
        logger.info(f"Processing query: {query}")
        
        if use_orchestrator and self.orchestrator:
            # Use full orchestration pipeline
            result = self.orchestrator.run(
                query=query,
                namespace=namespace,
                user_id=user_id,
            )
            return result
        else:
            # Use simple retrieval + generation
            results = self.retriever.retrieve(
                query=query,
                namespace=namespace,
                top_k=self.config.retrieval.top_k,
                fetch_k=self.config.retrieval.fetch_k,
            )
            
            return {
                "original_query": query,
                "retrieved_context": results,
                "generated_answer": "Simple retrieval mode - answer generation not implemented",
            }
    
    def evaluate_query(
        self,
        query: str,
        context: list,
        answer: str,
        namespace: str = "default",
        user_id: str = "default",
    ) -> dict:
        """
        Evaluate a query-answer pair using RAGAS.
        
        Args:
            query: User query
            context: Retrieved context documents
            answer: Generated answer
            namespace: Namespace identifier
            user_id: User identifier
            
        Returns:
            Dictionary with evaluation scores
        """
        logger.info(f"Evaluating query: {query}")
        
        if not self.config.evaluation.enable_ragas:
            logger.warning("RAGAS evaluation is disabled")
            return {}
        
        # Extract text from context
        context_texts = [doc.get("text", "") for doc in context]
        
        # Evaluate
        scores = self.evaluator.evaluate_single(
            query=query,
            context=context_texts,
            answer=answer,
        )
        
        # Record evaluation
        self.eval_tracker.record(
            query=query,
            context=context_texts,
            answer=answer,
            scores=scores,
            metadata={"namespace": namespace, "user_id": user_id},
        )
        
        return scores.to_dict()
    
    def get_evaluation_report(self) -> dict:
        """
        Get evaluation report from tracked evaluations.
        
        Returns:
            Dictionary with aggregated evaluation metrics
        """
        return self.eval_tracker.get_statistics()
    
    def save_evaluation_report(self, output_path: str) -> None:
        """
        Save evaluation report to CSV.
        
        Args:
            output_path: Path to save CSV file
        """
        self.eval_tracker.export_to_csv(output_path)
        logger.info(f"Evaluation report saved to {output_path}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Enterprise RAG Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Ingest documents
  python main.py ingest --documents data/documents.json --namespace finance
  
  # Query the pipeline
  python main.py query --query "What is the revenue for Q3?" --namespace finance
  
  # Evaluate pipeline
  python main.py evaluate --config config.yaml
        """
    )
    
    parser.add_argument(
        "--config",
        type=str,
        help="Path to YAML configuration file",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Ingest documents")
    ingest_parser.add_argument("--documents", type=str, required=True, help="Path to documents JSON file")
    ingest_parser.add_argument("--namespace", type=str, default="default", help="Namespace for data isolation")
    ingest_parser.add_argument("--batch-size", type=int, default=100, help="Batch size for ingestion")
    
    # Query command
    query_parser = subparsers.add_parser("query", help="Query the pipeline")
    query_parser.add_argument("--query", type=str, required=True, help="Query text")
    query_parser.add_argument("--namespace", type=str, default="default", help="Namespace to search")
    query_parser.add_argument("--user-id", type=str, default="default", help="User identifier")
    query_parser.add_argument("--no-orchestrator", action="store_true", help="Disable query orchestration")
    
    # Evaluate command
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate pipeline")
    eval_parser.add_argument("--queries", type=str, help="Path to JSON file with test queries")
    eval_parser.add_argument("--output", type=str, default="evaluation_report.csv", help="Output CSV file")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Initialize pipeline
    try:
        pipeline = RAGPipeline(config_path=args.config)
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        sys.exit(1)
    
    # Execute command
    try:
        if args.command == "ingest":
            num_ingested = pipeline.ingest_documents(
                documents_path=args.documents,
                namespace=args.namespace,
                batch_size=args.batch_size,
            )
            print(f"✓ Ingested {num_ingested} documents")
        
        elif args.command == "query":
            result = pipeline.query(
                query=args.query,
                namespace=args.namespace,
                user_id=args.user_id,
                use_orchestrator=not args.no_orchestrator,
            )
            print(f"\nQuery: {args.query}")
            print(f"Answer: {result.get('generated_answer', 'N/A')}")
            print(f"\nRetrieved {len(result.get('retrieved_context', []))} documents")
        
        elif args.command == "evaluate":
            if args.queries:
                with open(args.queries, "r") as f:
                    test_queries = json.load(f)
                
                for test_case in test_queries:
                    scores = pipeline.evaluate_query(
                        query=test_case["query"],
                        context=test_case.get("context", []),
                        answer=test_case.get("answer", ""),
                    )
                    print(f"Query: {test_case['query']}")
                    print(f"Scores: {scores}")
                    print()
            
            # Save report
            pipeline.save_evaluation_report(args.output)
            print(f"\n✓ Evaluation report saved to {args.output}")
            
            # Print summary
            report = pipeline.get_evaluation_report()
            if report:
                print("\nEvaluation Summary:")
                for key, value in report.items():
                    print(f"  {key}: {value:.3f}")
    
    except Exception as e:
        logger.error(f"Command failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
