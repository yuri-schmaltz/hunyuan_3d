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
from hy3dgen.api.schemas import JobStatus, JobResponse, JobRequest

logger = logging.getLogger(__name__)

class PriorityRequestManager:
    """
    Manages generation requests with priority queuing and resource cleanup.
    Ensures single-threaded execution of model inference to prevent VRAM OOM.
    """
    def __init__(self, device='cuda', max_concurrent=1, max_history: int = 1000):
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

        # Lazy initialization of the worker to speed up startup
        self.worker: Optional[ModelWorker] = None
        
    async def start(self):
        """Start the background worker loop."""
        if self._worker_task is None:
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

    async def submit_job(self, request: JobRequest, save_dir: str, priority: int = 10) -> str:
        """
        Submit a job to the queue.
        
        Args:
            request: The generation request (polymorphic)
            save_dir: Directory to save output
            priority: Lower number = higher priority. Default 10.
        
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
        if victims:
            logger.info(f"Evicted {len(victims)} old jobs (older than {max_age_seconds}s).")
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
        if to_remove > 0:
            logger.info(f"Evicted {to_remove} jobs to respect max_history={self.max_history}.")
        return to_remove

    def cancel_job(self, uid: str):
        if uid in self.jobs:
            # We can only cancel if it's not yet processing (or barely started)
            if self.jobs[uid].status == JobStatus.QUEUED:
                self.jobs[uid].status = JobStatus.CANCELLED
                self.jobs[uid].error = "Cancelled by user"
                logger.info(f"Job {uid} cancelled")

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

        try:
            # Validate texture_mesh has a reference (image or prompt) before
            # spinning up the worker.
            if request.type == 'texture_mesh' and not getattr(request, 'has_reference', False):
                raise ValueError(
                    "texture_mesh requires at least one of: image, prompt."
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

        except Exception as e:
            logger.error(f"Job {uid} failed: {e}")
            import traceback
            traceback.print_exc()
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow().isoformat()

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
