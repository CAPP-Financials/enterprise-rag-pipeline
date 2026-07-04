"""
Hybrid Retrieval Module

Combines dense vector retrieval with sparse BM25 keyword matching,
and applies MMR (Maximal Marginal Relevance) for diversity filtering.
"""

from typing import List, Dict, Optional, Tuple
import numpy as np
from pinecone_text.sparse import BM25Encoder
from langchain_openai import OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
import logging

logger = logging.getLogger(__name__)


class BM25RetrieverWrapper:
    """
    Wrapper for BM25 sparse retrieval using Pinecone's BM25Encoder.
    """
    
    def __init__(self, corpus: Optional[List[str]] = None):
        """
        Initialize BM25 retriever.
        
        Args:
            corpus: Optional corpus to fit BM25 on
        """
        self.bm25_encoder = BM25Encoder().default()
        
        if corpus:
            logger.info(f"Training BM25 on corpus of {len(corpus)} documents")
            self.bm25_encoder.fit(corpus)
    
    def encode_query(self, query: str) -> Dict:
        """
        Encode query to sparse representation.
        
        Args:
            query: Query text
            
        Returns:
            Sparse representation dict
        """
        return self.bm25_encoder.encode_query(query)
    
    def encode_corpus(self, corpus: List[str]) -> List[Dict]:
        """
        Encode corpus to sparse representations.
        
        Args:
            corpus: List of documents
            
        Returns:
            List of sparse representations
        """
        return self.bm25_encoder.encode_corpus(corpus)
    
    def save(self, path: str) -> None:
        """Save BM25 encoder to file."""
        self.bm25_encoder.dump(path)
    
    def load(self, path: str) -> None:
        """Load BM25 encoder from file."""
        self.bm25_encoder = BM25Encoder().load(path)


class HybridRetriever:
    """
    Hybrid retriever combining dense and sparse retrieval with MMR diversity filtering.
    
    Architecture:
    1. Dense retrieval: Vector similarity search
    2. Sparse retrieval: BM25 keyword matching
    3. Score combination: Weighted average of dense and sparse scores
    4. MMR filtering: Diversity-aware result selection
    """
    
    def __init__(
        self,
        dense_retriever,
        sparse_retriever: Optional[BM25RetrieverWrapper] = None,
        embedding_model: str = "openai",
        alpha: float = 0.5,
        use_mmr: bool = True,
    ):
        """
        Initialize hybrid retriever.
        
        Args:
            dense_retriever: Dense retriever instance (e.g., Pinecone)
            sparse_retriever: BM25 retriever instance
            embedding_model: "openai" or "huggingface"
            alpha: Weight for dense retrieval (1-alpha for sparse)
            use_mmr: Whether to apply MMR diversity filtering
        """
        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever
        self.alpha = alpha
        self.use_mmr = use_mmr
        
        # Initialize embeddings for MMR
        if embedding_model == "openai":
            self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        elif embedding_model == "huggingface":
            self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        else:
            raise ValueError(f"Unknown embedding model: {embedding_model}")
    
    def retrieve(
        self,
        query: str,
        namespace: str = "default",
        top_k: int = 5,
        fetch_k: int = 20,
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Retrieve documents using hybrid search with MMR filtering.
        
        Args:
            query: Query text
            namespace: Namespace to search within
            top_k: Number of final results to return
            fetch_k: Number of candidates to fetch before MMR filtering
            filters: Metadata filters
            
        Returns:
            List of retrieved documents with hybrid scores
        """
        # Dense retrieval
        dense_results = self.dense_retriever.search(
            query=query,
            namespace=namespace,
            top_k=fetch_k,
            filters=filters,
        )
        
        # Normalize dense scores (0-1 range)
        if dense_results:
            max_dense_score = max(r["score"] for r in dense_results)
            min_dense_score = min(r["score"] for r in dense_results)
            score_range = max_dense_score - min_dense_score
            
            for result in dense_results:
                if score_range > 0:
                    result["dense_score"] = (result["score"] - min_dense_score) / score_range
                else:
                    result["dense_score"] = 1.0
        
        # Sparse retrieval (if available)
        sparse_results = {}
        if self.sparse_retriever:
            try:
                sparse_query = self.sparse_retriever.encode_query(query)
                # TODO: Implement sparse search in Pinecone
                # For now, we'll skip sparse retrieval
            except Exception as e:
                logger.warning(f"Sparse retrieval failed: {e}")
        
        # Combine scores
        hybrid_results = []
        for result in dense_results:
            combined_score = self.alpha * result.get("dense_score", 0)
            if result["id"] in sparse_results:
                combined_score += (1 - self.alpha) * sparse_results[result["id"]]
            
            result["hybrid_score"] = combined_score
            hybrid_results.append(result)
        
        # Sort by hybrid score
        hybrid_results.sort(key=lambda x: x["hybrid_score"], reverse=True)
        
        # Apply MMR filtering
        if self.use_mmr and len(hybrid_results) > top_k:
            mmr_results = self._mmr_filtering(
                hybrid_results,
                query,
                top_k=top_k,
            )
            return mmr_results
        
        return hybrid_results[:top_k]
    
    def _mmr_filtering(
        self,
        candidates: List[Dict],
        query: str,
        top_k: int = 5,
        lambda_param: float = 0.5,
    ) -> List[Dict]:
        """
        Apply Maximal Marginal Relevance (MMR) filtering for diversity.
        
        MMR balances relevance to the query with diversity from already-selected documents.
        
        Args:
            candidates: List of candidate documents with scores
            query: Original query
            top_k: Number of results to return
            lambda_param: Trade-off parameter (0=diversity, 1=relevance)
            
        Returns:
            List of top-k diverse results
        """
        if not candidates or len(candidates) <= top_k:
            return candidates[:top_k]
        
        # Embed query and candidates
        query_embedding = self.embeddings.embed_query(query)
        query_embedding = np.array(query_embedding)
        
        candidate_embeddings = []
        for candidate in candidates:
            # Embed the text
            text_embedding = self.embeddings.embed_query(candidate["text"])
            candidate_embeddings.append(np.array(text_embedding))
        
        candidate_embeddings = np.array(candidate_embeddings)
        
        # Initialize selected set with highest-scoring document
        selected_indices = [0]
        selected_embeddings = [candidate_embeddings[0]]
        
        # Greedily select remaining documents
        while len(selected_indices) < top_k:
            best_idx = -1
            best_mmr_score = -float('inf')
            
            for i, candidate in enumerate(candidates):
                if i in selected_indices:
                    continue
                
                # Relevance: similarity to query
                relevance = np.dot(candidate_embeddings[i], query_embedding) / (
                    np.linalg.norm(candidate_embeddings[i]) * np.linalg.norm(query_embedding) + 1e-8
                )
                
                # Diversity: minimum similarity to already-selected documents
                diversity = float('inf')
                for selected_emb in selected_embeddings:
                    similarity = np.dot(candidate_embeddings[i], selected_emb) / (
                        np.linalg.norm(candidate_embeddings[i]) * np.linalg.norm(selected_emb) + 1e-8
                    )
                    diversity = min(diversity, similarity)
                
                # MMR score
                mmr_score = lambda_param * relevance - (1 - lambda_param) * diversity
                
                if mmr_score > best_mmr_score:
                    best_mmr_score = mmr_score
                    best_idx = i
            
            if best_idx >= 0:
                selected_indices.append(best_idx)
                selected_embeddings.append(candidate_embeddings[best_idx])
        
        # Return selected documents in original order
        mmr_results = [candidates[i] for i in selected_indices]
        
        # Add MMR score for transparency
        for i, result in enumerate(mmr_results):
            result["mmr_rank"] = i + 1
        
        return mmr_results
    
    def batch_retrieve(
        self,
        queries: List[str],
        namespace: str = "default",
        top_k: int = 5,
        fetch_k: int = 20,
        filters: Optional[Dict] = None,
    ) -> List[List[Dict]]:
        """
        Retrieve documents for multiple queries.
        
        Args:
            queries: List of query texts
            namespace: Namespace to search within
            top_k: Number of results per query
            fetch_k: Number of candidates to fetch per query
            filters: Metadata filters
            
        Returns:
            List of result lists (one per query)
        """
        results = []
        for query in queries:
            query_results = self.retrieve(
                query=query,
                namespace=namespace,
                top_k=top_k,
                fetch_k=fetch_k,
                filters=filters,
            )
            results.append(query_results)
        
        return results
