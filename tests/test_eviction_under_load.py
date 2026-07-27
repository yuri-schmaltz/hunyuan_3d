"""
Stress test for eviction policy under load.

Builds a manager with 1000 jobs (mix of active and terminal),
sets ``max_history=100``, and verifies that ``evict_to_size``:
- Reduces the in-memory count to 100
- Keeps the most recent 100 jobs (by created_at)
- Never evicts active (queued/processing) jobs
- Returns the number of evicted jobs
"""
import asyncio
import uuid
from datetime import datetime, timedelta

import pytest

try:
    import torch  # noqa: F401
    from hy3dgen.api.manager import PriorityRequestManager
    from hy3dgen.api.schemas import JobResponse, JobStatus
    _SKIP_REASON = None
except ModuleNotFoundError as exc:
    _SKIP_REASON = f"required dep: {exc.name}"


pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "torch missing")


def _add(mgr, uid, status, age_seconds):
    job = JobResponse(
        uid=uid,
        status=status,
        created_at=(datetime.utcnow() - timedelta(seconds=age_seconds)).isoformat(),
    )
    if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        job.completed_at = datetime.utcnow().isoformat()
    mgr.jobs[uid] = job


async def test_evict_to_100_from_1000_keeps_newest():
    mgr = PriorityRequestManager(device="cpu", max_history=100)
    mgr.worker = type("W", (), {"generate": lambda *a, **k: "/tmp/fake.glb"})()

    # Add 1000 jobs with monotonic age (j0 oldest, j999 newest)
    for i in range(1000):
        # j0 has age=10000s, j999 has age=1s
        _add(mgr, f"j{i:04d}", JobStatus.COMPLETED, age_seconds=10_000 - i)

    assert len(mgr.jobs) == 1000
    removed = await mgr.evict_to_size()
    assert removed == 900
    assert len(mgr.jobs) == 100

    # The 100 newest (j0900..j0999) must remain.
    for i in range(900, 1000):
        assert f"j{i:04d}" in mgr.jobs, f"j{i:04d} should be kept"
    # The 900 oldest (j0000..j0899) must be gone.
    for i in range(0, 900):
        assert f"j{i:04d}" not in mgr.jobs, f"j{i:04d} should be evicted"


async def test_evict_never_removes_active_jobs():
    """A cap of 100 must NOT evict active jobs even if they're old."""
    mgr = PriorityRequestManager(device="cpu", max_history=100)
    mgr.worker = type("W", (), {"generate": lambda *a, **k: "/tmp/fake.glb"})()

    # 50 old active jobs (they should be PRESERVED)
    for i in range(50):
        _add(mgr, f"old-active-{i:03d}", JobStatus.PROCESSING, age_seconds=10_000)

    # 200 new completed jobs (cap will force eviction of some)
    for i in range(200):
        _add(mgr, f"new-done-{i:03d}", JobStatus.COMPLETED, age_seconds=100 - i)

    # 50 new active jobs
    for i in range(50):
        _add(mgr, f"new-active-{i:03d}", JobStatus.QUEUED, age_seconds=10 - i)

    assert len(mgr.jobs) == 300
    removed = await mgr.evict_to_size()
    # Cap is 100, but 100 active jobs must remain, so only completed
    # jobs are eligible for eviction.
    assert removed == 200  # the 200 new-done jobs
    assert len(mgr.jobs) == 100
    # All 100 old active + new active = 100 active jobs survive
    for i in range(50):
        assert f"old-active-{i:03d}" in mgr.jobs
        assert f"new-active-{i:03d}" in mgr.jobs
    # All new-done are gone
    for i in range(200):
        assert f"new-done-{i:03d}" not in mgr.jobs


async def test_evict_to_size_timing_1000_jobs():
    """Evicting 900 of 1000 jobs should complete in under 200ms."""
    import time
    mgr = PriorityRequestManager(device="cpu", max_history=100)
    mgr.worker = type("W", (), {"generate": lambda *a, **k: "/tmp/fake.glb"})()

    for i in range(1000):
        _add(mgr, f"j{i:04d}", JobStatus.COMPLETED, age_seconds=10_000 - i)

    t0 = time.perf_counter()
    removed = await mgr.evict_to_size()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert removed == 900
    assert elapsed_ms < 200, f"evict_to_size took {elapsed_ms:.1f}ms"
    print(f"\n[evict] 1000→100 in {elapsed_ms:.1f}ms")
