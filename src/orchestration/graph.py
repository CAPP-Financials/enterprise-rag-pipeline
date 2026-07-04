"""
LangGraph Orchestration Layer

Implements the RAG workflow as a directed graph with state management.
Orchestrates query expansion, retrieval, and generation steps.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
import logging

logger = logging.getLogger(__name__)


@dataclass
class RAGState:
    """
    State object for the RAG workflow.
    
    Tracks the progression of a query through the pipeline:
    1. Original query
    2. Expanded queries (for broader recall)
    3. Retrieved context
    4. Generated answer
    """
    
    # Input
    original_query: str
    user_id: str = "default"
    namespace: str = "default"
    
    # Processing
    expanded_queries: List[str] = field(default_factory=list)
    retrieved_context: List[Dict[str, Any]] = field(default_factory=list)
    context_deduped: List[Dict[str, Any]] = field(default_factory=list)
    
    # Output
    generated_answer: str = ""
    confidence_score: float = 0.0
    
    # Metadata
    retrieval_time: float = 0.0
    generation_time: float = 0.0
    total_tokens: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary."""
        return {
            "original_query": self.original_query,
            "user_id": self.user_id,
            "namespace": self.namespace,
            "expanded_queries": self.expanded_queries,
            "retrieved_context": self.retrieved_context,
            "context_deduped": self.context_deduped,
            "generated_answer": self.generated_answer,
            "confidence_score": self.confidence_score,
            "retrieval_time": self.retrieval_time,
            "generation_time": self.generation_time,
            "total_tokens": self.total_tokens,
        }


class QueryExpander:
    """
    Expands user queries to improve recall.
    
    Techniques:
    1. Rewrite: Rephrase the query in different ways
    2. Decompose: Break complex queries into sub-queries
    3. Step-back: Ask for abstract concepts first
    """
    
    def __init__(self, llm_client):
        """
        Initialize query expander.
        
        Args:
            llm_client: LLM client for query rewriting
        """
        self.llm_client = llm_client
    
    def expand(self, query: str, num_expansions: int = 3) -> List[str]:
        """
        Expand query into multiple variants.
        
        Args:
            query: Original query
            num_expansions: Number of query variants to generate
            
        Returns:
            List of expanded queries including the original
        """
        expanded = [query]  # Include original
        
        try:
            # Use LLM to generate query variants
            expansion_prompt = f"""Generate {num_expansions} alternative phrasings of this query that would help retrieve the same information. 
            
Original query: {query}

Generate {num_expansions} alternative phrasings (one per line, without numbering):"""
            
            response = self.llm_client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": "You are a query expansion expert. Generate alternative phrasings that preserve the original intent."},
                    {"role": "user", "content": expansion_prompt}
                ],
                temperature=0.7,
                max_tokens=500,
            )
            
            # Parse response
            variants = response.choices[0].message.content.strip().split("\n")
            for variant in variants:
                variant = variant.strip()
                if variant and variant not in expanded:
                    expanded.append(variant)
            
            logger.info(f"Expanded query into {len(expanded)} variants")
            
        except Exception as e:
            logger.warning(f"Query expansion failed: {e}. Using original query only.")
        
        return expanded[:num_expansions + 1]  # Return original + num_expansions


class ContextDeduplicator:
    """
    Deduplicates retrieved context to avoid redundancy.
    """
    
    def __init__(self, similarity_threshold: float = 0.9):
        """
        Initialize deduplicator.
        
        Args:
            similarity_threshold: Threshold for considering documents as duplicates
        """
        self.similarity_threshold = similarity_threshold
    
    def deduplicate(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove duplicate or near-duplicate documents.
        
        Args:
            documents: List of retrieved documents
            
        Returns:
            Deduplicated list of documents
        """
        if not documents:
            return []
        
        deduped = []
        seen_texts = set()
        
        for doc in documents:
            text = doc.get("text", "")
            
            # Simple deduplication: check if text is already seen
            # TODO: Implement semantic deduplication using embeddings
            if text not in seen_texts:
                deduped.append(doc)
                seen_texts.add(text)
        
        logger.info(f"Deduplicated {len(documents)} documents to {len(deduped)}")
        return deduped


class RAGOrchestrator:
    """
    Orchestrates the RAG workflow using LangGraph.
    
    Workflow:
    1. Query Expansion: Expand user query into multiple variants
    2. Retrieval: Retrieve context for each expanded query
    3. Deduplication: Remove redundant context
    4. Generation: Generate answer from deduplicated context
    5. Evaluation: Assess quality of generated answer
    """
    
    def __init__(
        self,
        retriever,
        llm_client,
        query_expander: Optional[QueryExpander] = None,
        context_deduplicator: Optional[ContextDeduplicator] = None,
    ):
        """
        Initialize RAG orchestrator.
        
        Args:
            retriever: Hybrid retriever instance
            llm_client: LLM client for query expansion and generation
            query_expander: Query expansion module
            context_deduplicator: Context deduplication module
        """
        self.retriever = retriever
        self.llm_client = llm_client
        self.query_expander = query_expander or QueryExpander(llm_client)
        self.context_deduplicator = context_deduplicator or ContextDeduplicator()
        
        # Build the graph
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """
        Build the LangGraph workflow.
        
        Returns:
            Compiled StateGraph
        """
        workflow = StateGraph(dict)
        
        # Add nodes
        workflow.add_node("expand_query", self._expand_query_node)
        workflow.add_node("retrieve", self._retrieve_node)
        workflow.add_node("deduplicate", self._deduplicate_node)
        workflow.add_node("generate", self._generate_node)
        
        # Add edges
        workflow.set_entry_point("expand_query")
        workflow.add_edge("expand_query", "retrieve")
        workflow.add_edge("retrieve", "deduplicate")
        workflow.add_edge("deduplicate", "generate")
        workflow.set_finish_point("generate")
        
        return workflow.compile()
    
    def _expand_query_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expand the user query.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with expanded queries
        """
        logger.info("Expanding query...")
        
        original_query = state.get("original_query", "")
        expanded_queries = self.query_expander.expand(original_query, num_expansions=3)
        
        state["expanded_queries"] = expanded_queries
        return state
    
    def _retrieve_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Retrieve context for expanded queries.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with retrieved context
        """
        logger.info("Retrieving context...")
        
        expanded_queries = state.get("expanded_queries", [])
        namespace = state.get("namespace", "default")
        
        all_context = []
        
        for query in expanded_queries:
            try:
                results = self.retriever.retrieve(
                    query=query,
                    namespace=namespace,
                    top_k=5,
                    fetch_k=20,
                )
                all_context.extend(results)
                logger.info(f"Retrieved {len(results)} documents for query: {query}")
            except Exception as e:
                logger.warning(f"Retrieval failed for query '{query}': {e}")
        
        state["retrieved_context"] = all_context
        return state
    
    def _deduplicate_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deduplicate retrieved context.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with deduplicated context
        """
        logger.info("Deduplicating context...")
        
        retrieved_context = state.get("retrieved_context", [])
        deduped_context = self.context_deduplicator.deduplicate(retrieved_context)
        
        state["context_deduped"] = deduped_context
        return state
    
    def _generate_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate answer from deduplicated context.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with generated answer
        """
        logger.info("Generating answer...")
        
        original_query = state.get("original_query", "")
        context_docs = state.get("context_deduped", [])
        
        # Format context
        context_text = "\n\n".join([
            f"[Source: {doc.get('metadata', {}).get('source', 'unknown')}]\n{doc.get('text', '')}"
            for doc in context_docs[:10]  # Limit to top 10 for token efficiency
        ])
        
        # Generate answer
        generation_prompt = f"""Based on the following context, answer the user's question. 
If the context does not contain relevant information, say so clearly.

Context:
{context_text}

User Question: {original_query}

Answer:"""
        
        try:
            response = self.llm_client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that answers questions based on provided context. Be concise and accurate."},
                    {"role": "user", "content": generation_prompt}
                ],
                temperature=0.7,
                max_tokens=1000,
            )
            
            answer = response.choices[0].message.content
            state["generated_answer"] = answer
            state["total_tokens"] = response.usage.total_tokens
            
            logger.info(f"Generated answer ({response.usage.total_tokens} tokens)")
            
        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            state["generated_answer"] = f"Error generating answer: {e}"
        
        return state
    
    def run(self, query: str, namespace: str = "default", user_id: str = "default") -> Dict[str, Any]:
        """
        Run the RAG pipeline for a query.
        
        Args:
            query: User query
            namespace: Namespace to search within
            user_id: User identifier for tracking
            
        Returns:
            Complete workflow state with answer
        """
        logger.info(f"Starting RAG pipeline for query: {query}")
        
        initial_state = {
            "original_query": query,
            "namespace": namespace,
            "user_id": user_id,
            "expanded_queries": [],
            "retrieved_context": [],
            "context_deduped": [],
            "generated_answer": "",
            "confidence_score": 0.0,
            "total_tokens": 0,
        }
        
        try:
            final_state = self.graph.invoke(initial_state)
            logger.info("RAG pipeline completed successfully")
            return final_state
        except Exception as e:
            logger.error(f"RAG pipeline failed: {e}")
            initial_state["generated_answer"] = f"Pipeline error: {e}"
            return initial_state
