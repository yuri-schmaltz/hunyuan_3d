"""Tests for the SQLite-backed ``JobStore``."""
import os
import tempfile
from datetime import datetime, timedelta

import pytest

try:
    import torch  # noqa: F401
    from hy3dgen.api.persistence import JobStore
    from hy3dgen.api.schemas import JobResponse, JobStatus
    _SKIP_REASON = None
except ModuleNotFoundError as exc:
    JobStore = None  # type: ignore[assignment]
    JobResponse = None  # type: ignore[assignment]
    JobStatus = None  # type: ignore[assignment]
    _SKIP_REASON = f"required dependency missing: {exc.name}"


pytestmark = pytest.mark.skipif(
    _SKIP_REASON is not None,
    reason=_SKIP_REASON or "torch not installed",
)


@pytest.fixture
def store(tmp_path):
    """Fresh JobStore backed by a per-test SQLite file."""
    db = tmp_path / "jobs.db"
    s = JobStore(str(db))
    yield s
    # The connection is per-call; nothing to close.


def _make_job(uid, status=JobStatus.QUEUED, age_seconds=0):
    return JobResponse(
        uid=uid,
        status=status,
        created_at=(datetime.utcnow() - timedelta(seconds=age_seconds)).isoformat(),
    )


class TestUpsertAndGet:
    def test_insert_then_get(self, store):
        job = _make_job("a")
        store.upsert(job)
        loaded = store.get("a")
        assert loaded is not None
        assert loaded.uid == "a"
        assert loaded.status == JobStatus.QUEUED

    def test_upsert_overwrites_existing(self, store):
        store.upsert(_make_job("a", status=JobStatus.QUEUED))
        store.upsert(_make_job("a", status=JobStatus.PROCESSING))
        loaded = store.get("a")
        assert loaded.status == JobStatus.PROCESSING

    def test_get_missing_returns_none(self, store):
        assert store.get("does-not-exist") is None

    def test_persists_request_payload(self, store):
        payload = {"type": "text_to_3d", "prompt": "hi", "steps": 5}
        store.upsert(_make_job("a"), request_payload=payload)
        # restore_all should surface both the job and the payload.
        rows = list(store.restore_all())
        assert len(rows) == 1
        loaded_job, loaded_payload = rows[0]
        assert loaded_job.uid == "a"
        assert loaded_payload == payload

    def test_payload_not_overwritten_when_not_provided(self, store):
        store.upsert(_make_job("a"), request_payload={"first": True})
        store.upsert(_make_job("a"))  # no payload
        rows = list(store.restore_all())
        assert rows[0][1] == {"first": True}


class TestList:
    def test_list_returns_all_jobs(self, store):
        for i in range(5):
            store.upsert(_make_job(f"j{i}"))
        jobs = store.list()
        assert len(jobs) == 5

    def test_list_filter_by_status(self, store):
        store.upsert(_make_job("a", status=JobStatus.QUEUED))
        store.upsert(_make_job("b", status=JobStatus.COMPLETED))
        store.upsert(_make_job("c", status=JobStatus.COMPLETED))
        completed = store.list(status=JobStatus.COMPLETED)
        assert {j.uid for j in completed} == {"b", "c"}

    def test_list_with_limit(self, store):
        for i in range(10):
            store.upsert(_make_job(f"j{i:02d}"))
        jobs = store.list(limit=3)
        assert len(jobs) == 3


class TestDelete:
    def test_delete_returns_true_for_existing(self, store):
        store.upsert(_make_job("a"))
        assert store.delete("a") is True
        assert store.get("a") is None

    def test_delete_returns_false_for_missing(self, store):
        assert store.delete("does-not-exist") is False

    def test_delete_older_than_removes_only_terminal(self, store):
        store.upsert(_make_job("old-done", status=JobStatus.COMPLETED, age_seconds=10**6))
        store.upsert(_make_job("old-failed", status=JobStatus.FAILED, age_seconds=10**6))
        store.upsert(_make_job("recent-done", status=JobStatus.COMPLETED, age_seconds=5))
        store.upsert(_make_job("active", status=JobStatus.QUEUED, age_seconds=10**6))
        removed = store.delete_older_than(max_age_seconds=3600)
        assert removed == 2
        assert store.get("old-done") is None
        assert store.get("old-failed") is None
        assert store.get("recent-done") is not None
        assert store.get("active") is not None


class TestRestore:
    def test_restore_yields_oldest_first(self, store):
        # Out-of-order insert; restore_all must return them sorted by
        # created_at ASC.
        store.upsert(_make_job("newer", age_seconds=5))
        store.upsert(_make_job("older", age_seconds=100))
        uids = [row[0].uid for row in store.restore_all()]
        assert uids == ["older", "newer"]


class TestCount:
    def test_count(self, store):
        assert store.count() == 0
        store.upsert(_make_job("a"))
        store.upsert(_make_job("b"))
        assert store.count() == 2
