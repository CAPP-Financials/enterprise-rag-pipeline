# Enterprise RAG Pipeline: Deployment and Implementation Guide

## Executive Summary

This guide provides step-by-step instructions for deploying the Enterprise RAG Pipeline to production environments serving 500+ distributed users. The pipeline is designed to achieve a **40% improvement in query relevance scores** through semantic chunking, hybrid retrieval, MMR diversity filtering, query expansion, and RAGAS-based evaluation.

## Architecture Overview

The Enterprise RAG Pipeline implements a five-layer architecture:

| Layer | Component | Purpose |
|-------|-----------|---------|
| **Ingestion** | Semantic Chunking | Split documents at meaning boundaries, not character limits |
| **Storage** | Pinecone with Namespaces | Enterprise-grade vector storage with data isolation per business unit |
| **Retrieval** | Hybrid Search + MMR | Dense + sparse retrieval with diversity filtering |
| **Orchestration** | LangGraph | Stateful workflow with query expansion |
| **Evaluation** | RAGAS Metrics | Automated quality assessment (Context Relevance, Faithfulness, Answer Relevance, Context Precision) |

## Pre-Deployment Checklist

Before deploying to production, ensure the following prerequisites are met:

- [ ] Python 3.10+ installed
- [ ] Pinecone account created with API key
- [ ] OpenAI account with API key (or alternative LLM provider configured)
- [ ] Docker installed (for containerized deployment)
- [ ] Kubernetes cluster available (for distributed deployment)
- [ ] Monitoring infrastructure (Prometheus, Grafana, or similar)
- [ ] Database for tracking evaluations (PostgreSQL recommended)

## Step 1: Environment Setup

### 1.1 Clone Repository and Install Dependencies

```bash
git clone <repository-url>
cd enterprise-rag-pipeline
pip install -r requirements.txt
```

### 1.2 Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Pinecone Configuration
PINECONE_API_KEY=your-pinecone-api-key
PINECONE_INDEX_NAME=enterprise-rag-index
PINECONE_ENVIRONMENT=us-east-1-aws

# OpenAI Configuration
OPENAI_API_KEY=your-openai-api-key

# Pipeline Configuration
CHUNK_SIZE=512
CHUNK_OVERLAP=50
RETRIEVAL_TOP_K=5
RETRIEVAL_FETCH_K=20
USE_MMR=true
ENABLE_QUERY_EXPANSION=true
NUM_QUERY_EXPANSIONS=3

# Evaluation Configuration
ENABLE_RAGAS=true
SAVE_EVALUATIONS=true

# Logging
LOG_LEVEL=INFO
```

### 1.3 Verify Installation

```bash
python -c "from src.retrieval.pinecone_store import PineconeVectorStore; print('✓ Installation successful')"
```

## Step 2: Data Ingestion

### 2.1 Prepare Documents

Create a JSON file with your enterprise documents. Each document should follow this structure:

```json
[
  {
    "id": "unique_doc_id",
    "text": "Full document text content...",
    "source": "document_source.pdf",
    "business_unit": "finance",
    "timestamp": "2024-01-15T10:30:00Z"
  }
]
```

### 2.2 Ingest Documents by Business Unit

The pipeline uses Pinecone namespaces to isolate data by business unit. Ingest documents separately for each unit:

```bash
# Finance documents
python main.py ingest --documents data/finance_docs.json --namespace finance

# HR documents
python main.py ingest --documents data/hr_docs.json --namespace hr

# Engineering documents
python main.py ingest --documents data/engineering_docs.json --namespace engineering
```

### 2.3 Monitor Ingestion Progress

The ingestion process logs progress in batches. For large-scale ingestion (millions of documents), consider:

- Parallel ingestion across multiple worker processes
- Batch size optimization (default: 100 documents per batch)
- Monitoring Pinecone index statistics

```bash
python -c "
from src.retrieval.pinecone_store import PineconeVectorStore
store = PineconeVectorStore()
for ns in store.list_namespaces():
    stats = store.get_namespace_stats(ns)
    print(f'{ns}: {stats[\"vector_count\"]} vectors')
"
```

## Step 3: Query Processing Pipeline

### 3.1 Single Query Processing

Test the pipeline with individual queries:

```bash
python main.py query --query "What is our Q3 revenue?" --namespace finance
```

The pipeline will:
1. Expand the query into 3 variants
2. Retrieve top 20 candidates per expanded query
3. Apply MMR filtering to select top 5 diverse results
4. Generate an answer grounded in the retrieved context

### 3.2 Batch Query Processing

For evaluating multiple queries:

```bash
python main.py evaluate --queries data/test_queries.json --output results/evaluation_report.csv
```

## Step 4: Evaluation and Monitoring

### 4.1 RAGAS Evaluation Metrics

The pipeline automatically evaluates generated answers using four RAGAS metrics:

| Metric | Definition | Target |
|--------|-----------|--------|
| **Context Relevance** | How relevant is the retrieved context to the query? | > 0.85 |
| **Faithfulness** | Is the answer grounded in the retrieved context? | > 0.90 |
| **Answer Relevance** | Does the answer address the query? | > 0.85 |
| **Context Precision** | Are the most relevant documents ranked highest? | > 0.80 |

### 4.2 Interpreting Evaluation Results

The composite score is the average of all four metrics. A 40% improvement means:

- **Baseline**: ~0.60 composite score (keyword-matching system)
- **Target**: ~0.84 composite score (semantic RAG system)

### 4.3 Continuous Monitoring

Set up monitoring dashboards to track:

- Average composite score per namespace
- Trend of individual metrics over time
- Query latency and token usage
- User satisfaction (if available)

## Step 5: Production Deployment

### 5.1 Containerized Deployment (Docker)

Create a `Dockerfile` for containerized deployment:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py", "query", "--query", "${QUERY}", "--namespace", "${NAMESPACE}"]
```

Build and run:

```bash
docker build -t enterprise-rag-pipeline:latest .
docker run -e PINECONE_API_KEY=$PINECONE_API_KEY -e OPENAI_API_KEY=$OPENAI_API_KEY enterprise-rag-pipeline:latest
```

### 5.2 API Service (FastAPI)

Wrap the pipeline in a REST API for distributed access:

```python
from fastapi import FastAPI
from src.config import ConfigManager
from src.retrieval.pinecone_store import PineconeVectorStore
from src.retrieval.hybrid_search import HybridRetriever
from src.orchestration.graph import RAGOrchestrator

app = FastAPI()
config = ConfigManager.from_env()
vector_store = PineconeVectorStore(api_key=config.pinecone.api_key)
retriever = HybridRetriever(dense_retriever=vector_store)
orchestrator = RAGOrchestrator(retriever=retriever, llm_client=...)

@app.post("/query")
async def query(query: str, namespace: str = "default"):
    result = orchestrator.run(query, namespace)
    return result
```

### 5.3 Kubernetes Deployment

For large-scale deployments, use Kubernetes:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-pipeline
spec:
  replicas: 3
  selector:
    matchLabels:
      app: rag-pipeline
  template:
    metadata:
      labels:
        app: rag-pipeline
    spec:
      containers:
      - name: rag-pipeline
        image: enterprise-rag-pipeline:latest
        env:
        - name: PINECONE_API_KEY
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: pinecone-api-key
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: openai-api-key
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
```

## Step 6: Optimization and Tuning

### 6.1 Chunking Strategy Optimization

Test different chunking configurations to find the optimal balance:

```python
configs = [
    {"chunk_size": 256, "chunk_overlap": 25},
    {"chunk_size": 512, "chunk_overlap": 50},
    {"chunk_size": 1024, "chunk_overlap": 100},
]

for config in configs:
    # Test and measure RAGAS scores
    pass
```

### 6.2 Retrieval Parameter Tuning

Adjust hybrid retrieval parameters based on evaluation results:

| Parameter | Effect | Tuning |
|-----------|--------|--------|
| `alpha` | Weight for dense vs sparse | Increase if missing rare terms, decrease if too noisy |
| `top_k` | Final results returned | Increase for more comprehensive answers |
| `fetch_k` | Candidates before MMR | Increase for better diversity, decrease for speed |
| `mmr_lambda` | Relevance vs diversity | Increase for more relevant results, decrease for diversity |

### 6.3 Query Expansion Tuning

Monitor the impact of query expansion:

```bash
# Without expansion
python main.py query --query "Q3 revenue" --namespace finance --no-orchestrator

# With expansion
python main.py query --query "Q3 revenue" --namespace finance
```

Compare RAGAS scores to determine if expansion improves results.

## Step 7: Security and Compliance

### 7.1 Data Isolation

The pipeline uses Pinecone namespaces to ensure strict data isolation:

- Finance documents → `namespace: finance`
- HR documents → `namespace: hr`
- Engineering documents → `namespace: engineering`

Queries are automatically routed to the appropriate namespace based on user permissions.

### 7.2 API Authentication

Implement OAuth2 or SAML for API authentication:

```python
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.post("/query")
async def query(query: str, token: str = Depends(oauth2_scheme)):
    # Verify token and extract user namespace
    namespace = get_user_namespace(token)
    result = orchestrator.run(query, namespace)
    return result
```

### 7.3 Audit Logging

Log all queries and evaluations for compliance:

```python
evaluation_tracker.record(
    query=query,
    context=context,
    answer=answer,
    scores=scores,
    metadata={
        "user_id": user_id,
        "namespace": namespace,
        "timestamp": datetime.now().isoformat(),
        "ip_address": request.client.host,
    }
)
```

## Troubleshooting

### Issue: Low RAGAS Scores

**Symptoms**: Composite score < 0.70

**Solutions**:
1. Increase `chunk_size` to preserve more context
2. Increase `fetch_k` to improve retrieval diversity
3. Enable query expansion if disabled
4. Check if documents are relevant to queries

### Issue: High Latency

**Symptoms**: Query processing takes > 5 seconds

**Solutions**:
1. Reduce `fetch_k` to decrease retrieval candidates
2. Disable query expansion
3. Use a faster embedding model (e.g., all-MiniLM-L6-v2)
4. Implement caching for frequent queries

### Issue: Pinecone Connection Errors

**Symptoms**: "Failed to connect to Pinecone"

**Solutions**:
1. Verify `PINECONE_API_KEY` is set correctly
2. Check network connectivity to Pinecone servers
3. Verify index name matches configuration
4. Check Pinecone account quota

## Performance Benchmarks

Expected performance on a standard deployment:

| Metric | Target | Notes |
|--------|--------|-------|
| Query Latency | < 3 seconds | Includes expansion, retrieval, and generation |
| Throughput | 100+ QPS | With 3 replicas |
| RAGAS Composite Score | > 0.84 | 40% improvement over baseline |
| Cost per Query | < $0.05 | Depends on LLM pricing |

## Support and Maintenance

For ongoing support:

1. Monitor RAGAS scores weekly
2. Update embeddings monthly as new documents are added
3. Retrain BM25 encoder quarterly
4. Review and optimize chunking strategy quarterly
5. Update dependencies monthly for security patches

## References

- [LangChain Documentation](https://python.langchain.com/)
- [Pinecone Documentation](https://docs.pinecone.io/)
- [RAGAS Evaluation Framework](https://docs.ragas.io/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
