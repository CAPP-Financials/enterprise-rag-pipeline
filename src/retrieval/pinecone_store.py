"""
Pinecone Vector Store Integration

Manages Pinecone index creation, document ingestion, and namespace-based data isolation
for enterprise multi-tenant scenarios.
"""

import os
from typing import List, Dict, Optional, Tuple
from pinecone import Pinecone, ServerlessSpec
from langchain_openai import OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
import logging

logger = logging.getLogger(__name__)


class PineconeVectorStore:
    """
    Enterprise-grade Pinecone vector store with namespace isolation.
    
    Supports:
    - Namespace-based data separation per business unit
    - Hybrid search with metadata filtering
    - Batch document ingestion
    - Scalable retrieval for 500+ distributed users
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        index_name: str = "enterprise-rag-index",
        environment: str = "us-east-1-aws",
        embedding_model: str = "openai",
        embedding_dim: int = 1536,
        metric: str = "cosine",
    ):
        """
        Initialize Pinecone vector store.
        
        Args:
            api_key: Pinecone API key (defaults to PINECONE_API_KEY env var)
            index_name: Name of the Pinecone index
            environment: Pinecone environment
            embedding_model: "openai" or "huggingface"
            embedding_dim: Dimension of embeddings
            metric: Distance metric ("cosine", "dotproduct", "euclidean")
        """
        self.api_key = api_key or os.getenv("PINECONE_API_KEY")
        if not self.api_key:
            raise ValueError("PINECONE_API_KEY environment variable not set")
        
        self.index_name = index_name
        self.environment = environment
        self.embedding_dim = embedding_dim
        self.metric = metric
        
        # Initialize Pinecone client
        self.pc = Pinecone(api_key=self.api_key)
        
        # Initialize embeddings
        if embedding_model == "openai":
            self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        elif embedding_model == "huggingface":
            self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        else:
            raise ValueError(f"Unknown embedding model: {embedding_model}")
        
        # Create or get index
        self._ensure_index_exists()
        self.index = self.pc.Index(index_name)
        
        logger.info(f"Initialized Pinecone vector store: {index_name}")
    
    def _ensure_index_exists(self) -> None:
        """Create Pinecone index if it doesn't exist."""
        existing_indexes = [idx.name for idx in self.pc.list_indexes()]
        
        if self.index_name not in existing_indexes:
            logger.info(f"Creating Pinecone index: {self.index_name}")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.embedding_dim,
                metric=self.metric,
                spec=ServerlessSpec(cloud="aws", region=self.environment.split("-")[0] + "-" + self.environment.split("-")[1]),
            )
        else:
            logger.info(f"Index {self.index_name} already exists")
    
    def ingest_documents(
        self,
        documents: List[Dict[str, str]],
        namespace: str = "default",
        batch_size: int = 100,
    ) -> int:
        """
        Ingest documents into Pinecone with namespace isolation.
        
        Args:
            documents: List of dicts with 'id', 'text', and optional 'metadata'
            namespace: Namespace for data isolation (e.g., business unit name)
            batch_size: Number of documents to process per batch
            
        Returns:
            Number of documents ingested
        """
        logger.info(f"Ingesting {len(documents)} documents into namespace '{namespace}'")
        
        vectors_to_upsert = []
        
        for i, doc in enumerate(documents):
            doc_id = doc.get("id", f"doc_{i}")
            text = doc.get("text", "")
            metadata = doc.get("metadata", {})
            
            # Generate embedding
            embedding = self.embeddings.embed_query(text)
            
            # Prepare vector with metadata
            vector = (
                doc_id,
                embedding,
                {
                    "text": text,
                    "source": metadata.get("source", "unknown"),
                    "business_unit": metadata.get("business_unit", "general"),
                    "timestamp": metadata.get("timestamp", ""),
                    **{k: v for k, v in metadata.items() if k not in ["source", "business_unit", "timestamp"]}
                }
            )
            
            vectors_to_upsert.append(vector)
            
            # Upsert in batches
            if len(vectors_to_upsert) >= batch_size:
                self.index.upsert(
                    vectors=vectors_to_upsert,
                    namespace=namespace,
                )
                logger.info(f"Upserted batch of {len(vectors_to_upsert)} vectors")
                vectors_to_upsert = []
        
        # Upsert remaining vectors
        if vectors_to_upsert:
            self.index.upsert(
                vectors=vectors_to_upsert,
                namespace=namespace,
            )
            logger.info(f"Upserted final batch of {len(vectors_to_upsert)} vectors")
        
        logger.info(f"Successfully ingested {len(documents)} documents")
        return len(documents)
    
    def search(
        self,
        query: str,
        namespace: str = "default",
        top_k: int = 5,
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Search for similar documents using dense retrieval.
        
        Args:
            query: Query text
            namespace: Namespace to search within
            top_k: Number of results to return
            filters: Metadata filters (e.g., {"business_unit": "finance"})
            
        Returns:
            List of retrieved documents with scores
        """
        # Generate query embedding
        query_embedding = self.embeddings.embed_query(query)
        
        # Search in Pinecone
        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=namespace,
            filter=filters,
            include_metadata=True,
        )
        
        # Format results
        retrieved_docs = []
        for match in results.get("matches", []):
            retrieved_docs.append({
                "id": match["id"],
                "score": match["score"],
                "text": match["metadata"].get("text", ""),
                "metadata": {k: v for k, v in match["metadata"].items() if k != "text"}
            })
        
        return retrieved_docs
    
    def hybrid_search(
        self,
        query: str,
        namespace: str = "default",
        top_k: int = 5,
        alpha: float = 0.5,
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Hybrid search combining dense and sparse retrieval.
        
        Note: This is a placeholder for the actual hybrid search implementation.
        In production, integrate with BM25Encoder for sparse retrieval.
        
        Args:
            query: Query text
            namespace: Namespace to search within
            top_k: Number of results to return
            alpha: Weight for dense retrieval (1-alpha for sparse)
            filters: Metadata filters
            
        Returns:
            List of retrieved documents with combined scores
        """
        # For now, return dense search results
        # TODO: Integrate with BM25 sparse retrieval
        return self.search(query, namespace, top_k, filters)
    
    def delete_namespace(self, namespace: str) -> None:
        """
        Delete all documents in a namespace.
        
        Args:
            namespace: Namespace to delete
        """
        logger.warning(f"Deleting all documents in namespace: {namespace}")
        self.index.delete(delete_all=True, namespace=namespace)
    
    def get_namespace_stats(self, namespace: str) -> Dict:
        """
        Get statistics for a namespace.
        
        Args:
            namespace: Namespace to get stats for
            
        Returns:
            Dictionary with namespace statistics
        """
        stats = self.index.describe_index_stats()
        namespace_stats = stats.get("namespaces", {}).get(namespace, {})
        
        return {
            "vector_count": namespace_stats.get("vector_count", 0),
            "dimension": stats.get("dimension", 0),
            "index_fullness": stats.get("index_fullness", 0),
        }
    
    def list_namespaces(self) -> List[str]:
        """
        List all namespaces in the index.
        
        Returns:
            List of namespace names
        """
        stats = self.index.describe_index_stats()
        return list(stats.get("namespaces", {}).keys())
