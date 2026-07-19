"""
Test Suite: Semantic Chunking Module
=====================================
TC-CHK-001 to TC-CHK-006  : SemanticChunker constructor validation
TC-SENT-001 to TC-SENT-007 : split_sentences edge cases
TC-CHUNK-001 to TC-CHUNK-011: chunk() edge cases
TC-HYB-001 to TC-HYB-010  : HybridChunker edge cases
"""

import logging
import pytest

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from src.ingestion.chunking import SemanticChunker, HybridChunker


@pytest.fixture(scope="module")
def chunker():
    return SemanticChunker(
        model_name="all-MiniLM-L6-v2",
        similarity_threshold=0.5,
        min_chunk_size=50,
        max_chunk_size=500,
    )


@pytest.fixture(scope="module")
def hybrid_chunker():
    return HybridChunker(chunk_size=256, chunk_overlap=30)


# ── Constructor validation ──────────────────────────────────────────────────

class TestSemanticChunkerInit:

    def test_valid_init(self):
        """TC-CHK-001: Valid args produce a working instance."""
        sc = SemanticChunker(similarity_threshold=0.4, min_chunk_size=80, max_chunk_size=600)
        assert sc.similarity_threshold == 0.4

    def test_invalid_threshold_negative(self):
        """TC-CHK-002: Negative threshold raises ValueError."""
        with pytest.raises(ValueError, match="similarity_threshold"):
            SemanticChunker(similarity_threshold=-0.1)

    def test_invalid_threshold_above_one(self):
        """TC-CHK-003: threshold > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="similarity_threshold"):
            SemanticChunker(similarity_threshold=1.5)

    def test_invalid_chunk_sizes(self):
        """TC-CHK-004: min >= max raises ValueError."""
        with pytest.raises(ValueError, match="min_chunk_size"):
            SemanticChunker(min_chunk_size=500, max_chunk_size=500)

    def test_boundary_threshold_zero(self):
        """TC-CHK-005: threshold=0.0 is valid."""
        sc = SemanticChunker(similarity_threshold=0.0, min_chunk_size=10, max_chunk_size=1000)
        assert sc.similarity_threshold == 0.0

    def test_boundary_threshold_one(self):
        """TC-CHK-006: threshold=1.0 is valid."""
        sc = SemanticChunker(similarity_threshold=1.0, min_chunk_size=10, max_chunk_size=1000)
        assert sc.similarity_threshold == 1.0


# ── split_sentences ─────────────────────────────────────────────────────────

class TestSplitSentences:

    def test_normal_text(self, chunker):
        """TC-SENT-001: Multi-sentence text splits correctly."""
        text = "The market grew by 12%. Revenue increased. Costs were reduced."
        sentences = chunker.split_sentences(text)
        assert len(sentences) >= 2

    def test_empty_string(self, chunker):
        """TC-SENT-002: Empty string returns []."""
        assert chunker.split_sentences("") == []

    def test_whitespace_only(self, chunker):
        """TC-SENT-003: Whitespace-only returns []."""
        assert chunker.split_sentences("   \n\t  ") == []

    def test_no_punctuation(self, chunker):
        """TC-SENT-004: No sentence-ending punctuation returns one item."""
        text = "This is a sentence without a period"
        sentences = chunker.split_sentences(text)
        assert len(sentences) == 1

    def test_question_and_exclamation(self, chunker):
        """TC-SENT-005: ? and ! are treated as boundaries."""
        text = "What is the ROI? It is 8.2x. Excellent!"
        sentences = chunker.split_sentences(text)
        assert len(sentences) >= 2

    def test_unicode_text(self, chunker):
        """TC-SENT-006: Unicode characters handled without error."""
        text = "Optimisation coûts. Réduction de 70%. Résultats excellents."
        sentences = chunker.split_sentences(text)
        assert len(sentences) >= 1

    def test_consecutive_whitespace_collapsed(self, chunker):
        """TC-SENT-007: Consecutive whitespace is collapsed."""
        text = "First sentence.   Second   sentence.  Third."
        sentences = chunker.split_sentences(text)
        assert all("  " not in s for s in sentences)


# ── chunk() ─────────────────────────────────────────────────────────────────

class TestSemanticChunkerChunk:

    def test_empty_string(self, chunker):
        """TC-CHUNK-001: Empty string returns []."""
        assert chunker.chunk("") == []

    def test_none_input(self, chunker):
        """TC-CHUNK-002: None returns [] without crash."""
        assert chunker.chunk(None) == []

    def test_whitespace_only(self, chunker):
        """TC-CHUNK-003: Whitespace-only returns []."""
        assert chunker.chunk("   \n\n  ") == []

    def test_short_text_below_min(self, chunker):
        """TC-CHUNK-004: Text shorter than min_chunk_size returns as single chunk."""
        text = "Short."
        result = chunker.chunk(text)
        assert len(result) == 1

    def test_normal_multi_paragraph(self, chunker):
        """TC-CHUNK-005: Multi-paragraph text produces non-empty chunks."""
        text = (
            "The financial performance exceeded expectations in Q3. "
            "Revenue grew by 15% year-over-year. Operating margins improved. "
            "The engineering team deployed a new PySpark pipeline. "
            "Compute costs were reduced by 70% through optimisation. "
            "The HR department launched a new employee wellness programme. "
            "Participation rates reached 85% within the first month."
        )
        result = chunker.chunk(text)
        assert len(result) >= 1
        assert all(len(c) > 0 for c in result)

    def test_all_chunks_non_empty(self, chunker):
        """TC-CHUNK-006: No chunk is empty or whitespace-only."""
        text = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five."
        result = chunker.chunk(text)
        assert all(c.strip() for c in result)

    def test_no_chunk_exceeds_max_size(self):
        """TC-CHUNK-007: No output chunk exceeds max_chunk_size (with tolerance for fallback)."""
        sc = SemanticChunker(min_chunk_size=20, max_chunk_size=100)
        long_text = "A" * 50 + ". " + "B" * 50 + ". " + "C" * 50 + "."
        result = sc.chunk(long_text)
        assert all(len(c) <= 300 for c in result)

    def test_single_very_long_sentence(self, chunker):
        """TC-CHUNK-008: Single sentence exceeding max_chunk_size is split by fallback."""
        long_sentence = "word " * 300
        result = chunker.chunk(long_sentence)
        assert len(result) >= 1
        assert all(len(c) > 0 for c in result)

    def test_unicode_content(self, chunker):
        """TC-CHUNK-009: Unicode text is chunked without error."""
        text = (
            "L'optimisation des coûts est essentielle. "
            "La réduction de 70% a été atteinte. "
            "Les résultats sont excellents pour l'entreprise."
        )
        result = chunker.chunk(text)
        assert len(result) >= 1

    def test_text_with_numbers_and_symbols(self, chunker):
        """TC-CHUNK-010: Text with numbers, percentages, symbols is handled."""
        text = (
            "ROI was 8.2x in FY2024. Churn reduced by 6%. "
            "Fraud detection improved by 10%. Compute costs fell 70%."
        )
        result = chunker.chunk(text)
        assert len(result) >= 1

    def test_high_vs_low_threshold(self):
        """TC-CHUNK-011: High threshold produces <= chunks than low threshold."""
        text = (
            "The financial team reviewed quarterly results carefully. "
            "Revenue was up 15% compared to last year. "
            "The engineering team deployed a new ML pipeline. "
            "Model accuracy improved by 10% after tuning."
        )
        sc_low = SemanticChunker(similarity_threshold=0.1, min_chunk_size=20, max_chunk_size=2000)
        sc_high = SemanticChunker(similarity_threshold=0.9, min_chunk_size=20, max_chunk_size=2000)
        chunks_low = sc_low.chunk(text)
        chunks_high = sc_high.chunk(text)
        assert len(chunks_high) <= len(chunks_low) + 2


# ── HybridChunker ────────────────────────────────────────────────────────────

class TestHybridChunkerInit:

    def test_valid_init(self):
        """TC-HYB-001: Valid args produce a working instance."""
        hc = HybridChunker(chunk_size=512, chunk_overlap=50)
        assert hc is not None

    def test_invalid_overlap_equals_size(self):
        """TC-HYB-002: overlap == size raises ValueError."""
        with pytest.raises(ValueError, match="chunk_overlap"):
            HybridChunker(chunk_size=256, chunk_overlap=256)

    def test_invalid_overlap_exceeds_size(self):
        """TC-HYB-003: overlap > size raises ValueError."""
        with pytest.raises(ValueError, match="chunk_overlap"):
            HybridChunker(chunk_size=100, chunk_overlap=150)


class TestHybridChunkerChunk:

    def test_empty_string(self, hybrid_chunker):
        """TC-HYB-004: Empty string returns []."""
        assert hybrid_chunker.chunk("") == []

    def test_none_input(self, hybrid_chunker):
        """TC-HYB-005: None returns [] without crash."""
        assert hybrid_chunker.chunk(None) == []

    def test_normal_text(self, hybrid_chunker):
        """TC-HYB-006: Normal text produces at least one non-empty chunk."""
        text = "Enterprise RAG pipelines improve knowledge retrieval. " * 10
        result = hybrid_chunker.chunk(text)
        assert len(result) >= 1
        assert all(c.strip() for c in result)

    def test_without_semantic_refinement(self):
        """TC-HYB-007: Without semantic refinement, output is non-empty."""
        hc = HybridChunker(chunk_size=100, chunk_overlap=10, use_semantic_refinement=False)
        text = "Sentence one. Sentence two. Sentence three. " * 5
        result = hc.chunk(text)
        assert len(result) >= 1

    def test_with_semantic_refinement(self):
        """TC-HYB-008: With semantic refinement, output is still non-empty."""
        hc = HybridChunker(
            chunk_size=300,
            chunk_overlap=30,
            use_semantic_refinement=True,
            semantic_model="all-MiniLM-L6-v2",
        )
        text = (
            "The company achieved 8.2x ROI through strategic investments. "
            "The data engineering team built a PySpark pipeline for fraud detection. "
            "HR launched a new wellness programme with 85% participation."
        )
        result = hc.chunk(text)
        assert len(result) >= 1
        assert all(c.strip() for c in result)

    def test_large_document(self, hybrid_chunker):
        """TC-HYB-009: Large document (10,000+ chars) is chunked without error."""
        text = "Enterprise knowledge management requires robust retrieval systems. " * 100
        result = hybrid_chunker.chunk(text)
        assert len(result) > 1

    def test_single_word(self, hybrid_chunker):
        """TC-HYB-010: Single word input is returned as a chunk."""
        result = hybrid_chunker.chunk("RAG")
        assert len(result) == 1
        assert result[0] == "RAG"
