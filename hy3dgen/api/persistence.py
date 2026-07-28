"""SQLite-backed persistence for ``JobResponse``.

A thin layer over the stdlib ``sqlite3`` module. The store is **optional**
\u2014 the manager works fine in-memory without one \u2014 but when configured it
gives us two useful properties:

1. Jobs survive a server restart (active jobs that were mid-flight when
   the process died are reloaded; the manager is responsible for
   re-queueing them if appropriate).
2. Job history isn't bounded by RAM, so the in-memory ``max_history``
   cap becomes a UI-friendly cache rather than a hard limit.

Design notes
------------
- Single-file SQLite, WAL journal mode for concurrent reads while a
  write is in flight. Connection-per-call so the writer doesn't block
  SSE subscribers reading job state.
- Schema is versioned via ``user_version`` pragma; future schema changes
  run migrations here.
- The store only mirrors ``JobResponse`` (the public API surface). It
  doesn't touch ``save_dir`` file contents \u2014 those still live in the
  ``SAVE_DIR`` directory and are loaded via the ``/files`` mount.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from hy3dgen.api.schemas import JobResponse, JobStatus


_DEFAULT_DB_PATH = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "hy3dgen", "archeon", "jobs.db",
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    uid          TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    created_at   TEXT,
    completed_at TEXT,
    file_path    TEXT,
    error        TEXT,
    -- request_blob stores the original job payload so the server can
    -- resume processing after a restart. It's NULL for jobs that were
    -- not submitted via the persistent backend.
    request_blob TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
"""


class JobStore:
    """SQLite-backed mirror of the in-memory job history.

    Thread-safe: each call opens a fresh connection, so writers and
    readers can run concurrently without locking each other out.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        # Open one connection for schema setup; subsequent calls open
        # their own short-lived connections.
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()
        self._lock = threading.Lock()

    # -- connections -----------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    # -- public API ------------------------------------------------------

    def upsert(self, job: JobResponse, request_payload: Optional[dict] = None) -> None:
        """Insert or update a job row. Safe to call from any thread."""
        blob = json.dumps(request_payload) if request_payload is not None else None
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (uid, status, created_at, completed_at, file_path, error, request_blob)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    status       = excluded.status,
                    created_at   = excluded.created_at,
                    completed_at = excluded.completed_at,
                    file_path    = excluded.file_path,
                    error        = excluded.error,
                    request_blob = COALESCE(excluded.request_blob, jobs.request_blob)
                """,
                (
                    job.uid,
                    job.status.value if hasattr(job.status, "value") else str(job.status),
                    job.created_at,
                    job.completed_at,
                    job.file_path,
                    job.error,
                    blob,
                ),
            )

    def get(self, uid: str) -> Optional[JobResponse]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE uid = ?", (uid,)).fetchone()
        return _row_to_job(row) if row else None

    def list(
        self,
        status: Optional[JobStatus] = None,
        limit: Optional[int] = None,
    ) -> list[JobResponse]:
        clauses: list[str] = []
        params: list = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value if hasattr(status, "value") else str(status))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM jobs{where} ORDER BY created_at DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_job(r) for r in rows if r]

    def delete(self, uid: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM jobs WHERE uid = ?", (uid,))
            return cur.rowcount > 0

    def delete_older_than(self, max_age_seconds: int) -> int:
        cutoff = datetime.utcnow().timestamp() - max_age_seconds
        with self._lock, self._connect() as conn:
            # Use ``strftime('%s', created_at)`` to convert the stored ISO
            # timestamp to a Unix epoch. SQLite's strftime handles the
            # ``YYYY-MM-DDTHH:MM:SS[.ffffff]`` shape produced by
            # ``datetime.utcnow().isoformat()`` (truncating sub-second
            # precision, which is fine for an age cutoff).
            cur = conn.execute(
                """
                DELETE FROM jobs
                WHERE status IN ('completed', 'failed', 'cancelled')
                  AND created_at IS NOT NULL
                  AND CAST(strftime('%s', substr(created_at, 1, 19)) AS INTEGER) < ?
                """,
                (int(cutoff),),
            )
            return cur.rowcount

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()
        return int(row["c"]) if row else 0

    def restore_all(self) -> Iterable[tuple[JobResponse, Optional[dict]]]:
        """Yield (job, request_payload) for every persisted job, oldest first.

        The manager calls this on startup to rehydrate the in-memory
        state. Active jobs (queued / processing) are returned so the
        manager can decide whether to re-queue them; terminal jobs are
        returned so the history is consistent across restarts.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at ASC"
            ).fetchall()
        for row in rows:
            job = _row_to_job(row)
            payload = None
            if row["request_blob"]:
                try:
                    payload = json.loads(row["request_blob"])
                except (TypeError, ValueError):
                    payload = None
            yield job, payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_job(row: sqlite3.Row) -> JobResponse:
    status_value = row["status"]
    try:
        status = JobStatus(status_value)
    except ValueError:
        # Unknown status (forward-compat); default to QUEUED so the UI
        # doesn't blow up on values it doesn't recognize.
        status = JobStatus.QUEUED
    return JobResponse(
        uid=row["uid"],
        status=status,
        created_at=row["created_at"] or "",
        completed_at=row["completed_at"],
        file_path=row["file_path"],
        error=row["error"],
    )
