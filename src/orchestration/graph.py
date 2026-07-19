"""
LangGraph Orchestration Layer

Implements the RAG workflow as a directed graph with explicit state management.
Orchestrates query expansion → retrieval → deduplication → generation.

Edge cases handled:
- Empty / None query
- LLM client unavailable (query expansion degrades gracefully)
- Retrieval returning 0 results (answer states "no context found")
- Deduplication of empty context list
- Generation failure (returns error message, does not crash)
- State keys missing (all nodes use .get() with defaults)
- Timing tracked per node for observability
"""

import logging
import time
from typing import Any, Dict, List, Optional

from langgraph.graph import StateGraph

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query Expander
# ---------------------------------------------------------------------------

class QueryExpander:
    """
    Expands user queries to improve recall.

    Techniques:
    1. Rewrite   : Rephrase the query in different ways.
    2. Decompose : Break complex queries into sub-queries.
    3. Step-back : Ask for abstract concepts first.

    Edge cases:
    - LLM unavailable → returns [original_query] only
    - Empty query → returns []
    - LLM returns empty response → returns [original_query]
    - Duplicate variants → deduplicated
    """

    def __init__(self, llm_client):
        """
        Initialise query expander.

        Args:
            llm_client: OpenAI-compatible client (must support chat.completions.create).
        """
        self.llm_client = llm_client
        logger.info("QueryExpander initialised")

    def expand(self, query: str, num_expansions: int = 3) -> List[str]:
        """
        Expand query into multiple variants.

        Args:
            query          : Original query string.
            num_expansions : Number of additional variants to generate.

        Returns:
            List starting with original query, followed by unique variants.
        """
        if not query or not query.strip():
            logger.warning("QueryExpander.expand: empty query; returning []")
            return []

        expanded = [query.strip()]

        if self.llm_client is None:
            logger.warning("QueryExpander: no LLM client; returning original query only")
            return expanded

        prompt = (
            f"Generate {num_expansions} alternative phrasings of this search query "
            f"that would help retrieve the same information from a knowledge base.\n\n"
            f"Original query: {query}\n\n"
            f"Output exactly {num_expansions} alternatives, one per line, "
            f"without numbering or bullet points:"
        )

        try:
            response = self.llm_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a query expansion expert. "
                            "Generate alternative phrasings that preserve the original intent."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=300,
            )

            raw = response.choices[0].message.content or ""
            variants = [v.strip() for v in raw.strip().split("\n") if v.strip()]

            for variant in variants:
                if variant and variant not in expanded:
                    expanded.append(variant)

            logger.info(
                "QueryExpander: expanded '%s...' into %d variants",
                query[:40], len(expanded),
            )

        except Exception as exc:
            logger.warning(
                "QueryExpander: LLM call failed (%s); using original query only", exc
            )

        return expanded[: num_expansions + 1]


# ---------------------------------------------------------------------------
# Context Deduplicator
# ---------------------------------------------------------------------------

class ContextDeduplicator:
    """
    Removes duplicate or near-duplicate documents from retrieved context.

    Edge cases:
    - Empty list → returns []
    - Documents with identical text → keeps first occurrence
    - Documents with empty text → excluded
    """

    def deduplicate(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Deduplicate retrieved documents by exact text match.

        Args:
            documents: List of retrieved document dicts.

        Returns:
            Deduplicated list preserving original order.
        """
        if not documents:
            logger.debug("ContextDeduplicator: empty input; returning []")
            return []

        seen: set = set()
        deduped: List[Dict[str, Any]] = []

        for doc in documents:
            text = (doc.get("text") or "").strip()
            if not text:
                logger.debug("ContextDeduplicator: skipping document with empty text")
                continue
            if text not in seen:
                seen.add(text)
                deduped.append(doc)

        logger.info(
            "ContextDeduplicator: %d → %d documents after deduplication",
            len(documents), len(deduped),
        )
        return deduped


# ---------------------------------------------------------------------------
# RAG Orchestrator
# ---------------------------------------------------------------------------

class RAGOrchestrator:
    """
    Orchestrates the RAG workflow using LangGraph.

    Workflow nodes (in order):
    1. expand_query   : Expand user query into multiple variants.
    2. retrieve       : Retrieve context for each expanded query.
    3. deduplicate    : Remove redundant context documents.
    4. generate       : Generate answer from deduplicated context.
    """

    def __init__(
        self,
        retriever,
        llm_client,
        query_expander: Optional[QueryExpander] = None,
        context_deduplicator: Optional[ContextDeduplicator] = None,
        max_context_docs: int = 10,
    ):
        """
        Initialise RAG orchestrator.

        Args:
            retriever             : HybridRetriever instance.
            llm_client            : OpenAI-compatible LLM client.
            query_expander        : Optional QueryExpander (created if None).
            context_deduplicator  : Optional ContextDeduplicator (created if None).
            max_context_docs      : Maximum context documents passed to generation.
        """
        self.retriever = retriever
        self.llm_client = llm_client
        self.query_expander = query_expander or QueryExpander(llm_client)
        self.context_deduplicator = context_deduplicator or ContextDeduplicator()
        self.max_context_docs = max_context_docs

        logger.info(
            "RAGOrchestrator initialised: max_context_docs=%d", max_context_docs
        )
        self.graph = self._build_graph()

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self) -> StateGraph:
        """Build and compile the LangGraph workflow."""
        workflow = StateGraph(dict)
        workflow.add_node("expand_query", self._expand_query_node)
        workflow.add_node("retrieve", self._retrieve_node)
        workflow.add_node("deduplicate", self._deduplicate_node)
        workflow.add_node("generate", self._generate_node)

        workflow.set_entry_point("expand_query")
        workflow.add_edge("expand_query", "retrieve")
        workflow.add_edge("retrieve", "deduplicate")
        workflow.add_edge("deduplicate", "generate")
        workflow.set_finish_point("generate")

        logger.info("LangGraph workflow compiled: expand_query → retrieve → deduplicate → generate")
        return workflow.compile()

    # ------------------------------------------------------------------
    # Graph nodes
    # ------------------------------------------------------------------

    def _expand_query_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node 1: Expand the user query."""
        t0 = time.perf_counter()
        original_query = state.get("original_query", "")
        logger.info("[Node: expand_query] query='%s...'", original_query[:60])

        expanded = self.query_expander.expand(original_query, num_expansions=3)
        state["expanded_queries"] = expanded
        state["expand_time"] = time.perf_counter() - t0

        logger.info(
            "[Node: expand_query] produced %d variants in %.2fs",
            len(expanded), state["expand_time"],
        )
        return state

    def _retrieve_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node 2: Retrieve context for all expanded queries."""
        t0 = time.perf_counter()
        expanded_queries = state.get("expanded_queries", [])
        namespace = state.get("namespace", "default")
        logger.info(
            "[Node: retrieve] %d queries → namespace='%s'",
            len(expanded_queries), namespace,
        )

        all_context: List[Dict[str, Any]] = []

        for i, query in enumerate(expanded_queries):
            logger.info("[Node: retrieve] query %d/%d: '%s...'", i + 1, len(expanded_queries), query[:50])
            try:
                results = self.retriever.retrieve(
                    query=query,
                    namespace=namespace,
                    top_k=5,
                    fetch_k=20,
                )
                all_context.extend(results)
                logger.info("[Node: retrieve] query %d returned %d docs", i + 1, len(results))
            except Exception as exc:
                logger.warning("[Node: retrieve] query %d failed: %s", i + 1, exc)

        state["retrieved_context"] = all_context
        state["retrieval_time"] = time.perf_counter() - t0

        logger.info(
            "[Node: retrieve] total %d docs retrieved in %.2fs",
            len(all_context), state["retrieval_time"],
        )
        return state

    def _deduplicate_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node 3: Deduplicate retrieved context."""
        t0 = time.perf_counter()
        retrieved = state.get("retrieved_context", [])
        logger.info("[Node: deduplicate] deduplicating %d docs", len(retrieved))

        deduped = self.context_deduplicator.deduplicate(retrieved)
        state["context_deduped"] = deduped
        state["dedup_time"] = time.perf_counter() - t0

        logger.info(
            "[Node: deduplicate] %d → %d docs in %.3fs",
            len(retrieved), len(deduped), state["dedup_time"],
        )
        return state

    def _generate_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node 4: Generate answer from deduplicated context."""
        t0 = time.perf_counter()
        original_query = state.get("original_query", "")
        context_docs = state.get("context_deduped", [])

        logger.info(
            "[Node: generate] query='%s...', context_docs=%d",
            original_query[:60], len(context_docs),
        )

        # --- Guard: no context ---
        if not context_docs:
            logger.warning("[Node: generate] no context available; returning fallback answer")
            state["generated_answer"] = (
                "I could not find relevant information in the knowledge base "
                "to answer your question. Please try rephrasing or check that "
                "the relevant documents have been ingested."
            )
            state["generation_time"] = time.perf_counter() - t0
            state["total_tokens"] = 0
            return state

        # Format context (limit to max_context_docs)
        docs_to_use = context_docs[: self.max_context_docs]
        context_text = "\n\n".join(
            f"[Source: {doc.get('metadata', {}).get('source', 'unknown')}]\n{doc.get('text', '')}"
            for doc in docs_to_use
        )

        generation_prompt = (
            f"Based ONLY on the following context, answer the user's question accurately "
            f"and concisely. If the context does not contain enough information, say so clearly.\n\n"
            f"Context:\n{context_text}\n\n"
            f"Question: {original_query}\n\n"
            f"Answer:"
        )

        try:
            response = self.llm_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a precise enterprise knowledge assistant. "
                            "Answer questions strictly based on the provided context. "
                            "Never fabricate information."
                        ),
                    },
                    {"role": "user", "content": generation_prompt},
                ],
                temperature=0.3,
                max_tokens=1000,
            )

            answer = response.choices[0].message.content or ""
            tokens = response.usage.total_tokens if response.usage else 0

            state["generated_answer"] = answer
            state["total_tokens"] = tokens

            logger.info(
                "[Node: generate] answer generated: %d chars, %d tokens",
                len(answer), tokens,
            )

        except Exception as exc:
            logger.error("[Node: generate] LLM call failed: %s", exc, exc_info=True)
            state["generated_answer"] = (
                f"Answer generation failed due to an internal error: {exc}. "
                "Please try again or contact support."
            )
            state["total_tokens"] = 0

        state["generation_time"] = time.perf_counter() - t0
        logger.info("[Node: generate] completed in %.2fs", state["generation_time"])
        return state

    # ------------------------------------------------------------------
    # Public run method
    # ------------------------------------------------------------------

    def run(
        self,
        query: str,
        namespace: str = "default",
        user_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Run the full RAG pipeline for a single query.

        Args:
            query    : User query string.
            namespace: Pinecone namespace to search.
            user_id  : User identifier for audit logging.

        Returns:
            Complete workflow state dict with 'generated_answer' and timing metadata.
        """
        if not query or not query.strip():
            logger.warning("RAGOrchestrator.run: empty query received")
            return {
                "original_query": query,
                "generated_answer": "Please provide a non-empty query.",
                "expanded_queries": [],
                "retrieved_context": [],
                "context_deduped": [],
                "total_tokens": 0,
            }

        logger.info(
            "RAGOrchestrator.run: START | user=%s | namespace=%s | query='%s...'",
            user_id, namespace, query[:60],
        )
        t_pipeline_start = time.perf_counter()

        initial_state: Dict[str, Any] = {
            "original_query": query.strip(),
            "namespace": namespace,
            "user_id": user_id,
            "expanded_queries": [],
            "retrieved_context": [],
            "context_deduped": [],
            "generated_answer": "",
            "total_tokens": 0,
            "expand_time": 0.0,
            "retrieval_time": 0.0,
            "dedup_time": 0.0,
            "generation_time": 0.0,
        }

        try:
            final_state = self.graph.invoke(initial_state)
        except Exception as exc:
            logger.error("RAGOrchestrator.run: pipeline failed: %s", exc, exc_info=True)
            initial_state["generated_answer"] = f"Pipeline error: {exc}"
            return initial_state

        total_time = time.perf_counter() - t_pipeline_start
        final_state["total_pipeline_time"] = total_time

        logger.info(
            "RAGOrchestrator.run: COMPLETE | %.2fs total | "
            "expand=%.2fs | retrieve=%.2fs | dedup=%.3fs | generate=%.2fs | tokens=%d",
            total_time,
            final_state.get("expand_time", 0),
            final_state.get("retrieval_time", 0),
            final_state.get("dedup_time", 0),
            final_state.get("generation_time", 0),
            final_state.get("total_tokens", 0),
        )
        return final_state
