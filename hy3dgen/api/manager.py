import asyncio
import gc
import logging
import threading
import torch
import uuid
import os
import time
from datetime import datetime
from typing import Dict, Optional, Tuple, Any

from hy3dgen.inference import ModelWorker
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.schemas import JobStatus, JobResponse, JobRequest

logger = logging.getLogger(__name__)


class PriorityRequestManager:
    """
    Manages generation requests with priority queuing and resource cleanup.
    Ensures single-threaded execution of model inference to prevent VRAM OOM.
    """

    def __init__(
        self,
        device='cuda',
        max_concurrent=1,
        max_history: int = 1000,
        store: Optional[JobStore] = None,
    ):
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.jobs: Dict[str, JobResponse] = {}
        self.device = device
        self._shutdown_event = asyncio.Event()
        self._worker_task: Optional[asyncio.Task] = None

        # Cap the in-memory job history so a long-running server doesn't grow
        # unbounded. Old completed/failed/cancelled jobs are evicted when the
        # dictionary exceeds ``max_history`` entries. 0 disables the cap.
        self.max_history = max_history
        self._evicted_total = 0

        # Most recent worker error (string) so /health can surface it.
        # Cleared automatically on the next successful job.
        self.last_error: Optional[str] = None

        # Optional SQLite-backed persistence. When set, every job transition
        # is mirrored to disk and the in-memory state is rehydrated on start.
        self.store: Optional[JobStore] = store

        # Per-job subscribers. ``subscribers[uid]`` is a list of asyncio
        # Queues; on each status change we put the new JobResponse on every
        # queue. SSE handlers consume one queue each.
        self._subscribers: Dict[str, list[asyncio.Queue]] = {}
        self._subs_lock = threading.Lock()
        # List-level subscribers (one queue per consumer). On every job
        # change we broadcast the current full list to all of these.
        # Used by the gallery page to update without polling.
        self._list_subscribers: list[asyncio.Queue] = []
        self._list_subs_lock = threading.Lock()

        # Lazy initialization of the worker to speed up startup
        self.worker: Optional[ModelWorker] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def rehydrate(self) -> int:
        """Restore jobs from the persistent store into memory.

        Returns the number of jobs rehydrated. Active jobs (queued or
        processing) that have a stored payload are reconstructed and
        re-queued so they actually resume after a restart. Active jobs
        that lack a payload (legacy DB, or written by an older version)
        are marked FAILED with a clear error. Terminal jobs are loaded
        as-is to preserve the history.
        """
        if self.store is None:
            return 0
        # Lazy import to avoid a hard dependency at module load.
        from hy3dgen.api.config import SAVE_DIR
        count = 0
        replayed = 0
        for job, payload in self.store.restore_all():
            self.jobs[job.uid] = job
            count += 1
            if job.status not in (JobStatus.QUEUED, JobStatus.PROCESSING):
                continue
            if not payload:
                # Legacy job whose payload wasn't persisted. Mark it
                # failed so the user can see the reason and resubmit.
                job.status = JobStatus.FAILED
                job.error = (
                    "Server restarted while this job was in-flight and "
                    "its original request payload was not stored. "
                    "Please resubmit."
                )
                job.completed_at = datetime.utcnow().isoformat()
                self._persist(job)
                self._notify(job)
                logger.warning(f"Cannot replay job {job.uid}: payload missing.")
                continue
            try:
                request = _request_from_payload(payload)
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = f"Stored payload could not be deserialized: {e}"
                job.completed_at = datetime.utcnow().isoformat()
                self._persist(job)
                self._notify(job)
                logger.warning(f"Cannot replay job {job.uid}: bad payload ({e}).")
                continue
            # Mid-flight jobs use a low priority (high number) so we
            # don't jump in front of anything new.
            self.queue.put_nowait((100, time.time(), job.uid, request, SAVE_DIR))
            replayed += 1
            logger.info(f"Re-queued active job {job.uid} after restart.")
        logger.info(
            f"Rehydrated {count} jobs from persistent store "
            f"({replayed} re-queued for replay)."
        )
        return count

    async def start(self):
        """Start the background worker loop."""
        if self._worker_task is None:
            self.rehydrate()
            self._worker_task = asyncio.create_task(self._process_queue())
            logger.info("PriorityRequestManager worker started.")

    async def stop(self):
        """Stop the worker loop gracefully."""
        self._shutdown_event.set()
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("PriorityRequestManager worker stopped.")

    async def submit_job(
        self,
        request: JobRequest,
        save_dir: str,
        priority: int = 10,
        _payload: Optional[dict] = None,
    ) -> str:
        """Submit a job to the queue.

        Args:
            request: The generation request (polymorphic)
            save_dir: Directory to save output
            priority: Lower number = higher priority. Default 10.
            _payload: Optional serialised request (used by rehydration
                so the original request body can be replayed after a
                restart). Normally callers should pass only ``request``
                and let ``_payload`` default to ``request.model_dump()``.

        Returns:
            uid: The unique job ID
        """
        uid = str(uuid.uuid4())
        job = JobResponse(
            uid=uid,
            status=JobStatus.QUEUED,
            created_at=datetime.utcnow().isoformat()
        )
        self.jobs[uid] = job

        # Queue item: (priority, timestamp, uid, request, save_dir)
        # timestamp acts as secondary sort key for FIFO within same priority
        await self.queue.put((priority, time.time(), uid, request, save_dir))
        logger.info(f"Job {uid} queued with priority {priority}")
        # Persist the initial state and notify any early subscribers.
        self._persist(job, payload=_payload or (request.model_dump() if request else None))
        self._notify(job)
        return uid

    def get_job(self, uid: str) -> Optional[JobResponse]:
        return self.jobs.get(uid)

    def evict_old_jobs(self, max_age_seconds: int = 24 * 3600) -> int:
        """Drop completed/failed/cancelled jobs older than ``max_age_seconds``.

        Active (queued/processing) jobs are never evicted. Returns the number
        of jobs removed. Call this from a periodic task or after each
        completed job to keep memory bounded.
        """
        cutoff = time.time() - max_age_seconds
        terminal_statuses = (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )
        victims: list[tuple[float, str]] = []  # (created_ts, uid)
        for uid, job in self.jobs.items():
            if job.status not in terminal_statuses or not job.created_at:
                continue
            try:
                created_ts = datetime.fromisoformat(job.created_at).timestamp()
            except ValueError:
                continue
            if created_ts < cutoff:
                victims.append((created_ts, uid))
        # Oldest first; sort ensures determinism when many jobs share a timestamp.
        victims.sort()
        for _, uid in victims:
            del self.jobs[uid]
            self._evicted_total += 1
            if self.store is not None:
                self.store.delete(uid)
        if victims:
            logger.info(f"Evicted {len(victims)} old jobs (older than {max_age_seconds}s).")
            self._notify_list()
        return len(victims)

    def evict_to_size(self) -> int:
        """If ``max_history`` is set and exceeded, drop the oldest terminal jobs.

        Returns the number evicted.
        """
        if self.max_history <= 0 or len(self.jobs) <= self.max_history:
            return 0
        terminal_statuses = (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )
        sortable: list[tuple[str, float]] = []
        for uid, job in self.jobs.items():
            if job.status in terminal_statuses and job.created_at:
                try:
                    created_ts = datetime.fromisoformat(job.created_at).timestamp()
                except ValueError:
                    created_ts = 0.0
                sortable.append((uid, created_ts))
        sortable.sort(key=lambda pair: pair[1])  # oldest first
        to_remove = len(self.jobs) - self.max_history
        for uid, _ in sortable[:to_remove]:
            del self.jobs[uid]
            self._evicted_total += 1
            if self.store is not None:
                self.store.delete(uid)
        if to_remove > 0:
            logger.info(f"Evicted {to_remove} jobs to respect max_history={self.max_history}.")
            self._notify_list()
        return to_remove

    def cancel_job(self, uid: str):
        if uid in self.jobs:
            # We can only cancel if it's not yet processing (or barely started)
            if self.jobs[uid].status == JobStatus.QUEUED:
                self.jobs[uid].status = JobStatus.CANCELLED
                self.jobs[uid].error = "Cancelled by user"
                logger.info(f"Job {uid} cancelled")
                self._persist(self.jobs[uid])
                self._notify(self.jobs[uid])

    async def _process_queue(self):
        while not self._shutdown_event.is_set():
            try:
                # Wait for job
                priority, _, uid, request, save_dir = await self.queue.get()
                
                # Check status
                if uid not in self.jobs or self.jobs[uid].status in (JobStatus.CANCELLED, JobStatus.FAILED):
                    self.queue.task_done()
                    continue

                # Run job
                await self._execute_model_worker(uid, request, save_dir)
                
                # Cleanup
                self.queue.task_done()
                self._aggressive_cleanup()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                await asyncio.sleep(1) # Backoff

    async def _execute_model_worker(self, uid: str, request: JobRequest, save_dir: str):
        job = self.jobs[uid]
        job.status = JobStatus.PROCESSING
        self._persist(job)
        self._notify(job)

        try:
            # Validate texture_mesh has a reference (image or prompt) before
            # spinning up the worker.
            if request and request.type == 'texture_mesh' and not getattr(request, 'has_reference', False):
                raise ValueError(
                    "texture_mesh requires at least one of: image, prompt."
                )

            # If we were rehydrated after a restart, request is None; we
            # can't replay the job without its original payload. Mark it
            # failed and move on.
            if request is None:
                raise RuntimeError(
                    "Job payload missing (server restarted mid-flight). Cannot replay."
                )

            # Initialize worker if needed (Lazy Loading)
            if self.worker is None:
                logger.info("Initializing ModelWorker (Lazy Load)...")
                # Blocking init logic, run in thread to avoid freezing API?
                # Model loading is heavy.
                self.worker = await asyncio.to_thread(
                    ModelWorker,
                    device=self.device,
                    enable_tex=True, # Archeon default to enabled for now
                    enable_t2i=True
                )

            # Prepare params dict from Pydantic model
            params = request.model_dump()

            # Map Pydantic fields to ModelWorker expectations
            if request.type == 'text_to_3d':
                params['text'] = request.prompt
            elif request.type == 'texture_mesh':
                # texture_mesh implies texture=True; ModelWorker also expects the
                # mesh (base64) to be present in params under the 'mesh' key, and
                # a guidance image/prompt under 'image'/'text'.
                params['texture'] = True
                if request.prompt and 'text' not in params:
                    params['text'] = request.prompt

            # Run generation in thread
            logger.info(f"Starting generation for job {uid}")
            file_path = await asyncio.to_thread(
                self.worker.generate,
                uid,
                params,
                save_dir
            )

            job.status = JobStatus.COMPLETED
            job.file_path = file_path
            job.completed_at = datetime.utcnow().isoformat()
            logger.info(f"Job {uid} completed successfully")
            # Clear the last_error latch after a success.
            self.last_error = None
            self._persist(job)
            self._notify(job)

        except Exception as e:
            logger.error(f"Job {uid} failed: {e}")
            import traceback
            traceback.print_exc()
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow().isoformat()
            # Track the most recent failure so /health can surface it.
            self.last_error = f"{type(e).__name__}: {e}"
            self._persist(job)
            self._notify(job)

    def _aggressive_cleanup(self):
        """Perform aggressive garbage collection and bounded history cleanup."""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        # Keep the in-memory history bounded. We don't evict on every job
        # (would be wasteful for short bursts), but we do check periodically.
        if self.max_history > 0 and len(self.jobs) > self.max_history * 1.2:
            self.evict_to_size()

    # ------------------------------------------------------------------
    # Persistence + pub/sub
    # ------------------------------------------------------------------

    def _persist(self, job: JobResponse, payload: Optional[dict] = None) -> None:
        """Mirror a job transition to the persistent store. No-op without one."""
        if self.store is None:
            return
        try:
            self.store.upsert(job, request_payload=payload)
        except Exception as e:  # never let persistence failures kill the worker
            logger.warning(f"Failed to persist job {job.uid}: {e}")

    def _notify(self, job: JobResponse) -> None:
        """Fan out a job update to every subscriber of this uid, and to
        list-level subscribers (one event per change, payload is the
        current full list)."""
        with self._subs_lock:
            queues = list(self._subscribers.get(job.uid, ()))
        for q in queues:
            try:
                q.put_nowait(job)
            except asyncio.QueueFull:  # pragma: no cover (unbounded queue)
                logger.warning(f"Subscriber queue full for {job.uid}; dropping event")
        # Then notify list subscribers with a fresh snapshot.
        if self._list_subscribers:
            self._notify_list()

    def _notify_list(self) -> None:
        """Send the current job list to every list-level subscriber.

        We send the full list (not a diff) so the consumer can simply
        replace its state. List size is bounded by max_history and the
        SSE payload is small (one JSON per uid).
        """
        with self._list_subs_lock:
            listeners = list(self._list_subscribers)
        if not listeners:
            return
        snapshot = sorted(
            self.jobs.values(),
            key=lambda j: j.created_at or "",
            reverse=True,
        )
        for q in listeners:
            try:
                q.put_nowait(snapshot)
            except asyncio.QueueFull:  # pragma: no cover (unbounded queue)
                logger.warning("List subscriber queue full; dropping event")

    def subscribe(self, uid: str) -> asyncio.Queue:
        """Register a new subscriber for ``uid`` and return its queue.

        The caller is expected to read the queue and call
        ``unsubscribe(uid, queue)`` when done. The first item on the
        queue is the current job state (so consumers don't have to
        separately fetch it).
        """
        q: asyncio.Queue = asyncio.Queue()
        with self._subs_lock:
            self._subscribers.setdefault(uid, []).append(q)
        # Prime the queue with the current state so the consumer has it
        # immediately, even if no further transitions happen.
        current = self.jobs.get(uid) or (self.store.get(uid) if self.store else None)
        if current is not None:
            q.put_nowait(current)
        return q

    def unsubscribe(self, uid: str, queue: asyncio.Queue) -> None:
        with self._subs_lock:
            listeners = self._subscribers.get(uid)
            if not listeners:
                return
            try:
                listeners.remove(queue)
            except ValueError:
                pass
            if not listeners:
                self._subscribers.pop(uid, None)

    def subscribe_list(self) -> asyncio.Queue:
        """Register a new list-level subscriber.

        The first item on the queue is the current snapshot of the
        in-memory job list, so consumers don't need a separate fetch.
        Subsequent items are also full snapshots, sorted by created_at
        desc.
        """
        q: asyncio.Queue = asyncio.Queue()
        with self._list_subs_lock:
            self._list_subscribers.append(q)
        # Prime with the current snapshot.
        q.put_nowait(
            sorted(
                self.jobs.values(),
                key=lambda j: j.created_at or "",
                reverse=True,
            )
        )
        return q

    def unsubscribe_list(self, queue: asyncio.Queue) -> None:
        with self._list_subs_lock:
            try:
                self._list_subscribers.remove(queue)
            except ValueError:
                pass


# ---------------------------------------------------------------------------
# Rehydration helpers
# ---------------------------------------------------------------------------

# Map the ``type`` discriminator to the concrete Pydantic model class.
# We can't use ``TypeAdapter(JobRequest)`` here because the union is
# declared with ``Annotated[..., Field(discriminator='type')]`` and
# Pydantic 2.13 has a bug with that combo. Instead we look up the class
# by name from the JSON tag.
_REQUEST_CLASSES: dict = {
    "text_to_3d": None,  # filled in lazily to avoid an import cycle
    "image_to_3d": None,
    "multiview": None,
    "texture_mesh": None,
}


def _request_from_payload(payload: dict):
    """Reconstruct a JobRequest (or one of its union members) from a dict.

    Used by ``PriorityRequestManager.rehydrate`` to rebuild the original
    request from a payload we stored in SQLite.
    """
    from hy3dgen.api.schemas import (
        TextTo3DRequest,
        ImageTo3DRequest,
        MultiviewRequest,
        TextureMeshRequest,
    )
    if _REQUEST_CLASSES["text_to_3d"] is None:
        _REQUEST_CLASSES.update({
            "text_to_3d": TextTo3DRequest,
            "image_to_3d": ImageTo3DRequest,
            "multiview": MultiviewRequest,
            "texture_mesh": TextureMeshRequest,
        })
    if not isinstance(payload, dict):
        raise ValueError(f"Payload is not a dict: {type(payload).__name__}")
    tag = payload.get("type")
    if tag not in _REQUEST_CLASSES:
        raise ValueError(f"Unknown request type: {tag!r}")
    cls = _REQUEST_CLASSES[tag]
    if cls is None:
        raise ValueError(f"Request class for type {tag!r} not registered")
    return cls.model_validate(payload)
