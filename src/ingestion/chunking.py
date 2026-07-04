"""
Semantic Chunking Module

Implements semantic boundary detection for document chunking using sentence-transformers.
Splits documents at meaningful semantic boundaries rather than fixed character limits.
"""

from typing import List, Tuple
import numpy as np
from sentence_transformers import SentenceTransformer, util
from langchain_text_splitters import RecursiveCharacterTextSplitter


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
            model_name: Sentence transformer model to use for embeddings
            similarity_threshold: Threshold for semantic boundary detection (0-1)
            min_chunk_size: Minimum characters per chunk
            max_chunk_size: Maximum characters per chunk
        """
        self.model = SentenceTransformer(model_name)
        self.similarity_threshold = similarity_threshold
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        
        # Fallback recursive splitter for very long sentences
        self.fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_chunk_size,
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )
    
    def split_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences using simple heuristics.
        
        Args:
            text: Text to split into sentences
            
        Returns:
            List of sentences
        """
        # Simple sentence splitting on periods, exclamation marks, and question marks
        sentences = []
        current_sentence = ""
        
        for char in text:
            current_sentence += char
            if char in ".!?":
                # Check if next char is space or end of text
                if current_sentence.strip():
                    sentences.append(current_sentence.strip())
                    current_sentence = ""
        
        # Add remaining text
        if current_sentence.strip():
            sentences.append(current_sentence.strip())
        
        return [s for s in sentences if len(s) > 0]
    
    def _find_semantic_boundaries(self, sentences: List[str]) -> List[int]:
        """
        Find semantic boundaries between sentences.
        
        Args:
            sentences: List of sentences
            
        Returns:
            List of indices where semantic boundaries occur
        """
        if len(sentences) < 2:
            return []
        
        # Embed all sentences
        embeddings = self.model.encode(sentences, convert_to_tensor=True)
        
        # Calculate cosine similarity between consecutive sentences
        boundaries = []
        for i in range(len(sentences) - 1):
            similarity = util.pytorch_cos_sim(embeddings[i], embeddings[i + 1]).item()
            
            # Mark boundary if similarity drops below threshold
            if similarity < self.similarity_threshold:
                boundaries.append(i + 1)
        
        return boundaries
    
    def chunk(self, text: str) -> List[str]:
        """
        Chunk text using semantic boundaries.
        
        Args:
            text: Text to chunk
            
        Returns:
            List of semantic chunks
        """
        # Split into sentences
        sentences = self.split_sentences(text)
        
        if len(sentences) < 2:
            # If text is too short, use fallback splitter
            return self.fallback_splitter.split_text(text)
        
        # Find semantic boundaries
        boundaries = self._find_semantic_boundaries(sentences)
        
        # Group sentences into chunks based on boundaries
        chunks = []
        current_chunk_sentences = []
        current_chunk_length = 0
        
        for i, sentence in enumerate(sentences):
            current_chunk_sentences.append(sentence)
            current_chunk_length += len(sentence)
            
            # Create chunk if:
            # 1. We hit a semantic boundary AND chunk is large enough, OR
            # 2. Chunk exceeds max size
            should_split = (i + 1 in boundaries and current_chunk_length >= self.min_chunk_size) or \
                          current_chunk_length >= self.max_chunk_size
            
            if should_split and current_chunk_sentences:
                chunk_text = " ".join(current_chunk_sentences)
                if len(chunk_text) > 0:
                    chunks.append(chunk_text)
                current_chunk_sentences = []
                current_chunk_length = 0
        
        # Add remaining sentences
        if current_chunk_sentences:
            chunk_text = " ".join(current_chunk_sentences)
            if len(chunk_text) > 0:
                chunks.append(chunk_text)
        
        # Ensure no chunk is too large (fallback)
        final_chunks = []
        for chunk in chunks:
            if len(chunk) > self.max_chunk_size:
                # Use fallback splitter for oversized chunks
                final_chunks.extend(self.fallback_splitter.split_text(chunk))
            else:
                final_chunks.append(chunk)
        
        return final_chunks


class HybridChunker:
    """
    Hybrid chunking strategy combining recursive character splitting with semantic refinement.
    
    Uses recursive character splitting as the primary strategy, then optionally
    applies semantic boundary detection for fine-tuning.
    """
    
    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        use_semantic_refinement: bool = False,
        semantic_model: str = "all-MiniLM-L6-v2",
    ):
        """
        Initialize the hybrid chunker.
        
        Args:
            chunk_size: Target chunk size in characters
            chunk_overlap: Overlap between chunks in characters
            use_semantic_refinement: Whether to apply semantic refinement
            semantic_model: Model for semantic refinement
        """
        self.recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )
        
        self.use_semantic_refinement = use_semantic_refinement
        if use_semantic_refinement:
            self.semantic_chunker = SemanticChunker(
                model_name=semantic_model,
                min_chunk_size=chunk_size // 2,
                max_chunk_size=chunk_size * 2,
            )
    
    def chunk(self, text: str) -> List[str]:
        """
        Chunk text using hybrid strategy.
        
        Args:
            text: Text to chunk
            
        Returns:
            List of chunks
        """
        # Primary: recursive character splitting
        chunks = self.recursive_splitter.split_text(text)
        
        # Optional: semantic refinement
        if self.use_semantic_refinement:
            refined_chunks = []
            for chunk in chunks:
                # Apply semantic chunking to each recursive chunk
                semantic_chunks = self.semantic_chunker.chunk(chunk)
                refined_chunks.extend(semantic_chunks)
            return refined_chunks
        
        return chunks
