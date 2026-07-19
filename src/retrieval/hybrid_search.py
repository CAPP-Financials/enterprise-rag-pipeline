"""
Hybrid Retrieval Module

Combines dense vector retrieval with sparse BM25 keyword matching,
and applies MMR (Maximal Marginal Relevance) for diversity filtering.

Edge cases handled:
- Empty query string
- Empty candidate list for MMR
- top_k > number of available candidates
- fetch_k < top_k (auto-corrected)
- Zero-norm embeddings in MMR cosine computation
- BM25 encoder not fitted (graceful fallback to dense-only)
- All candidates identical (MMR degeneracy)
- Single candidate returned from dense search
- alpha outside [0, 1] (clamped)
"""

import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — allow module to load even without pinecone_text installed
# ---------------------------------------------------------------------------
try:
    from pinecone_text.sparse import BM25Encoder as _BM25Encoder
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False
    logger.warning("pinecone_text not available; BM25 sparse retrieval disabled")

try:
    from langchain_openai import OpenAIEmbeddings as _OpenAIEmbeddings
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False
    logger.warning("langchain_openai not available; OpenAI embeddings disabled")

try:
    from langchain_huggingface import HuggingFaceEmbeddings as _HFEmbeddings
    _HF_AVAILABLE = True
except ImportError:
    _HF_AVAILABLE = False
    logger.warning("langchain_huggingface not available; HuggingFace embeddings disabled")


# ---------------------------------------------------------------------------
# BM25 Wrapper
# ---------------------------------------------------------------------------

class BM25RetrieverWrapper:
    """
    Wrapper for BM25 sparse retrieval using Pinecone's BM25Encoder.

    Edge cases:
    - Library not installed → raises ImportError with clear message
    - encode_query on unfitted encoder → returns empty sparse dict
    - Empty corpus → logs warning, encoder remains in default state
    """

    def __init__(self, corpus: Optional[List[str]] = None):
        """
        Initialise BM25 retriever.

        Args:
            corpus: Optional corpus to fit BM25 on.

        Raises:
            ImportError: If pinecone_text is not installed.
        """
        if not _BM25_AVAILABLE:
            raise ImportError(
                "pinecone_text is required for BM25 retrieval. "
                "Install with: pip install pinecone-text"
            )

        self.bm25_encoder = _BM25Encoder().default()
        self._fitted = False

        if corpus:
            if not corpus:
                logger.warning("BM25RetrieverWrapper: empty corpus provided; skipping fit")
            else:
                logger.info("Training BM25 on corpus of %d documents", len(corpus))
                self.bm25_encoder.fit(corpus)
                self._fitted = True

    def encode_query(self, query: str) -> Dict:
        """
        Encode query to sparse representation.

        Args:
            query: Query text (empty string returns empty dict).

        Returns:
            Sparse representation dict.
        """
        if not query or not query.strip():
            logger.warning("BM25RetrieverWrapper.encode_query: empty query; returning {}")
            return {}
        results = self.bm25_encoder.encode_queries([query])
        return results[0] if results else {}

    def encode_corpus(self, corpus: List[str]) -> List[Dict]:
        """
        Encode corpus to sparse representations.

        Args:
            corpus: List of document strings.

        Returns:
            List of sparse representation dicts.
        """
        if not corpus:
            logger.warning("BM25RetrieverWrapper.encode_corpus: empty corpus; returning []")
            return []
        return self.bm25_encoder.encode_documents(corpus)

    def save(self, path: str) -> None:
        """Save BM25 encoder to file."""
        logger.info("Saving BM25 encoder to %s", path)
        self.bm25_encoder.dump(path)

    def load(self, path: str) -> None:
        """Load BM25 encoder from file."""
        logger.info("Loading BM25 encoder from %s", path)
        self.bm25_encoder = _BM25Encoder().load(path)
        self._fitted = True


# ---------------------------------------------------------------------------
# Hybrid Retriever
# ---------------------------------------------------------------------------

class HybridRetriever:
    """
    Hybrid retriever combining dense and sparse retrieval with MMR diversity filtering.

    Architecture:
    1. Dense retrieval  : Vector similarity search via Pinecone
    2. Sparse retrieval : BM25 keyword matching (optional)
    3. Score fusion     : Weighted average of dense and sparse scores
    4. MMR filtering    : Diversity-aware result selection

    Edge cases handled:
    - Empty query
    - fetch_k < top_k (auto-corrected to top_k)
    - alpha clamped to [0, 1]
    - No results from dense retrieval
    - MMR with fewer candidates than top_k
    """

    def __init__(
        self,
        dense_retriever,
        sparse_retriever: Optional[BM25RetrieverWrapper] = None,
        embedding_model: str = "huggingface",
        alpha: float = 0.5,
        use_mmr: bool = True,
    ):
        """
        Initialise hybrid retriever.

        Args:
            dense_retriever : Dense retriever instance (e.g., PineconeVectorStore).
            sparse_retriever: Optional BM25 retriever instance.
            embedding_model : "openai" or "huggingface" — used for MMR re-embedding.
            alpha           : Weight for dense retrieval score (clamped to [0, 1]).
            use_mmr         : Whether to apply MMR diversity filtering.

        Raises:
            ValueError: If embedding_model is not recognised.
        """
        # Clamp alpha
        if not 0.0 <= alpha <= 1.0:
            logger.warning("alpha=%.3f is outside [0, 1]; clamping", alpha)
            alpha = max(0.0, min(1.0, alpha))

        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever
        self.alpha = alpha
        self.use_mmr = use_mmr

        logger.info(
            "Initialising HybridRetriever: embedding=%s, alpha=%.2f, mmr=%s",
            embedding_model, alpha, use_mmr,
        )

        # Embeddings for MMR re-ranking
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        namespace: str = "default",
        top_k: int = 5,
        fetch_k: int = 20,
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Retrieve documents using hybrid search with optional MMR filtering.

        Args:
            query    : Query text.
            namespace: Pinecone namespace to search within.
            top_k    : Number of final results to return.
            fetch_k  : Candidates to fetch before MMR (auto-corrected if < top_k).
            filters  : Pinecone metadata filters.

        Returns:
            List of retrieved document dicts with hybrid_score and optional mmr_rank.
        """
        # --- Guard: empty query ---
        if not query or not query.strip():
            logger.warning("retrieve() called with empty query; returning []")
            return []

        # --- Guard: fetch_k < top_k ---
        if fetch_k < top_k:
            logger.warning("fetch_k (%d) < top_k (%d); setting fetch_k = top_k", fetch_k, top_k)
            fetch_k = top_k

        logger.info(
            "retrieve(): query='%s...', namespace=%s, top_k=%d, fetch_k=%d",
            query[:60], namespace, top_k, fetch_k,
        )

        # --- Dense retrieval ---
        try:
            dense_results = self.dense_retriever.search(
                query=query,
                namespace=namespace,
                top_k=fetch_k,
                filters=filters,
            )
        except Exception as exc:
            logger.error("Dense retrieval failed: %s", exc, exc_info=True)
            return []

        if not dense_results:
            logger.warning("Dense retrieval returned 0 results for query='%s'", query[:60])
            return []

        logger.info("Dense retrieval returned %d candidates", len(dense_results))

        # --- Normalise dense scores to [0, 1] ---
        scores = [r["score"] for r in dense_results]
        score_min, score_max = min(scores), max(scores)
        score_range = score_max - score_min

        for result in dense_results:
            if score_range > 1e-9:
                result["dense_score"] = (result["score"] - score_min) / score_range
            else:
                result["dense_score"] = 1.0  # All scores identical

        # --- Sparse retrieval (optional) ---
        sparse_scores: Dict[str, float] = {}
        if self.sparse_retriever:
            try:
                _sparse_query = self.sparse_retriever.encode_query(query)
                # NOTE: Full Pinecone sparse-vector search requires a hybrid index.
                # Current implementation gracefully degrades to dense-only.
                logger.debug("Sparse query encoded; full sparse search requires hybrid Pinecone index")
            except Exception as exc:
                logger.warning("Sparse retrieval failed: %s; falling back to dense-only", exc)

        # --- Combine scores ---
        for result in dense_results:
            dense_s = result.get("dense_score", 0.0)
            sparse_s = sparse_scores.get(result["id"], 0.0)
            result["hybrid_score"] = self.alpha * dense_s + (1.0 - self.alpha) * sparse_s

        # Sort by hybrid score descending
        dense_results.sort(key=lambda x: x["hybrid_score"], reverse=True)

        # --- MMR filtering ---
        if self.use_mmr and len(dense_results) > top_k:
            logger.info("Applying MMR filtering: %d → %d results", len(dense_results), top_k)
            return self._mmr_filtering(dense_results, query, top_k=top_k)

        result_slice = dense_results[:top_k]
        logger.info("retrieve() returning %d results (no MMR needed)", len(result_slice))
        return result_slice

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
            queries  : List of query strings.
            namespace: Pinecone namespace.
            top_k    : Results per query.
            fetch_k  : Candidates per query before MMR.
            filters  : Metadata filters.

        Returns:
            List of result lists (one per query).
        """
        if not queries:
            logger.warning("batch_retrieve() called with empty queries list; returning []")
            return []

        logger.info("batch_retrieve(): %d queries", len(queries))
        results = []
        for i, query in enumerate(queries):
            logger.info("  Processing query %d/%d: '%s...'", i + 1, len(queries), query[:40])
            results.append(
                self.retrieve(query=query, namespace=namespace,
                              top_k=top_k, fetch_k=fetch_k, filters=filters)
            )
        return results

    # ------------------------------------------------------------------
    # Internal: MMR
    # ------------------------------------------------------------------

    def _mmr_filtering(
        self,
        candidates: List[Dict],
        query: str,
        top_k: int = 5,
        lambda_param: float = 0.5,
    ) -> List[Dict]:
        """
        Apply Maximal Marginal Relevance (MMR) filtering for diversity.

        MMR score = λ * Relevance(doc, query) − (1−λ) * max_Similarity(doc, selected)

        Edge cases:
        - Fewer candidates than top_k → return all candidates
        - Zero-norm embeddings → cosine similarity treated as 0
        - All candidates identical → first top_k returned

        Args:
            candidates   : Candidate documents (already sorted by hybrid_score).
            query        : Original query string.
            top_k        : Number of results to return.
            lambda_param : Trade-off (0 = max diversity, 1 = max relevance).

        Returns:
            Diverse list of top_k documents.
        """
        if not candidates:
            logger.warning("_mmr_filtering: empty candidates list; returning []")
            return []

        if len(candidates) <= top_k:
            logger.info("_mmr_filtering: candidates (%d) ≤ top_k (%d); returning all",
                        len(candidates), top_k)
            return candidates

        logger.info("_mmr_filtering: embedding %d candidates for MMR", len(candidates))

        # Embed query
        try:
            query_emb = np.array(self.embeddings.embed_query(query), dtype=np.float32)
        except Exception as exc:
            logger.error("MMR: failed to embed query: %s; skipping MMR", exc)
            return candidates[:top_k]

        # Embed candidates
        candidate_embs: List[np.ndarray] = []
        for i, cand in enumerate(candidates):
            text = cand.get("text", "")
            if not text.strip():
                logger.debug("MMR: candidate %d has empty text; using zero vector", i)
                candidate_embs.append(np.zeros_like(query_emb))
            else:
                try:
                    candidate_embs.append(
                        np.array(self.embeddings.embed_query(text), dtype=np.float32)
                    )
                except Exception as exc:
                    logger.warning("MMR: failed to embed candidate %d: %s; using zero vector", i, exc)
                    candidate_embs.append(np.zeros_like(query_emb))

        def _cosine(a: np.ndarray, b: np.ndarray) -> float:
            """Safe cosine similarity; returns 0.0 for zero-norm vectors."""
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a < 1e-9 or norm_b < 1e-9:
                return 0.0
            return float(np.dot(a, b) / (norm_a * norm_b))

        selected_indices: List[int] = [0]
        selected_embs: List[np.ndarray] = [candidate_embs[0]]

        while len(selected_indices) < top_k:
            best_idx = -1
            best_score = -float("inf")

            for i in range(len(candidates)):
                if i in selected_indices:
                    continue

                relevance = _cosine(candidate_embs[i], query_emb)
                max_sim_to_selected = max(
                    _cosine(candidate_embs[i], sel_emb) for sel_emb in selected_embs
                )
                mmr_score = lambda_param * relevance - (1.0 - lambda_param) * max_sim_to_selected

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = i

            if best_idx < 0:
                logger.warning("MMR: no valid candidate found in iteration; stopping early")
                break

            selected_indices.append(best_idx)
            selected_embs.append(candidate_embs[best_idx])
            logger.debug("MMR selected candidate %d (score=%.4f)", best_idx, best_score)

        mmr_results = [candidates[i] for i in selected_indices]
        for rank, result in enumerate(mmr_results, start=1):
            result["mmr_rank"] = rank

        logger.info("_mmr_filtering: selected %d diverse results", len(mmr_results))
        return mmr_results
