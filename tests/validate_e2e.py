"""
End-to-end pipeline validation with realistic enterprise scenarios.
Tests all 5 business units, edge cases, and logs every step.
Run with: TRANSFORMERS_OFFLINE=1 python3 tests/validate_e2e.py
"""
import sys, os, logging, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

from unittest.mock import MagicMock
from src.ingestion.chunking import SemanticChunker, HybridChunker
from src.retrieval.hybrid_search import BM25RetrieverWrapper, HybridRetriever
from src.orchestration.graph import QueryExpander, ContextDeduplicator, RAGOrchestrator
from src.evaluation.ragas_metrics import RAGASScores, EvaluationTracker

results = []

def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, condition, detail))
    print(f"  [{status}]  {name}" + (f" -- {detail}" if detail else ""))
    return condition

print("\n" + "="*65)
print("ENTERPRISE RAG PIPELINE -- END-TO-END VALIDATION")
print("="*65)

corpus = [
    "ROI analysis shows 8.2x return on AI investments",
    "Churn reduction achieved 6% improvement with PySpark",
    "Fraud detection improved 10% with ML pipeline",
    "Green AI reduces compute costs by 70%",
    "Semantic search improves query relevance by 40%",
]

# ── 1. SEMANTIC CHUNKING ─────────────────────────────────────
print("\n[1] Semantic Chunking")
chunker = SemanticChunker(similarity_threshold=0.5, min_chunk_size=100, max_chunk_size=1000)

docs = [
    "The company achieved 8.2x ROI through strategic AI investments in 2024. "
    "This was measured against a baseline of traditional software deployments. "
    "The key driver was a PySpark market mix model that reduced churn by 6%.",
    "Green AI principles require optimising compute efficiency. "
    "Our RAG pipeline reduced inference costs by 70% through semantic caching. "
    "Batch processing replaced real-time calls where latency tolerance allowed.",
    "Fraud detection improved by 10% after deploying the ML pipeline. "
    "The model uses ensemble methods combining gradient boosting and neural networks. "
    "Real-time scoring latency was kept under 50ms at the 99th percentile.",
]
for i, doc in enumerate(docs):
    chunks = chunker.chunk(doc)
    check(f"Doc {i+1} produces >= 1 chunk", len(chunks) >= 1, f"{len(doc)} chars -> {len(chunks)} chunks")

check("Empty document -> 0 chunks", len(chunker.chunk("")) == 0)
check("None input -> 0 chunks", len(chunker.chunk(None)) == 0)
check("Single sentence -> >= 1 chunk", len(chunker.chunk("Hello world.")) >= 1)

# ── 2. HYBRID CHUNKER ────────────────────────────────────────
print("\n[2] HybridChunker")
hc = HybridChunker(chunk_size=200, chunk_overlap=30, use_semantic_refinement=False)
long_doc = " ".join(["Enterprise knowledge management requires sophisticated retrieval systems."] * 20)
chunks = hc.chunk(long_doc)
check("Long doc chunked correctly", len(chunks) >= 2, f"{len(long_doc)} chars -> {len(chunks)} chunks")
check("All chunks non-empty", all(len(c) > 0 for c in chunks))
check("No chunk exceeds 2x chunk_size", all(len(c) <= 400 for c in chunks))

# ── 3. BM25 RETRIEVER ────────────────────────────────────────
print("\n[3] BM25RetrieverWrapper")
bm25 = BM25RetrieverWrapper(corpus)
q_enc = bm25.encode_query("What is the ROI?")
check("BM25 encode_query returns non-empty dict", len(q_enc) > 0, f"{len(q_enc)} tokens")
corpus_enc = bm25.encode_corpus(corpus)
check("BM25 encode_corpus returns 5 vectors", len(corpus_enc) == 5)
check("Each corpus vector is a dict", all(isinstance(v, dict) for v in corpus_enc))
check("BM25 empty query -> empty dict", bm25.encode_query("") == {})
check("BM25 whitespace query -> empty dict", bm25.encode_query("   ") == {})

# ── 4. HYBRID RETRIEVER ──────────────────────────────────────
print("\n[4] HybridRetriever with MMR")

class MockDenseRetriever:
    def search(self, query, namespace="default", top_k=5, filters=None):
        if not query or not query.strip():
            return []
        return [
            {"id": f"doc_{i}", "text": corpus[i % len(corpus)],
             "score": 0.9 - i*0.05, "metadata": {"source": f"doc_{i}"}}
            for i in range(min(top_k, 10))
        ]

mock_dense = MockDenseRetriever()
retriever = HybridRetriever(dense_retriever=mock_dense, alpha=0.7, use_mmr=True, embedding_model="huggingface")
hybrid_results = retriever.retrieve("AI ROI investment", top_k=3, fetch_k=10)
check("Hybrid retrieve returns <= 3 results", len(hybrid_results) <= 3, f"got {len(hybrid_results)}")
check("Hybrid scores in [0,1]", all(0 <= r.get("hybrid_score", 0) <= 1 for r in hybrid_results))

r_clamp = HybridRetriever(dense_retriever=mock_dense, alpha=1.5, embedding_model="huggingface")
check("Alpha >1 clamped to 1.0", r_clamp.alpha == 1.0)
r_clamp2 = HybridRetriever(dense_retriever=mock_dense, alpha=-0.5, embedding_model="huggingface")
check("Alpha <0 clamped to 0.0", r_clamp2.alpha == 0.0)
check("Empty query -> 0 results", len(retriever.retrieve("", top_k=3)) == 0)

# ── 5. QUERY EXPANDER ────────────────────────────────────────
print("\n[5] QueryExpander")
mock_llm_client = MagicMock()
mock_llm_client.chat.completions.create.return_value = MagicMock(
    choices=[MagicMock(message=MagicMock(content="variant 1\nvariant 2\nvariant 3"))]
)
expander = QueryExpander(llm_client=mock_llm_client)
test_cases = [
    ("ROI", lambda e: len(e) >= 1),
    ("What is the churn reduction?", lambda e: len(e) >= 1),
    ("", lambda e: len(e) == 0),
    ("   ", lambda e: len(e) == 0),
]
for q, cond in test_cases:
    expanded = expander.expand(q)
    check(f"expand('{q[:30]}') -> {len(expanded)} variants", cond(expanded))

# ── 6. CONTEXT DEDUPLICATOR ──────────────────────────────────
print("\n[6] ContextDeduplicator")
dedup = ContextDeduplicator()
docs_with_dupes = [
    {"text": "The ROI was 8.2x.", "source": "doc1"},
    {"text": "The ROI was 8.2x.", "source": "doc2"},
    {"text": "Churn reduced by 6%.", "source": "doc3"},
    {"text": "", "source": "doc4"},
    {"text": "   ", "source": "doc5"},
]
deduped = dedup.deduplicate(docs_with_dupes)
check("Exact duplicates removed", len(deduped) < len(docs_with_dupes))
check("Empty text docs removed", all(d["text"].strip() for d in deduped))
check("Empty list -> empty list", dedup.deduplicate([]) == [])

# ── 7. RAG ORCHESTRATOR -- 5 NAMESPACES ──────────────────────
print("\n[7] RAGOrchestrator -- 5 Business Unit Namespaces")
mock_retriever = MagicMock()
mock_retriever.retrieve.return_value = [
    {"text": "The company achieved 8.2x ROI through strategic AI investments.", "source": "finance_report", "hybrid_score": 0.92},
    {"text": "Churn was reduced by 6% using a PySpark market mix model.", "source": "analytics_report", "hybrid_score": 0.88},
]
mock_llm_client2 = MagicMock()
mock_llm_client2.chat.completions.create.return_value = MagicMock(
    choices=[MagicMock(message=MagicMock(content="Based on the context, the ROI was 8.2x."))],
    usage=MagicMock(total_tokens=120)
)
orchestrator = RAGOrchestrator(
    retriever=mock_retriever,
    llm_client=mock_llm_client2,
    max_context_docs=5,
)

namespaces = ["finance", "hr", "engineering", "legal", "operations"]
for ns in namespaces:
    result = orchestrator.run(
        query=f"What are the key metrics for {ns}?",
        namespace=ns,
        user_id=f"user_{ns}_001",
    )
    check(
        f"Namespace '{ns}' returns generated_answer",
        bool(result.get("generated_answer")),
        f"answer='{str(result.get('generated_answer',''))[:40]}'"
    )

result_empty = orchestrator.run(query="", namespace="finance", user_id="u1")
check("Empty query handled gracefully", "generated_answer" in result_empty)

long_q = "What is the ROI? " * 50
result_long = orchestrator.run(query=long_q, namespace="finance", user_id="u2")
check("Very long query handled", "generated_answer" in result_long)

# ── 8. EVALUATION TRACKER ────────────────────────────────────
print("\n[8] EvaluationTracker")
tracker = EvaluationTracker()
check("Empty tracker stats == {}", tracker.get_statistics() == {})

sample_scores = [
    RAGASScores(0.85, 0.92, 0.88, 0.79),
    RAGASScores(0.78, 0.95, 0.82, 0.91),
    RAGASScores(0.91, 0.88, 0.94, 0.86),
]
for i, (q, s) in enumerate(zip(["ROI query", "Churn query", "Fraud query"], sample_scores)):
    tracker.record(q, [f"context_{i}"], f"answer_{i}", s, {"namespace": "test"})

stats = tracker.get_statistics()
check("total_evaluations == 3", stats["total_evaluations"] == 3)
check("avg_composite_score in [0,1]", 0 <= stats["avg_composite_score"] <= 1)
check("min <= avg <= max", stats["min_composite_score"] <= stats["avg_composite_score"] <= stats["max_composite_score"])

with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
    csv_path = f.name
tracker.export_to_csv(csv_path)
with open(csv_path) as f:
    lines = f.readlines()
check("CSV has header + 3 data rows", len(lines) == 4, f"got {len(lines)} lines")
check("CSV header contains 'query'", "query" in lines[0])
os.unlink(csv_path)

nan_score = RAGASScores(float("nan"), float("inf"), -0.5, 1.5)
check("NaN context_relevance -> 0.0", nan_score.context_relevance == 0.0)
check("Inf faithfulness -> 0.0 (invalid, clamped to safe default)", nan_score.faithfulness == 0.0)
check("Negative answer_relevance -> 0.0", nan_score.answer_relevance == 0.0)
check("context_precision > 1 -> 1.0", nan_score.context_precision == 1.0)

# ── SUMMARY ──────────────────────────────────────────────────
print("\n" + "="*65)
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f"VALIDATION SUMMARY: {passed} passed, {failed} failed out of {len(results)} checks")
if failed:
    print("\nFailed checks:")
    for name, ok, detail in results:
        if not ok:
            print(f"  [FAIL] {name}" + (f" -- {detail}" if detail else ""))
    sys.exit(1)
else:
    print("ALL VALIDATION CHECKS PASSED")
print("="*65)
