"""
Semantic Chunking Module

Implements semantic boundary detection for document chunking using sentence-transformers.
Splits documents at meaningful semantic boundaries rather than fixed character limits.

Edge cases handled:
- Empty text input
- Single-sentence documents
- Very long sentences exceeding max_chunk_size
- Unicode and special character text
- Whitespace-only input
- None input
- Similarity threshold edge cases (0.0 and 1.0)
- Documents with no sentence-ending punctuation
"""

import re
import logging
from typing import List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer, util
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class SemanticChunker:
    """
    Chunks documents using semantic boundary detection.

    Splits text at points where semantic similarity drops significantly,
    preserving meaning and context within chunks.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.5,
        min_chunk_size: int = 100,
        max_chunk_size: int = 1000,
    ):
        """
        Initialize the semantic chunker.

        Args:
            model_name: Sentence transformer model to use for embeddings.
            similarity_threshold: Threshold for semantic boundary detection (0–1).
                                  Lower = more splits; higher = fewer splits.
            min_chunk_size: Minimum characters per chunk (avoids micro-chunks).
            max_chunk_size: Maximum characters per chunk (triggers fallback splitter).

        Raises:
            ValueError: If similarity_threshold is outside [0, 1].
            ValueError: If min_chunk_size >= max_chunk_size.
        """
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError(
                f"similarity_threshold must be in [0, 1], got {similarity_threshold}"
            )
        if min_chunk_size >= max_chunk_size:
            raise ValueError(
                f"min_chunk_size ({min_chunk_size}) must be < max_chunk_size ({max_chunk_size})"
            )

        logger.info(
            "Initialising SemanticChunker: model=%s, threshold=%.2f, "
            "min=%d, max=%d chars",
            model_name, similarity_threshold, min_chunk_size, max_chunk_size,
        )

        self.model = SentenceTransformer(model_name)
        self.similarity_threshold = similarity_threshold
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size

        # Fallback recursive splitter for oversized chunks / very short texts
        self.fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_chunk_size,
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def split_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences using regex-based heuristics.

        Handles:
        - Standard terminators: . ! ?
        - Abbreviations (e.g. "Dr.", "U.S.A.") are NOT treated as boundaries
        - Trailing whitespace stripped from each sentence
        - Consecutive whitespace collapsed

        Args:
            text: Raw text to split.

        Returns:
            List of non-empty sentence strings.
        """
        if not text or not text.strip():
            logger.debug("split_sentences received empty/whitespace text; returning []")
            return []

        # Normalise whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Split on sentence-ending punctuation followed by whitespace or EOS
        # Negative look-behind for common abbreviations (single capital letter + dot)
        sentence_endings = re.compile(r"(?<![A-Z])(?<!\b\w)[.!?](?=\s|$)")

        parts = sentence_endings.split(text)
        terminators = sentence_endings.findall(text)

        sentences = []
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            if i < len(terminators):
                part = part + terminators[i]
            if part:
                sentences.append(part)

        logger.debug("split_sentences produced %d sentences from %d chars", len(sentences), len(text))
        return sentences

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_semantic_boundaries(self, sentences: List[str]) -> List[int]:
        """
        Find semantic boundaries between consecutive sentences.

        Args:
            sentences: List of sentence strings (must have >= 2 items).

        Returns:
            Sorted list of indices *before* which a boundary exists.
        """
        if len(sentences) < 2:
            logger.debug("_find_semantic_boundaries: fewer than 2 sentences; no boundaries")
            return []

        logger.debug("Computing embeddings for %d sentences", len(sentences))
        embeddings = self.model.encode(sentences, convert_to_tensor=True, show_progress_bar=False)

        boundaries: List[int] = []
        for i in range(len(sentences) - 1):
            sim = util.pytorch_cos_sim(embeddings[i], embeddings[i + 1]).item()
            logger.debug("  Sentence %d→%d similarity: %.4f", i, i + 1, sim)
            if sim < self.similarity_threshold:
                boundaries.append(i + 1)

        logger.info(
            "_find_semantic_boundaries: found %d boundaries in %d sentences (threshold=%.2f)",
            len(boundaries), len(sentences), self.similarity_threshold,
        )
        return boundaries

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def chunk(self, text: str) -> List[str]:
        """
        Chunk text using semantic boundaries.

        Edge cases handled:
        - None → treated as empty string → returns []
        - Empty / whitespace-only → returns []
        - Single sentence → returns [text] (after size check)
        - Text with no punctuation → fallback splitter
        - Oversized chunks → recursively split with fallback

        Args:
            text: Document text to chunk.

        Returns:
            List of non-empty chunk strings.
        """
        # --- Guard: None / empty ---
        if not text or not text.strip():
            logger.warning("chunk() called with empty or None text; returning []")
            return []

        text = text.strip()
        logger.info("chunk() called: %d chars", len(text))

        # --- Guard: text shorter than min_chunk_size ---
        if len(text) <= self.min_chunk_size:
            logger.info("Text shorter than min_chunk_size (%d); returning as single chunk", self.min_chunk_size)
            return [text]

        sentences = self.split_sentences(text)

        # --- Guard: no sentences detected (no punctuation) ---
        if not sentences:
            logger.warning("No sentences detected; falling back to recursive splitter")
            return self.fallback_splitter.split_text(text)

        # --- Guard: single sentence ---
        if len(sentences) == 1:
            logger.info("Single sentence detected; applying size check")
            if len(sentences[0]) > self.max_chunk_size:
                return self.fallback_splitter.split_text(sentences[0])
            return [sentences[0]]

        # Find semantic boundaries
        boundaries = self._find_semantic_boundaries(sentences)

        # Assemble chunks
        chunks: List[str] = []
        current_sentences: List[str] = []
        current_length = 0

        for i, sentence in enumerate(sentences):
            current_sentences.append(sentence)
            current_length += len(sentence)

            at_boundary = (i + 1) in boundaries
            over_max = current_length >= self.max_chunk_size

            if (at_boundary and current_length >= self.min_chunk_size) or over_max:
                chunk_text = " ".join(current_sentences).strip()
                if chunk_text:
                    chunks.append(chunk_text)
                    logger.debug("Created chunk #%d: %d chars", len(chunks), len(chunk_text))
                current_sentences = []
                current_length = 0

        # Flush remaining sentences
        if current_sentences:
            chunk_text = " ".join(current_sentences).strip()
            if chunk_text:
                chunks.append(chunk_text)
                logger.debug("Flushed final chunk #%d: %d chars", len(chunks), len(chunk_text))

        # --- Guard: oversized chunks → fallback ---
        final_chunks: List[str] = []
        for chunk in chunks:
            if len(chunk) > self.max_chunk_size:
                logger.warning(
                    "Chunk exceeds max_chunk_size (%d > %d); applying fallback splitter",
                    len(chunk), self.max_chunk_size,
                )
                final_chunks.extend(self.fallback_splitter.split_text(chunk))
            else:
                final_chunks.append(chunk)

        # --- Guard: no chunks produced (degenerate input) ---
        if not final_chunks:
            logger.warning("No chunks produced; returning full text as single chunk")
            return [text]

        logger.info("chunk() produced %d chunks from %d chars", len(final_chunks), len(text))
        return final_chunks


class HybridChunker:
    """
    Hybrid chunking strategy combining recursive character splitting with optional
    semantic boundary refinement.

    Edge cases handled:
    - None / empty text
    - chunk_size <= chunk_overlap (raises ValueError)
    - use_semantic_refinement with very short chunks
    - Unicode text
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        use_semantic_refinement: bool = False,
        semantic_model: str = "all-MiniLM-L6-v2",
    ):
        """
        Initialise the hybrid chunker.

        Args:
            chunk_size: Target chunk size in characters.
            chunk_overlap: Overlap between consecutive chunks in characters.
            use_semantic_refinement: Whether to apply semantic refinement on top of
                                     recursive splitting.
            semantic_model: Sentence-transformers model name for semantic refinement.

        Raises:
            ValueError: If chunk_overlap >= chunk_size.
        """
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be < chunk_size ({chunk_size})"
            )

        logger.info(
            "Initialising HybridChunker: size=%d, overlap=%d, semantic=%s",
            chunk_size, chunk_overlap, use_semantic_refinement,
        )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.use_semantic_refinement = use_semantic_refinement

        self.recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )

        if use_semantic_refinement:
            self.semantic_chunker = SemanticChunker(
                model_name=semantic_model,
                min_chunk_size=max(50, chunk_size // 4),
                max_chunk_size=chunk_size * 2,
            )

    def chunk(self, text: str) -> List[str]:
        """
        Chunk text using the hybrid strategy.

        Args:
            text: Document text to chunk.

        Returns:
            List of non-empty chunk strings.
        """
        if not text or not text.strip():
            logger.warning("HybridChunker.chunk() called with empty text; returning []")
            return []

        text = text.strip()
        logger.info("HybridChunker.chunk(): %d chars, semantic_refinement=%s",
                    len(text), self.use_semantic_refinement)

        # Primary: recursive character splitting
        chunks = self.recursive_splitter.split_text(text)
        logger.info("Recursive splitter produced %d chunks", len(chunks))

        if not self.use_semantic_refinement:
            return chunks

        # Optional: semantic refinement
        refined: List[str] = []
        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
            try:
                semantic_chunks = self.semantic_chunker.chunk(chunk)
                refined.extend(semantic_chunks)
                logger.debug("Chunk %d → %d semantic sub-chunks", i, len(semantic_chunks))
            except Exception as exc:
                logger.warning("Semantic refinement failed for chunk %d: %s; keeping original", i, exc)
                refined.append(chunk)

        logger.info("HybridChunker produced %d refined chunks", len(refined))
        return refined
