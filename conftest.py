"""Root conftest: make hy3dgen importable in tests without an install.

The repository layout uses implicit namespace packages (no __init__.py
in hy3dgen/api/), so ``import hy3dgen.api.manager`` only works if the
repo root is on sys.path. We add it here so all tests in tests/ can
import hy3dgen directly.
"""
import os
import sys

# Repo root is the parent of this conftest.py
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
