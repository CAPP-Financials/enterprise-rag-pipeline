"""
Tests for semantic chunking module.
"""

import pytest
from src.ingestion.chunking import SemanticChunker, HybridChunker


def test_semantic_chunker_initialization():
    """Test that SemanticChunker initializes correctly."""
    chunker = SemanticChunker(
        similarity_threshold=0.5,
        min_chunk_size=50,
        max_chunk_size=200,
    )
    assert chunker.similarity_threshold == 0.5
    assert chunker.min_chunk_size == 50
    assert chunker.max_chunk_size == 200


def test_split_sentences():
    """Test sentence splitting."""
    chunker = SemanticChunker()
    text = "This is sentence one. This is sentence two! Is this sentence three? Yes."
    sentences = chunker.split_sentences(text)
    
    assert len(sentences) == 4
    assert sentences[0] == "This is sentence one."
    assert sentences[1] == "This is sentence two!"
    assert sentences[2] == "Is this sentence three?"
    assert sentences[3] == "Yes."


def test_hybrid_chunker_without_semantic():
    """Test hybrid chunker without semantic refinement."""
    chunker = HybridChunker(
        chunk_size=100,
        chunk_overlap=10,
        use_semantic_refinement=False,
    )
    
    text = "A" * 250
    chunks = chunker.chunk(text)
    
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_hybrid_chunker_with_semantic():
    """Test hybrid chunker with semantic refinement."""
    chunker = HybridChunker(
        chunk_size=100,
        chunk_overlap=10,
        use_semantic_refinement=True,
    )
    
    text = "This is a test document. It contains multiple sentences. We want to see if semantic chunking works properly. It should group related sentences together. This is a completely different topic about quantum physics. Quantum entanglement is fascinating."
    
    chunks = chunker.chunk(text)
    
    assert len(chunks) > 0
    # The exact number of chunks depends on the model, but it should run without errors
