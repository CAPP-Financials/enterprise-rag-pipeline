"""
Configuration Management

Handles environment variables, settings, and configuration for the RAG pipeline.
"""

import os
from typing import Optional
from dataclasses import dataclass
import yaml
import logging

logger = logging.getLogger(__name__)


@dataclass
class PineconeConfig:
    """Pinecone configuration."""
    api_key: str
    index_name: str = "enterprise-rag-index"
    environment: str = "us-east-1-aws"
    embedding_model: str = "openai"
    embedding_dim: int = 1536
    metric: str = "cosine"


@dataclass
class EmbeddingConfig:
    """Embedding model configuration."""
    model_type: str = "openai"  # "openai" or "huggingface"
    model_name: str = "text-embedding-3-small"
    dimension: int = 1536


@dataclass
class ChunkingConfig:
    """Document chunking configuration."""
    chunk_size: int = 512
    chunk_overlap: int = 50
    use_semantic_refinement: bool = True
    semantic_model: str = "all-MiniLM-L6-v2"


@dataclass
class RetrievalConfig:
    """Retrieval configuration."""
    top_k: int = 5
    fetch_k: int = 20
    alpha: float = 0.5  # Weight for dense retrieval
    use_mmr: bool = True
    mmr_lambda: float = 0.5


@dataclass
class GenerationConfig:
    """LLM generation configuration."""
    model: str = "gpt-5-mini"
    temperature: float = 0.7
    max_tokens: int = 1000
    system_prompt: str = "You are a helpful assistant that answers questions based on provided context."


@dataclass
class EvaluationConfig:
    """Evaluation configuration."""
    enable_ragas: bool = True
    evaluation_batch_size: int = 10
    save_evaluations: bool = True
    evaluation_output_dir: str = "./evaluations"


@dataclass
class PipelineConfig:
    """Complete pipeline configuration."""
    pinecone: PineconeConfig
    embedding: EmbeddingConfig
    chunking: ChunkingConfig
    retrieval: RetrievalConfig
    generation: GenerationConfig
    evaluation: EvaluationConfig
    
    # Enterprise settings
    default_namespace: str = "default"
    enable_query_expansion: bool = True
    num_query_expansions: int = 3
    enable_context_deduplication: bool = True
    log_level: str = "INFO"


class ConfigManager:
    """
    Manages pipeline configuration from environment variables and config files.
    """
    
    @staticmethod
    def from_env() -> PipelineConfig:
        """
        Load configuration from environment variables.
        
        Returns:
            PipelineConfig object
        """
        logger.info("Loading configuration from environment variables")
        
        # Pinecone config
        pinecone_config = PineconeConfig(
            api_key=os.getenv("PINECONE_API_KEY", ""),
            index_name=os.getenv("PINECONE_INDEX_NAME", "enterprise-rag-index"),
            environment=os.getenv("PINECONE_ENVIRONMENT", "us-east-1-aws"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "openai"),
        )
        
        # Embedding config
        embedding_config = EmbeddingConfig(
            model_type=os.getenv("EMBEDDING_MODEL_TYPE", "openai"),
            model_name=os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small"),
        )
        
        # Chunking config
        chunking_config = ChunkingConfig(
            chunk_size=int(os.getenv("CHUNK_SIZE", "512")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "50")),
            use_semantic_refinement=os.getenv("USE_SEMANTIC_REFINEMENT", "true").lower() == "true",
        )
        
        # Retrieval config
        retrieval_config = RetrievalConfig(
            top_k=int(os.getenv("RETRIEVAL_TOP_K", "5")),
            fetch_k=int(os.getenv("RETRIEVAL_FETCH_K", "20")),
            alpha=float(os.getenv("RETRIEVAL_ALPHA", "0.5")),
            use_mmr=os.getenv("USE_MMR", "true").lower() == "true",
        )
        
        # Generation config
        generation_config = GenerationConfig(
            model=os.getenv("LLM_MODEL", "gpt-5-mini"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1000")),
        )
        
        # Evaluation config
        evaluation_config = EvaluationConfig(
            enable_ragas=os.getenv("ENABLE_RAGAS", "true").lower() == "true",
            save_evaluations=os.getenv("SAVE_EVALUATIONS", "true").lower() == "true",
        )
        
        return PipelineConfig(
            pinecone=pinecone_config,
            embedding=embedding_config,
            chunking=chunking_config,
            retrieval=retrieval_config,
            generation=generation_config,
            evaluation=evaluation_config,
            default_namespace=os.getenv("DEFAULT_NAMESPACE", "default"),
            enable_query_expansion=os.getenv("ENABLE_QUERY_EXPANSION", "true").lower() == "true",
            num_query_expansions=int(os.getenv("NUM_QUERY_EXPANSIONS", "3")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
    
    @staticmethod
    def from_yaml(filepath: str) -> PipelineConfig:
        """
        Load configuration from YAML file.
        
        Args:
            filepath: Path to YAML config file
            
        Returns:
            PipelineConfig object
        """
        logger.info(f"Loading configuration from {filepath}")
        
        with open(filepath, "r") as f:
            config_dict = yaml.safe_load(f)
        
        # Build config objects from dict
        pinecone_config = PineconeConfig(**config_dict.get("pinecone", {}))
        embedding_config = EmbeddingConfig(**config_dict.get("embedding", {}))
        chunking_config = ChunkingConfig(**config_dict.get("chunking", {}))
        retrieval_config = RetrievalConfig(**config_dict.get("retrieval", {}))
        generation_config = GenerationConfig(**config_dict.get("generation", {}))
        evaluation_config = EvaluationConfig(**config_dict.get("evaluation", {}))
        
        return PipelineConfig(
            pinecone=pinecone_config,
            embedding=embedding_config,
            chunking=chunking_config,
            retrieval=retrieval_config,
            generation=generation_config,
            evaluation=evaluation_config,
            **{k: v for k, v in config_dict.items() 
               if k not in ["pinecone", "embedding", "chunking", "retrieval", "generation", "evaluation"]}
        )
    
    @staticmethod
    def to_yaml(config: PipelineConfig, filepath: str) -> None:
        """
        Save configuration to YAML file.
        
        Args:
            config: PipelineConfig object
            filepath: Path to save YAML file
        """
        config_dict = {
            "pinecone": {
                "api_key": config.pinecone.api_key,
                "index_name": config.pinecone.index_name,
                "environment": config.pinecone.environment,
                "embedding_model": config.pinecone.embedding_model,
            },
            "embedding": {
                "model_type": config.embedding.model_type,
                "model_name": config.embedding.model_name,
                "dimension": config.embedding.dimension,
            },
            "chunking": {
                "chunk_size": config.chunking.chunk_size,
                "chunk_overlap": config.chunking.chunk_overlap,
                "use_semantic_refinement": config.chunking.use_semantic_refinement,
                "semantic_model": config.chunking.semantic_model,
            },
            "retrieval": {
                "top_k": config.retrieval.top_k,
                "fetch_k": config.retrieval.fetch_k,
                "alpha": config.retrieval.alpha,
                "use_mmr": config.retrieval.use_mmr,
                "mmr_lambda": config.retrieval.mmr_lambda,
            },
            "generation": {
                "model": config.generation.model,
                "temperature": config.generation.temperature,
                "max_tokens": config.generation.max_tokens,
            },
            "evaluation": {
                "enable_ragas": config.evaluation.enable_ragas,
                "save_evaluations": config.evaluation.save_evaluations,
            },
            "default_namespace": config.default_namespace,
            "enable_query_expansion": config.enable_query_expansion,
            "num_query_expansions": config.num_query_expansions,
            "log_level": config.log_level,
        }
        
        with open(filepath, "w") as f:
            yaml.dump(config_dict, f, default_flow_style=False)
        
        logger.info(f"Configuration saved to {filepath}")
