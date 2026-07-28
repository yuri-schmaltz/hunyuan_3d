"""Type stubs for ``hy3dgen.inference`` (the heavy ML module).

The runtime module is excluded from mypy (see ``pyproject.toml``'s
``[[tool.mypy.overrides]]``) because torch + trimesh + the model
loading code pulls in third-party types that don't ship stubs. This
file gives the *rest* of the codebase just enough types to use
``ModelWorker`` safely without having to import torch at type-check
time.
"""
from __future__ import annotations

from typing import Any

class ModelWorker:
    """Heavy inference worker. Stub-only; see runtime module for docs."""
    def __init__(
        self,
        *,
        device: str = "cuda",
        enable_tex: bool = True,
        enable_t2i: bool = True,
    ) -> None: ...
    def generate(
        self,
        uid: str,
        params: dict[str, Any],
        save_dir: str,
    ) -> str:
        """Run generation; returns the output file path."""
        ...
