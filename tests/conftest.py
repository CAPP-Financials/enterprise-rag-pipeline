"""
pytest configuration and shared fixtures.
"""
import sys
import os
import logging

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Configure logging for all tests
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/home/ubuntu/enterprise-rag-pipeline/test_run.log", mode="w"),
    ]
)
