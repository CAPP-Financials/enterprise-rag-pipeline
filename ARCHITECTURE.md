# Enterprise RAG Pipeline: Technical Architecture

## System Design Overview

The Enterprise RAG Pipeline is architected as a modular, scalable system designed to deliver high-relevance query responses to 500+ distributed enterprise users. The system replaces baseline keyword-matching with a sophisticated five-layer architecture that targets a 40% improvement in query relevance scores as measured by RAGAS metrics.

## Layer 1: Ingestion and Semantic Chunking

### Design Rationale

Traditional fixed-size chunking (e.g., 512 characters) often splits sentences mid-thought, fragmenting semantic meaning. The semantic chunking layer addresses this by detecting natural boundaries in text where semantic similarity drops significantly.

### Implementation Details

**Module**: `src/ingestion/chunking.py`

The `SemanticChunker` class implements the following workflow:

1. **Sentence Segmentation**: Split text into sentences using punctuation-based heuristics.
2. **Embedding Generation**: Encode each sentence using `sentence-transformers` (all-MiniLM-L6-v2 by default).
3. **Similarity Computation**: Calculate cosine similarity between consecutive sentence embeddings.
4. **Boundary Detection**: Identify semantic boundaries where similarity drops below a configurable threshold (default: 0.5).
5. **Chunk Assembly**: Group sentences into chunks respecting semantic boundaries while maintaining size constraints (min: 100 chars, max: 1000 chars).

**Key Trade-offs**:
- **Benefit**: Semantic chunks improve recall by up to 9% compared to fixed-size splitting.
- **Cost**: Requires embedding every sentence, increasing ingestion latency by ~30%.
- **Mitigation**: Batch embedding operations and cache results for repeated ingestion.

### Hybrid Chunking Strategy

For production deployments, the `HybridChunker` combines recursive character splitting (fast, reliable) with optional semantic refinement:

1. **Primary**: Recursive character splitting at 512-character boundaries with 50-character overlap.
2. **Optional Refinement**: Apply semantic chunking to chunks exceeding size thresholds.

This hybrid approach balances performance and quality.

## Layer 2: Enterprise Vector Storage

### Design Rationale

Pinecone provides a managed vector database optimized for similarity search at scale. The namespace-based isolation ensures strict data separation for multi-tenant enterprise deployments.

### Implementation Details

**Module**: `src/retrieval/pinecone_store.py`

The `PineconeVectorStore` class manages:

1. **Index Creation**: Serverless Pinecone index with cosine similarity metric.
2. **Namespace Isolation**: Each business unit (finance, HR, engineering, etc.) gets its own namespace.
3. **Batch Ingestion**: Vectorize and upsert documents in batches of 100 to optimize throughput.
4. **Metadata Enrichment**: Attach source, business unit, and timestamp metadata to each vector for filtering.

**Namespace Architecture**:

```
Pinecone Index: enterprise-rag-index
├── Namespace: finance
│   ├── Vector 1: Q3_Revenue_Report (metadata: source, business_unit, timestamp)
│   ├── Vector 2: Q3_Earnings_Call (metadata: ...)
│   └── ...
├── Namespace: hr
│   ├── Vector 1: Employee_Handbook (metadata: ...)
│   └── ...
└── Namespace: engineering
    ├── Vector 1: Technical_Spec (metadata: ...)
    └── ...
```

**Scaling Considerations**:
- Namespaces enable horizontal scaling: each business unit's data is independently queryable.
- Metadata filtering allows sub-namespace filtering (e.g., only documents from Q3 2024).
- Serverless spec auto-scales compute based on query volume.

## Layer 3: Hybrid Retrieval with MMR Diversity Filtering

### Design Rationale

Dense retrieval (vector similarity) captures semantic meaning but may miss exact terminology. Sparse retrieval (BM25) excels at keyword matching but lacks semantic understanding. Hybrid retrieval combines both, and MMR filtering ensures diversity.

### Implementation Details

**Module**: `src/retrieval/hybrid_search.py`

The `HybridRetriever` class implements a three-step retrieval pipeline:

#### Step 1: Dense Retrieval

```python
query_embedding = embeddings.embed_query(query)
dense_results = index.query(
    vector=query_embedding,
    top_k=fetch_k,  # Fetch more candidates for MMR
    namespace=namespace,
    filter=metadata_filters,
)
```

- Retrieve `fetch_k` (default: 20) candidates using vector similarity.
- Normalize scores to [0, 1] range.

#### Step 2: Sparse Retrieval (BM25)

```python
sparse_query = bm25_encoder.encode_query(query)
sparse_results = bm25_search(sparse_query, fetch_k)
```

- Encode query to sparse representation using BM25Encoder.
- Retrieve keyword-matching candidates.
- Note: Current implementation prioritizes dense retrieval; sparse integration is a future enhancement.

#### Step 3: Score Combination

```python
hybrid_score = alpha * dense_score + (1 - alpha) * sparse_score
```

- Default `alpha=0.5` gives equal weight to dense and sparse scores.
- Tunable parameter for different use cases.

#### Step 4: MMR Filtering

The `_mmr_filtering` method implements Maximal Marginal Relevance:

```
MMR_score = λ * Relevance - (1 - λ) * Diversity

where:
  Relevance = similarity(document, query)
  Diversity = min(similarity(document, already_selected))
  λ = trade-off parameter (default: 0.5)
```

**Algorithm**:
1. Initialize selected set with highest-scoring document.
2. Iteratively select documents that maximize MMR score.
3. Continue until `top_k` documents are selected.

**Result**: A diverse set of top-k results that balances relevance and coverage.

## Layer 4: LangGraph Orchestration

### Design Rationale

LangGraph provides a state-machine abstraction for complex workflows. The orchestration layer implements query expansion, retrieval, deduplication, and generation as explicit workflow nodes.

### Implementation Details

**Module**: `src/orchestration/graph.py`

The `RAGOrchestrator` class builds a directed graph with four nodes:

```
expand_query → retrieve → deduplicate → generate
```

#### Node 1: Query Expansion

```python
def _expand_query_node(state):
    original_query = state["original_query"]
    expanded_queries = query_expander.expand(original_query, num_expansions=3)
    state["expanded_queries"] = expanded_queries
    return state
```

The `QueryExpander` uses an LLM to generate query variants:

- **Rewrite**: Rephrase the query in different ways.
- **Decompose**: Break complex queries into sub-queries.
- **Step-back**: Ask for abstract concepts first.

**Example**:
- Original: "What is our Q3 revenue?"
- Variant 1: "How much revenue did we generate in the third quarter?"
- Variant 2: "Q3 financial performance and total earnings"
- Variant 3: "Third quarter revenue figures and metrics"

#### Node 2: Retrieval

```python
def _retrieve_node(state):
    expanded_queries = state["expanded_queries"]
    all_context = []
    for query in expanded_queries:
        results = retriever.retrieve(query, namespace, top_k=5, fetch_k=20)
        all_context.extend(results)
    state["retrieved_context"] = all_context
    return state
```

Retrieve context for each expanded query, aggregating results.

#### Node 3: Deduplication

```python
def _deduplicate_node(state):
    retrieved_context = state["retrieved_context"]
    deduped_context = context_deduplicator.deduplicate(retrieved_context)
    state["context_deduped"] = deduped_context
    return state
```

Remove duplicate or near-duplicate documents to reduce noise.

#### Node 4: Generation

```python
def _generate_node(state):
    original_query = state["original_query"]
    context_docs = state["context_deduped"]
    context_text = format_context(context_docs)
    
    response = llm.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\n{context_text}\n\nQuestion: {original_query}"}
        ],
    )
    state["generated_answer"] = response.choices[0].message.content
    return state
```

Generate answer grounded in deduplicated context.

### State Management

The `RAGState` dataclass tracks:

```python
@dataclass
class RAGState:
    original_query: str
    expanded_queries: List[str]
    retrieved_context: List[Dict]
    context_deduped: List[Dict]
    generated_answer: str
    confidence_score: float
    retrieval_time: float
    generation_time: float
    total_tokens: int
```

This explicit state tracking enables:
- Debugging: See exactly what happened at each step.
- Monitoring: Track latency and token usage.
- Evaluation: Correlate intermediate results with final quality.

## Layer 5: RAGAS Evaluation Framework

### Design Rationale

RAGAS provides reference-free evaluation of RAG systems, measuring the quality of retrieval and generation without requiring gold-standard answers.

### Implementation Details

**Module**: `src/evaluation/ragas_metrics.py`

The `RAGASEvaluator` class computes four metrics:

#### Metric 1: Context Relevance

**Definition**: How relevant is the retrieved context to the query?

**Computation**: LLM evaluates whether each retrieved chunk is relevant to the query.

**Interpretation**: 
- 1.0 = All retrieved chunks are relevant
- 0.0 = No retrieved chunks are relevant

**Target**: > 0.85

#### Metric 2: Faithfulness

**Definition**: Is the generated answer grounded in the retrieved context?

**Computation**: LLM identifies claims in the answer and verifies each claim against the context.

**Interpretation**:
- 1.0 = All claims are supported by context
- 0.0 = No claims are supported

**Target**: > 0.90

#### Metric 3: Answer Relevance

**Definition**: Does the answer address the original query?

**Computation**: LLM evaluates whether the answer is relevant to the query.

**Interpretation**:
- 1.0 = Answer fully addresses query
- 0.0 = Answer is completely irrelevant

**Target**: > 0.85

#### Metric 4: Context Precision

**Definition**: Are the most relevant documents ranked highest?

**Computation**: LLM identifies relevant documents and checks if they appear early in the ranking.

**Interpretation**:
- 1.0 = All relevant documents are ranked highest
- 0.0 = Relevant documents are ranked lowest

**Target**: > 0.80

### Composite Score

```
Composite Score = (Context Relevance + Faithfulness + Answer Relevance + Context Precision) / 4
```

**Baseline** (keyword-matching): ~0.60
**Target** (semantic RAG): ~0.84
**Improvement**: 40%

### Evaluation Tracking

The `EvaluationTracker` records all evaluations for monitoring:

```python
tracker.record(
    query=query,
    context=context,
    answer=answer,
    scores=scores,
    metadata={"user_id": user_id, "namespace": namespace}
)
```

Export to CSV for dashboard integration:

```python
tracker.export_to_csv("evaluation_report.csv")
```

## Configuration Management

**Module**: `src/config.py`

The `ConfigManager` supports two configuration modes:

### Mode 1: Environment Variables

```bash
export PINECONE_API_KEY=...
export CHUNK_SIZE=512
export RETRIEVAL_TOP_K=5
```

### Mode 2: YAML Configuration

```yaml
pinecone:
  api_key: ${PINECONE_API_KEY}
  index_name: enterprise-rag-index

chunking:
  chunk_size: 512
  use_semantic_refinement: true

retrieval:
  top_k: 5
  alpha: 0.5
  use_mmr: true
```

This flexibility enables:
- **Development**: Use environment variables for quick setup.
- **Production**: Use YAML files for version control and reproducibility.

## Performance Characteristics

### Latency Breakdown (per query)

| Component | Latency | Notes |
|-----------|---------|-------|
| Query Expansion | 0.5-1.0s | LLM call to generate variants |
| Retrieval (per query) | 0.1-0.2s | Pinecone similarity search |
| MMR Filtering | 0.1-0.2s | Embedding similarity computation |
| Deduplication | 0.05-0.1s | String comparison |
| Generation | 1.0-2.0s | LLM call to generate answer |
| **Total** | **2.0-4.0s** | End-to-end latency |

### Throughput

- **Single instance**: 10-20 queries per second
- **3 replicas**: 30-60 queries per second
- **10 replicas**: 100-200 queries per second

### Cost per Query

- Query expansion: ~0.01 USD (LLM call)
- Retrieval: ~0.001 USD (Pinecone)
- Generation: ~0.02 USD (LLM call)
- **Total**: ~0.03 USD per query

## Scaling Architecture

For 500+ distributed users:

1. **Horizontal Scaling**: Deploy multiple instances behind a load balancer.
2. **Namespace Isolation**: Each business unit's data is independently queryable.
3. **Caching**: Implement semantic caching for frequent queries (e.g., Redis).
4. **Batch Processing**: Process evaluation queries in batches to amortize LLM costs.
5. **Monitoring**: Use Prometheus + Grafana to track RAGAS scores and latency.

## Future Enhancements

1. **Sparse Retrieval Integration**: Full BM25 integration with Pinecone.
2. **Adaptive Query Expansion**: Learn which query variants work best for each namespace.
3. **Semantic Caching**: Cache embeddings and answers for frequent queries.
4. **Multi-hop Reasoning**: Support complex queries requiring multiple retrieval steps.
5. **Real-time Indexing**: Ingest new documents immediately via webhooks.
6. **Fine-tuned Embeddings**: Train custom embeddings on enterprise domain data.

## References

- [LangChain Documentation](https://python.langchain.com/)
- [Pinecone Documentation](https://docs.pinecone.io/)
- [RAGAS Evaluation Framework](https://docs.ragas.io/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Semantic Chunking Research](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)
