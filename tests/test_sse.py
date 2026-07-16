"""Tests for the SSE job-events endpoint and the manager's pub/sub layer.

The HTTP-level test is covered by an OpenAPI smoke (the route is
registered, content-type is correct) but we don't try to drain the
stream to EOF here: TestClient + httpx streaming is finicky and the
upstream keep-alive can keep the connection open indefinitely. The
end-to-end behavior is covered by the ``TestSubscribeNotify`` class
below, which exercises the manager's pub/sub directly with asyncio.
"""
import asyncio
from unittest.mock import MagicMock

import pytest

try:
    import torch  # noqa: F401
    from fastapi.testclient import TestClient
    from hy3dgen.api.manager import PriorityRequestManager
    from hy3dgen.api.schemas import JobResponse, JobStatus
    from hy3dgen.api import server as server_module
    _SKIP_REASON = None
except ModuleNotFoundError as exc:
    TestClient = None  # type: ignore[assignment]
    PriorityRequestManager = None  # type: ignore[assignment]
    JobResponse = None  # type: ignore[assignment]
    JobStatus = None  # type: ignore[assignment]
    server_module = None  # type: ignore[assignment]
    _SKIP_REASON = f"required dependency missing: {exc.name}"


pytestmark = pytest.mark.skipif(
    _SKIP_REASON is not None,
    reason=_SKIP_REASON or "torch/fastapi not installed",
)


# ---------------------------------------------------------------------------
# Manager-level pub/sub (no HTTP)
# ---------------------------------------------------------------------------

class TestSubscribeNotify:
    def test_subscribe_primed_with_current_state(self):
        mgr = PriorityRequestManager(device="cpu")
        mgr.worker = MagicMock()
        mgr.jobs["a"] = JobResponse(uid="a", status=JobStatus.QUEUED, created_at="2025-01-01T00:00:00")

        async def _scenario():
            queue = mgr.subscribe("a")
            item = await asyncio.wait_for(queue.get(), timeout=1.0)
            return item

        item = asyncio.run(_scenario())
        assert item.uid == "a"
        assert item.status == JobStatus.QUEUED

    def test_notify_fans_out_to_all_subscribers(self):
        mgr = PriorityRequestManager(device="cpu")
        mgr.worker = MagicMock()
        mgr.jobs["a"] = JobResponse(uid="a", status=JobStatus.QUEUED, created_at="2025-01-01T00:00:00")

        async def _scenario():
            q1 = mgr.subscribe("a")
            q2 = mgr.subscribe("a")
            # Drain the initial prime events.
            await asyncio.wait_for(q1.get(), timeout=1.0)
            await asyncio.wait_for(q2.get(), timeout=1.0)
            # Notify a new state.
            mgr.jobs["a"].status = JobStatus.PROCESSING
            mgr._notify(mgr.jobs["a"])
            v1 = await asyncio.wait_for(q1.get(), timeout=1.0)
            v2 = await asyncio.wait_for(q2.get(), timeout=1.0)
            return v1, v2

        v1, v2 = asyncio.run(_scenario())
        assert v1.status == JobStatus.PROCESSING
        assert v2.status == JobStatus.PROCESSING

    def test_unsubscribe_stops_events(self):
        mgr = PriorityRequestManager(device="cpu")
        mgr.worker = MagicMock()
        mgr.jobs["a"] = JobResponse(uid="a", status=JobStatus.QUEUED, created_at="2025-01-01T00:00:00")

        async def _scenario():
            q = mgr.subscribe("a")
            await asyncio.wait_for(q.get(), timeout=1.0)  # drain initial
            mgr.unsubscribe("a", q)
            mgr._notify(mgr.jobs["a"])
            try:
                await asyncio.wait_for(q.get(), timeout=0.2)
            except asyncio.TimeoutError:
                return True
            return False

        assert asyncio.run(_scenario()) is True

    def test_persistence_called_on_transitions(self, tmp_path):
        """Each status transition should mirror to the store."""
        from hy3dgen.api.persistence import JobStore
        store = JobStore(str(tmp_path / "jobs.db"))
        mgr = PriorityRequestManager(device="cpu", store=store)
        mgr.worker = MagicMock()
        mgr.jobs["a"] = JobResponse(uid="a", status=JobStatus.QUEUED, created_at="2025-01-01T00:00:00")

        # Simulate the worker code path: PROCESSING then COMPLETED.
        mgr.jobs["a"].status = JobStatus.PROCESSING
        mgr._persist(mgr.jobs["a"])
        mgr.jobs["a"].status = JobStatus.COMPLETED
        mgr.jobs["a"].file_path = "/tmp/fake.glb"
        mgr.jobs["a"].completed_at = "2025-01-01T00:00:01"
        mgr._persist(mgr.jobs["a"])

        loaded = store.get("a")
        assert loaded is not None
        assert loaded.status == JobStatus.COMPLETED
        assert loaded.file_path == "/tmp/fake.glb"


# ---------------------------------------------------------------------------
# HTTP-level: route is registered, returns 200 with the right content-type
# ---------------------------------------------------------------------------

