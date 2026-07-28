"""SQLite-backed persistence for ``JobResponse``.

Async (via ``aiosqlite``) so the FastAPI handlers and the manager's
worker loop can ``await`` store calls instead of blocking the event
loop. Same schema and semantics as the previous sync version; the
public API moved from sync to async.

Design notes
------------
- Single-file SQLite, WAL journal mode for concurrent reads while a
  write is in flight. ``aiosqlite`` opens a fresh connection per call
  by default; the writer doesn't block SSE subscribers reading job
  state.
- Schema is versioned via the ``user_version`` pragma; future schema
  changes run migrations here.
- The store only mirrors ``JobResponse`` (the public API surface).
  It doesn't touch ``save_dir`` file contents — those still live in
  the ``SAVE_DIR`` directory and are loaded via the ``/files`` mount.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import aiosqlite

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
    request_blob TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
"""


class JobStore:
    """Async SQLite-backed mirror of the in-memory job history.

    Thread-safe AND asyncio-safe: every call opens a fresh
    ``aiosqlite`` connection. The underlying sqlite3 driver serialises
    writes (with WAL), and aiosqlite lets multiple coroutines share
    the same connection via its internal lock — so we don't need our
    own threading.Lock any more.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        # Open one connection for schema setup; subsequent calls open
        # their own short-lived connections.
        self._init_schema_sync()

    def _init_schema_sync(self) -> None:
        """Run CREATE TABLE / CREATE INDEX synchronously at startup.

        We use the sync sqlite3 here so the schema is in place before
        the first async request lands. The rest of the API is async.
        """
        with self._connect_sync() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    # -- connections -----------------------------------------------------

    def _connect_sync(self) -> sqlite3.Connection:
        """Sync connection (used only for initial schema setup)."""
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _connect(self) -> aiosqlite.Connection:
        """Open a new async connection. Use ``async with`` to start it.

        The function itself is sync (returns the ``Connection``). Use
        ``async with self._connect() as conn:`` so the connection's
        ``__aenter__`` handles the awaiting (starting the worker
        thread). Calling ``await self._connect()`` first would start
        the thread, and then ``__aenter__`` would fail with
        "threads can only be started once".

        The row_factory and pragmas are set inside ``__aenter__``
        (via ``_setup_connection``) because the underlying sqlite3
        connection only exists once the worker thread is running.
        """
        conn = aiosqlite.connect(self._db_path, timeout=5.0)
        return conn

    @staticmethod
    async def _setup_connection(conn: aiosqlite.Connection) -> None:
        """Run pragmas + set row_factory on a fresh, already-active connection.

        Must be called *inside* the ``async with`` block, after the
        connection's worker thread is running. The aiosqlite
        ``Connection.row_factory`` setter raises
        ``ValueError("no active connection")`` if called before the
        connection is entered.
        """
        conn.row_factory = sqlite3.Row
        await conn.execute("PRAGMA journal_mode = WAL;")
        await conn.execute("PRAGMA synchronous = NORMAL;")

    # -- public API ------------------------------------------------------

    async def upsert(
        self, job: JobResponse, request_payload: dict | None = None
    ) -> None:
        """Insert or update a job row. Safe to call from any coroutine."""
        blob = json.dumps(request_payload) if request_payload is not None else None
        async with self._connect() as conn:
            await self._setup_connection(conn)
            await conn.execute(
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
            await conn.commit()

    async def get(self, uid: str) -> JobResponse | None:
        async with self._connect() as conn:
            await self._setup_connection(conn)
            async with conn.execute(
                "SELECT * FROM jobs WHERE uid = ?", (uid,)
            ) as cur:
                row = await cur.fetchone()
        return _row_to_job(row) if row else None

    async def list(
        self,
        status: JobStatus | None = None,
        limit: int | None = None,
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
        async with self._connect() as conn:
            await self._setup_connection(conn)
            async with conn.execute(sql, params) as cur:
                rows = await cur.fetchall()
        return [_row_to_job(r) for r in rows if r]

    async def delete(self, uid: str) -> bool:
        async with self._connect() as conn:
            await self._setup_connection(conn)
            async with conn.execute(
                "DELETE FROM jobs WHERE uid = ?", (uid,)
            ) as cur:
                await cur.fetchone()  # drain any pending row
            await conn.commit()
            return cur.rowcount > 0

    async def delete_older_than(self, max_age_seconds: int) -> int:
        cutoff = datetime.utcnow().timestamp() - max_age_seconds
        async with self._connect() as conn:
            await self._setup_connection(conn)
            cur = await conn.execute(
                """
                DELETE FROM jobs
                WHERE status IN ('completed', 'failed', 'cancelled')
                  AND created_at IS NOT NULL
                  AND CAST(strftime('%s', substr(created_at, 1, 19)) AS INTEGER) < ?
                """,
                (int(cutoff),),
            )
            await conn.commit()
            return cur.rowcount or 0

    async def count(self) -> int:
        async with self._connect() as conn:
            await self._setup_connection(conn)
            async with conn.execute(
                "SELECT COUNT(*) AS c FROM jobs"
            ) as cur:
                row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def restore_all(
        self,
    ) -> AsyncIterator[tuple[JobResponse, dict | None]]:
        """Yield (job, request_payload) for every persisted job, oldest first.

        The manager calls this on startup to rehydrate the in-memory
        state. Active jobs (queued / processing) are returned so the
        manager can decide whether to re-queue them; terminal jobs are
        returned so the history is consistent across restarts.
        """
        async with self._connect() as conn:
            await self._setup_connection(conn)
            async with conn.execute(
                "SELECT * FROM jobs ORDER BY created_at ASC"
            ) as cur:
                rows = await cur.fetchall()
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
