"""Root conftest.py - sets offline mode for all tests to prevent network hangs."""
import os
import sys
import logging

# Force offline mode so sentence-transformers uses cached model
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

# Ensure src is importable
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
