"""Shared pytest setup: make the repo root importable (so `import brief` works)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
