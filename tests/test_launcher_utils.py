"""Tests for utility functions in launcher.py.

The previous version of this file re-implemented every function it tested
inside the test body, which meant the suite could pass while the real
code had bugs. These tests import the real implementations and verify
their behaviour directly.
"""
import os
import random
import shutil
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest


MAX_SEED = int(1e7)


# ``launcher.py`` is a top-level script that pulls in torch, mmgp, and a
# large amount of the Hunyuan3D / gradio / fastapi stack. Importing the
# whole module just to test its pure utilities would force every test in
# this file to skip on a CPU-only runner. Instead we copy the pure
# functions we want to test into a minimal stand-alone module via exec,
# which is the standard technique for testing private functions of a
# script that is not a package.

# We extract only the two utility functions that are safe to test in
# isolation. This is preferable to refactoring launcher.py to expose
# them publicly because the launcher is a top-level UI script we don't
# own end-to-end.

_LAUNCHER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "launcher.py"
)
_LAUNCHER_SOURCE = Path(_LAUNCHER_PATH).read_text(encoding="utf-8")


def _extract(name: str) -> str:
    """Return the source of the top-level function ``name`` from launcher.py."""
    lines = _LAUNCHER_SOURCE.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith(f"def {name}("):
            start = i
            break
    if start is None:
        raise RuntimeError(f"Could not find {name} in launcher.py")
    # Walk forward until we dedent back to column 0 (or hit EOF).
    end = start + 1
    while end < len(lines) and (lines[end].startswith(" ") or lines[end] == ""):
        end += 1
    return "\n".join(lines[start:end])


# Compile a tiny module containing the two functions we want to test.
# We pre-populate the namespace with the same imports the real launcher.py
# has at module level so the extracted functions can use them.
import random as _random
import shutil as _shutil
import uuid as _uuid
import os as _os
from pathlib import Path as _Path

_ns: dict = {
    "__name__": "launcher_utils_under_test",
    "os": _os,
    "random": _random,
    "shutil": _shutil,
    "uuid": _uuid,
    "Path": _Path,
    "MAX_SEED": MAX_SEED,
    "SAVE_DIR": str(_Path.home() / ".cache" / "hy3dgen" / "launcher"),
    "logger": __import__("logging").getLogger("test"),
}
exec(
    compile(_extract("randomize_seed_fn"), "<launcher:randomize_seed_fn>", "exec"),
    _ns,
)
exec(
    compile(_extract("gen_save_folder"), "<launcher:gen_save_folder>", "exec"),
    _ns,
)
randomize_seed_fn = _ns["randomize_seed_fn"]
gen_save_folder = _ns["gen_save_folder"]


MAX_SEED = int(1e7)


# ---------------------------------------------------------------------------
# randomize_seed_fn
# ---------------------------------------------------------------------------

class TestRandomizeSeedFn:
    def test_returns_same_seed_when_not_randomizing(self):
        assert randomize_seed_fn(42, False) == 42

    def test_returns_random_seed_when_randomizing(self):
        result = randomize_seed_fn(42, True)
        assert 0 <= result <= MAX_SEED

    def test_float_input_is_handled_without_typeerror(self):
        """Gradio passes floats from number inputs; the function must coerce."""
        # randomize_seed_fn returns seed unchanged when randomize_seed=False,
        # so a float input would propagate. We treat that as a bug and assert
        # the function returns an int regardless.
        result = randomize_seed_fn(1234.0, False)
        assert isinstance(result, int), (
            f"randomize_seed_fn should coerce to int, got {type(result).__name__}"
        )

    def test_randomized_float_input_is_also_int(self):
        result = randomize_seed_fn(1234.0, True)
        assert isinstance(result, int)
        assert 0 <= result <= MAX_SEED

    def test_zero_seed_is_valid(self):
        assert randomize_seed_fn(0, False) == 0

    def test_max_seed_is_valid(self):
        assert randomize_seed_fn(MAX_SEED, False) == MAX_SEED

    def test_deterministic_with_same_random_state(self):
        random.seed(123)
        r1 = randomize_seed_fn(0, True)
        random.seed(123)
        r2 = randomize_seed_fn(0, True)
        assert r1 == r2

    def test_negative_seed_passes_through(self):
        # The function does not clamp; we just ensure it doesn't crash.
        assert randomize_seed_fn(-1, False) == -1


# ---------------------------------------------------------------------------
# gen_save_folder
# ---------------------------------------------------------------------------

class TestGenSaveFolder:
    def test_creates_folder_with_uuid_name(self, tmp_path, monkeypatch):
        # Patch the SAVE_DIR in the function's namespace so we don't touch
        # the user's real cache directory.
        import builtins
        real_makedirs = builtins.__import__("os").makedirs
        save_dir = str(tmp_path / "cache")
        real_makedirs(save_dir, exist_ok=True)
        # Re-execute the function with the patched SAVE_DIR.
        patched = _ns.copy()
        patched["SAVE_DIR"] = save_dir
        exec(
            compile(_extract("gen_save_folder"), "<launcher:gen_save_folder>", "exec"),
            patched,
        )
        fn = patched["gen_save_folder"]
        new_path = fn(max_size=10_000)
        assert os.path.isdir(new_path)
        assert os.path.dirname(new_path) == save_dir
        # Verify the directory name is a UUID.
        try:
            uuid.UUID(os.path.basename(new_path))
        except ValueError:
            pytest.fail(f"gen_save_folder produced non-UUID dirname: {new_path}")

    def test_max_size_enforced(self, tmp_path, monkeypatch):
        # Patch SAVE_DIR via monkeypatching the function's globals at call
        # time. We re-exec the function with a controlled SAVE_DIR.
        save_dir = str(tmp_path / "cache")
        os.makedirs(save_dir)
        # Re-execute the function with a patched SAVE_DIR.
        patched = _ns.copy()
        patched["SAVE_DIR"] = save_dir
        exec(
            compile(_extract("gen_save_folder"), "<launcher:gen_save_folder>", "exec"),
            patched,
        )
        fn = patched["gen_save_folder"]
        # Create max_size folders.
        max_size = 3
        for _ in range(max_size):
            fn(max_size=max_size)
        # The next call should evict the oldest.
        newest = fn(max_size=max_size)
        subdirs = list(Path(save_dir).iterdir())
        assert len(subdirs) == max_size
        assert newest in [str(p) for p in subdirs]
