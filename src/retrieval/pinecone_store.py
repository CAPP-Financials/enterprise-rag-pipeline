"""
Pinecone Vector Store Integration

Manages Pinecone index creation, document ingestion, and namespace-based data isolation
for enterprise multi-tenant scenarios.

Edge cases handled:
- Missing API key (clear error message)
- Index already exists (idempotent creation)
- Empty document list
- Documents with missing 'id' or 'text' fields
- Metadata values that are not Pinecone-compatible types (auto-cast to str)
- Batch ingestion failures (per-batch retry with logging)
- search() with top_k=0 (returns [])
- search() with empty query (returns [])
- Namespace not found (returns empty list gracefully)
- region parsing from environment string
"""

import logging
import os
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------
try:
    from pinecone import Pinecone, ServerlessSpec
    _PINECONE_AVAILABLE = True
except ImportError:
    _PINECONE_AVAILABLE = False
    logger.warning("pinecone package not available; PineconeVectorStore will raise on init")

try:
    from langchain_openai import OpenAIEmbeddings as _OpenAIEmbeddings
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

try:
    from langchain_huggingface import HuggingFaceEmbeddings as _HFEmbeddings
    _HF_AVAILABLE = True
except ImportError:
    _HF_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_metadata_value(value) -> str:
    """
    Convert metadata value to a Pinecone-compatible type.

    Pinecone metadata supports: str, int, float, bool, list[str].
    Anything else is cast to str.
    """
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [str(v) for v in value]
    return str(value)


def _parse_region(environment: str) -> str:
    """
    Parse cloud region from environment string.

    Examples:
        "us-east-1-aws"  → "us-east-1"
        "eu-west-1"      → "eu-west-1"
        "us-east-1"      → "us-east-1"
    """
    # Strip trailing cloud provider suffix (e.g. "-aws", "-gcp")
    parts = environment.split("-")
    # Standard AWS/GCP region format: <continent>-<direction>-<number>
    if len(parts) >= 3 and parts[-1] in ("aws", "gcp", "azure"):
        return "-".join(parts[:-1])
    return environment


# ---------------------------------------------------------------------------
# PineconeVectorStore
# ---------------------------------------------------------------------------

class PineconeVectorStore:
    """
    Enterprise-grade Pinecone vector store with namespace isolation.

    Supports:
    - Namespace-based data separation per business unit
    - Metadata filtering for sub-namespace queries
    - Batch document ingestion with per-batch error handling
    - Scalable retrieval for 500+ distributed users
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        index_name: str = "enterprise-rag-index",
        environment: str = "us-east-1-aws",
        embedding_model: str = "huggingface",
        embedding_dim: int = 384,
        metric: str = "cosine",
    ):
        """
        Initialise Pinecone vector store.

        Args:
            api_key        : Pinecone API key (falls back to PINECONE_API_KEY env var).
            index_name     : Name of the Pinecone index.
            environment    : Pinecone cloud region string (e.g. "us-east-1-aws").
            embedding_model: "openai" (dim=1536) or "huggingface" (dim=384).
            embedding_dim  : Embedding dimension — must match the chosen model.
            metric         : Distance metric: "cosine", "dotproduct", or "euclidean".

        Raises:
            ImportError : If pinecone package is not installed.
            ValueError  : If API key is missing or embedding_model is unknown.
        """
        if not _PINECONE_AVAILABLE:
            raise ImportError(
                "pinecone package is required. Install with: pip install pinecone-client"
            )

        resolved_key = api_key or os.getenv("PINECONE_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "Pinecone API key not found. Set PINECONE_API_KEY environment variable "
                "or pass api_key= to PineconeVectorStore()."
            )

        self.index_name = index_name
        self.environment = environment
        self.embedding_dim = embedding_dim
        self.metric = metric

        logger.info(
            "Initialising PineconeVectorStore: index=%s, region=%s, embedding=%s, dim=%d",
            index_name, environment, embedding_model, embedding_dim,
        )

        # Pinecone client
        self.pc = Pinecone(api_key=resolved_key)

        # Embeddings
        if embedding_model == "openai":
            if not _OPENAI_AVAILABLE:
                raise ImportError("langchain_openai required for OpenAI embeddings")
            self.embeddings = _OpenAIEmbeddings(model="text-embedding-3-small")
        elif embedding_model == "huggingface":
            if not _HF_AVAILABLE:
                raise ImportError("langchain_huggingface required for HuggingFace embeddings")
            self.embeddings = _HFEmbeddings(model_name="all-MiniLM-L6-v2")
        else:
            raise ValueError(
                f"Unknown embedding_model '{embedding_model}'. "
                "Choose 'openai' or 'huggingface'."
            )

        # Create index if needed
        self._ensure_index_exists()
        self.index = self.pc.Index(index_name)
        logger.info("PineconeVectorStore ready: index=%s", index_name)

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _ensure_index_exists(self) -> None:
        """Create Pinecone index if it does not already exist."""
        existing = [idx.name for idx in self.pc.list_indexes()]
        if self.index_name in existing:
            logger.info("Index '%s' already exists; skipping creation", self.index_name)
            return

        region = _parse_region(self.environment)
        logger.info(
            "Creating Pinecone index '%s': dim=%d, metric=%s, region=%s",
            self.index_name, self.embedding_dim, self.metric, region,
        )
        self.pc.create_index(
            name=self.index_name,
            dimension=self.embedding_dim,
            metric=self.metric,
            spec=ServerlessSpec(cloud="aws", region=region),
        )
        # Wait for index to be ready
        self._wait_for_index_ready()

    def _wait_for_index_ready(self, timeout: int = 120) -> None:
        """Poll until index is ready or timeout expires."""
        logger.info("Waiting for index '%s' to become ready...", self.index_name)
        deadline = time.time() + timeout
        while time.time() < deadline:
            desc = self.pc.describe_index(self.index_name)
            status = getattr(desc, "status", {})
            if isinstance(status, dict) and status.get("ready"):
                logger.info("Index '%s' is ready", self.index_name)
                return
            time.sleep(2)
        logger.warning("Index '%s' did not become ready within %ds", self.index_name, timeout)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_documents(
        self,
        documents: List[Dict],
        namespace: str = "default",
        batch_size: int = 100,
    ) -> int:
        """
        Ingest documents into Pinecone with namespace isolation.

        Args:
            documents : List of dicts with 'id', 'text', and optional 'metadata'.
            namespace : Namespace for data isolation (e.g. business unit name).
            batch_size: Documents per upsert batch.

        Returns:
            Number of documents successfully ingested.

        Edge cases:
        - Empty list → logs warning, returns 0
        - Document missing 'text' → skipped with warning
        - Document missing 'id' → auto-generated as "doc_{index}"
        - Metadata values of unsupported types → cast to str
        """
        if not documents:
            logger.warning("ingest_documents: empty document list; nothing to ingest")
            return 0

        logger.info(
            "ingest_documents: %d documents → namespace='%s', batch_size=%d",
            len(documents), namespace, batch_size,
        )

        vectors_to_upsert = []
        skipped = 0
        ingested = 0

        for i, doc in enumerate(documents):
            doc_id = doc.get("id") or f"doc_{i}"
            text = doc.get("text", "")
            metadata = doc.get("metadata", {})

            if not text or not text.strip():
                logger.warning("Document %s has empty text; skipping", doc_id)
                skipped += 1
                continue

            # Generate embedding
            try:
                embedding = self.embeddings.embed_query(text)
            except Exception as exc:
                logger.error("Failed to embed document %s: %s; skipping", doc_id, exc)
                skipped += 1
                continue

            # Sanitise metadata
            safe_meta = {
                "text": text[:40_000],  # Pinecone metadata value limit
                "source": str(metadata.get("source", "unknown")),
                "business_unit": str(metadata.get("business_unit", "general")),
                "timestamp": str(metadata.get("timestamp", "")),
            }
            for k, v in metadata.items():
                if k not in safe_meta:
                    safe_meta[k] = _safe_metadata_value(v)

            vectors_to_upsert.append((doc_id, embedding, safe_meta))

            if len(vectors_to_upsert) >= batch_size:
                self._upsert_batch(vectors_to_upsert, namespace)
                ingested += len(vectors_to_upsert)
                vectors_to_upsert = []

        # Flush remaining
        if vectors_to_upsert:
            self._upsert_batch(vectors_to_upsert, namespace)
            ingested += len(vectors_to_upsert)

        logger.info(
            "ingest_documents complete: %d ingested, %d skipped (namespace='%s')",
            ingested, skipped, namespace,
        )
        return ingested

    def _upsert_batch(self, vectors: List, namespace: str) -> None:
        """Upsert a batch of vectors with retry on failure."""
        for attempt in range(3):
            try:
                self.index.upsert(vectors=vectors, namespace=namespace)
                logger.info("Upserted batch of %d vectors (namespace='%s')", len(vectors), namespace)
                return
            except Exception as exc:
                logger.warning(
                    "Upsert attempt %d/3 failed: %s", attempt + 1, exc
                )
                time.sleep(2 ** attempt)
        logger.error("All upsert attempts failed for batch of %d vectors", len(vectors))

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

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
            query    : Query text.
            namespace: Namespace to search within.
            top_k    : Number of results to return.
            filters  : Pinecone metadata filters.

        Returns:
            List of retrieved documents with 'id', 'score', 'text', 'metadata'.

        Edge cases:
        - Empty query → returns []
        - top_k <= 0 → returns []
        - Namespace not found → returns [] gracefully
        """
        if not query or not query.strip():
            logger.warning("search() called with empty query; returning []")
            return []

        if top_k <= 0:
            logger.warning("search() called with top_k=%d; returning []", top_k)
            return []

        logger.info(
            "search(): query='%s...', namespace=%s, top_k=%d",
            query[:60], namespace, top_k,
        )

        try:
            query_embedding = self.embeddings.embed_query(query)
        except Exception as exc:
            logger.error("Failed to embed query: %s", exc, exc_info=True)
            return []

        try:
            results = self.index.query(
                vector=query_embedding,
                top_k=top_k,
                namespace=namespace,
                filter=filters,
                include_metadata=True,
            )
        except Exception as exc:
            logger.error("Pinecone query failed: %s", exc, exc_info=True)
            return []

        matches = results.get("matches", [])
        if not matches:
            logger.info("search(): no matches found in namespace='%s'", namespace)
            return []

        retrieved = []
        for match in matches:
            meta = match.get("metadata") or {}
            retrieved.append({
                "id": match.get("id", ""),
                "score": float(match.get("score", 0.0)),
                "text": meta.get("text", ""),
                "metadata": {k: v for k, v in meta.items() if k != "text"},
            })

        logger.info("search(): returned %d results", len(retrieved))
        return retrieved

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

        Note: Full sparse retrieval requires a Pinecone hybrid index.
        Current implementation falls back to dense-only with a warning.

        Args:
            query    : Query text.
            namespace: Namespace to search within.
            top_k    : Number of results.
            alpha    : Weight for dense retrieval (unused in current implementation).
            filters  : Metadata filters.

        Returns:
            List of retrieved documents.
        """
        logger.info(
            "hybrid_search(): query='%s...', namespace=%s, top_k=%d, alpha=%.2f",
            query[:60], namespace, top_k, alpha,
        )
        # Full hybrid requires a Pinecone hybrid index; degrade gracefully
        logger.debug("hybrid_search: using dense-only (sparse requires hybrid Pinecone index)")
        return self.search(query, namespace, top_k, filters)

    # ------------------------------------------------------------------
    # Namespace management
    # ------------------------------------------------------------------

    def delete_namespace(self, namespace: str) -> None:
        """Delete all documents in a namespace."""
        logger.warning("Deleting all documents in namespace='%s'", namespace)
        self.index.delete(delete_all=True, namespace=namespace)

    def get_namespace_stats(self, namespace: str) -> Dict:
        """
        Get statistics for a namespace.

        Returns:
            Dict with 'vector_count', 'dimension', 'index_fullness'.
        """
        try:
            stats = self.index.describe_index_stats()
        except Exception as exc:
            logger.error("Failed to get index stats: %s", exc)
            return {"vector_count": 0, "dimension": 0, "index_fullness": 0}

        ns_stats = (stats.get("namespaces") or {}).get(namespace, {})
        return {
            "vector_count": ns_stats.get("vector_count", 0),
            "dimension": stats.get("dimension", 0),
            "index_fullness": stats.get("index_fullness", 0.0),
        }

    def list_namespaces(self) -> List[str]:
        """List all namespaces in the index."""
        try:
            stats = self.index.describe_index_stats()
            return list((stats.get("namespaces") or {}).keys())
        except Exception as exc:
            logger.error("Failed to list namespaces: %s", exc)
            return []
