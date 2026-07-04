# Enterprise RAG Pipeline

A production-grade Retrieval-Augmented Generation (RAG) pipeline designed to deliver highly relevant, consistent query responses for enterprise environments with 500+ distributed users.

## Architecture Highlights

This pipeline replaces baseline keyword-matching with a sophisticated architecture:

1. **Semantic Chunking**: Utilizes `sentence-transformers` to split documents at meaningful semantic boundaries rather than fixed character limits, preserving context and improving downstream retrieval accuracy.
2. **Enterprise Vector Storage**: Built on Pinecone with strict namespace isolation per business unit, ensuring data security and scalable performance.
3. **Hybrid Retrieval**: Combines dense vector similarity (OpenAI embeddings) with sparse keyword matching (BM25), intelligently weighted to capture both abstract concepts and specific enterprise terminology.
4. **MMR Diversity Filtering**: Applies Maximal Marginal Relevance (MMR) to the retrieval candidate pool, preventing redundant results and ensuring the LLM receives diverse, comprehensive context.
5. **LangGraph Orchestration**: Implements a stateful workflow that expands narrow queries into multiple variants before retrieval, broadening recall without sacrificing precision.
6. **RAGAS Evaluation Framework**: Includes automated metrics for Context Relevance, Faithfulness, Answer Relevance, and Context Precision to validate the target 40% improvement in query relevance scores.

## Project Structure

```text
enterprise-rag-pipeline/
├── src/
│   ├── ingestion/
│   │   └── chunking.py         # Semantic boundary detection
│   ├── retrieval/
│   │   ├── pinecone_store.py   # Pinecone integration & namespaces
│   │   └── hybrid_search.py    # BM25 + Dense retrieval + MMR
│   ├── orchestration/
│   │   └── graph.py            # LangGraph workflow & query expansion
│   ├── evaluation/
│   │   └── ragas_metrics.py    # Evaluation scoring pipeline
│   ├── __init__.py
│   └── config.py               # Configuration management
├── tests/
│   └── test_chunking.py        # Unit tests
├── config/
│   └── example_config.yaml     # Example configuration
├── data/                       # Directory for raw and processed data
├── main.py                     # CLI entrypoint
├── requirements.txt            # Python dependencies
└── README.md                   # This documentation
```

## Prerequisites

- Python 3.10+
- Pinecone API Key
- OpenAI API Key (or alternative LLM provider)

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set environment variables:
   ```bash
   export PINECONE_API_KEY="your-pinecone-api-key"
   export OPENAI_API_KEY="your-openai-api-key"
   ```

## Usage Guide

The pipeline provides a comprehensive Command-Line Interface (CLI) via `main.py`.

### 1. Ingesting Documents

Ingest a JSON file containing enterprise documents. Use namespaces to isolate data by business unit.

```bash
python main.py ingest --documents data/sample_docs.json --namespace finance --batch-size 100
```

*Expected document format:*
```json
[
  {
    "id": "doc_001",
    "text": "Q3 revenue increased by 15% due to strong performance in the cloud sector...",
    "source": "Q3_Earnings_Report.pdf",
    "business_unit": "finance"
  }
]
```

### 2. Querying the Pipeline

Execute a query against a specific namespace. The pipeline will automatically expand the query, perform hybrid retrieval, apply MMR filtering, and generate an answer.

```bash
python main.py query --query "What were the key drivers of Q3 revenue growth?" --namespace finance
```

To bypass the orchestration layer (query expansion) and perform simple retrieval:
```bash
python main.py query --query "Q3 revenue" --namespace finance --no-orchestrator
```

### 3. Evaluating Performance

Evaluate the pipeline's performance using the integrated RAGAS framework.

```bash
python main.py evaluate --queries data/test_queries.json --output evaluation_report.csv
```

*Expected test queries format:*
```json
[
  {
    "query": "What were the key drivers of Q3 revenue growth?",
    "answer": "Q3 revenue growth was driven by a 15% increase in the cloud sector.",
    "context": ["Q3 revenue increased by 15% due to strong performance in the cloud sector."]
  }
]
```

## Configuration

The pipeline can be configured via environment variables or a YAML configuration file. See `config/example_config.yaml` for all available options, including:

- Chunking sizes and overlap
- Semantic refinement toggles
- Retrieval `top_k` and `fetch_k` parameters
- MMR lambda weights
- Query expansion settings

To run with a specific configuration file:
```bash
python main.py query --query "Search text" --config custom_config.yaml
```

## Enterprise Deployment Considerations

For deploying to 500+ distributed users:

1. **API Integration**: Wrap the `RAGPipeline` class in a FastAPI or Flask application to serve requests over HTTP.
2. **Authentication**: Implement OAuth2 or SAML to authenticate users and automatically route them to their authorized Pinecone namespaces.
3. **Monitoring**: Connect the `EvaluationTracker` output to a dashboard (e.g., Grafana) to continuously monitor the RAGAS composite scores in production.
4. **Caching**: Implement semantic caching for frequent queries to reduce LLM costs and latency.
