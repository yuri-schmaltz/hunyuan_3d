from fastapi import APIRouter, Depends, HTTPException, Request
import os
import os
import asyncio
import json
from typing import List, Dict, AsyncIterator
from sse_starlette.sse import EventSourceResponse
from hy3dgen.api.schemas import (
    JobRequest,
    JobResponse,
    MeshOpsRequest,
    GenerationRequest,
)
from hy3dgen.api.deps import get_manager, get_mesh_processor
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.meshops.processor import MeshProcessor
from hy3dgen.monitoring import get_system_metrics
from hy3dgen.api.config import SAVE_DIR

router = APIRouter(prefix="/v1", tags=["generation"])

# Terminal job states that should close the SSE stream.
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# Default save directory (following XDG specs)
# We might want to pass this via config later

@router.post("/jobs", response_model=JobResponse, status_code=202)
async def submit_job(
    request: JobRequest,
    manager: PriorityRequestManager = Depends(get_manager)
):
    """
    Submit a generation job.
    Accepts polymorphic JSON body: { "type": "text_to_3d" | "image_to_3d" | "multiview", ... }
    """
    uid = await manager.submit_job(request, SAVE_DIR)
    
    # Return initial status
    job = manager.get_job(uid)
    return job


@router.post("/generate", response_model=JobResponse, status_code=202)
async def submit_unified_job(
    request: GenerationRequest,
    manager: PriorityRequestManager = Depends(get_manager),
):
    """Submit a generation job using the unified request schema.

    All input fields are optional at the type level; the backend infers
    the generation mode from what's filled in. See ``GenerationRequest``
    for the dispatch rules. The internal ``JobRequest`` variant is
    derived automatically and dispatched the same way as a job
    submitted via ``POST /v1/jobs``.
    """
    uid = await manager.submit_unified(request, SAVE_DIR)
    return manager.get_job(uid)

@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(
    manager: PriorityRequestManager = Depends(get_manager)
):
    """List all jobs in memory."""
    return list(manager.jobs.values())

@router.get("/jobs/events")
async def stream_jobs_events(
    request: Request,
    manager: PriorityRequestManager = Depends(get_manager),
) -> EventSourceResponse:
    """Server-Sent Events stream of the full job list.

    The first event is the current snapshot (sorted by created_at desc),
    so a client that connects after jobs have already been created
    still gets the latest state. Subsequent events are full snapshots
    whenever any job transitions, or when a job is added/evicted. The
    stream stays open until the client disconnects.
    """
    queue = manager.subscribe_list()

    async def list_publisher() -> AsyncIterator[Dict]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    jobs: List[JobResponse] = await asyncio.wait_for(
                        queue.get(), timeout=15.0,
                    )
                except asyncio.TimeoutError:
                    # Keep-alive ping so proxies don't time out the connection.
                    yield {"event": "ping", "data": "{}"}
                    continue
                # Each event payload is a JSON array of JobResponse dicts.
                payload = json.dumps(
                    [j.model_dump(mode="json") for j in jobs],
                    default=str,
                )
                yield {"event": "list", "data": payload}
        finally:
            manager.unsubscribe_list(queue)

    return EventSourceResponse(list_publisher())


@router.get("/jobs/{uid}", response_model=JobResponse)
async def get_job_status(
    uid: str,
    manager: PriorityRequestManager = Depends(get_manager)
):
    """Retrieve job status and result path."""
    job = manager.get_job(uid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.delete("/jobs/{uid}")
async def cancel_job(
    uid: str,
    manager: PriorityRequestManager = Depends(get_manager)
):
    """Request job cancellation."""
    manager.cancel_job(uid)
    return {"status": "cancellation_requested", "uid": uid}


@router.get("/jobs/{uid}/events")
async def stream_job_events(
    uid: str,
    request: Request,
    manager: PriorityRequestManager = Depends(get_manager),
) -> EventSourceResponse:
    """Server-Sent Events stream of job state changes.

    The first event is the current state, so a client that connects after
    a job has already started still gets the latest status. Subsequent
    events are sent whenever the job transitions to a new state. The
    stream closes after a terminal status (completed/failed/cancelled)
    is sent, or when the client disconnects.
    """
    # If we don't even know about the uid, return 404 instead of an
    # open-ended stream.
    if manager.get_job(uid) is None and (
        manager.store is None or manager.store.get(uid) is None
    ):
        raise HTTPException(status_code=404, detail="Job not found")

    queue = manager.subscribe(uid)

    async def event_publisher() -> AsyncIterator[Dict]:
        try:
            while True:
                # Bail out promptly if the client has gone away.
                if await request.is_disconnected():
                    break
                try:
                    job: JobResponse = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Keep-alive ping so proxies don't time out the connection.
                    yield {"event": "ping", "data": "{}"}
                    continue
                payload = job.model_dump(mode="json")
                yield {
                    "event": "status",
                    "id": job.uid,
                    "data": json.dumps(payload, default=str),
                }
                if str(job.status) in _TERMINAL_STATUSES:
                    break
        finally:
            manager.unsubscribe(uid, queue)

    return EventSourceResponse(event_publisher())

@router.get("/system/metrics", tags=["system"])
async def get_metrics():
    """Get system resource usage (CPU, GPU, RAM)."""
    return get_system_metrics()

@router.post("/meshops/process")
async def process_mesh(
    request: MeshOpsRequest,
    manager: PriorityRequestManager = Depends(get_manager),
    processor: MeshProcessor = Depends(get_mesh_processor)
):
    """
    Process an existing job's output mesh (Decimate/Convert).
    """
    # 1. Get job
    job = manager.get_job(request.job_uid)
    if not job:
         raise HTTPException(status_code=404, detail="Job not found")
    if not job.file_path or not os.path.exists(job.file_path):
         raise HTTPException(status_code=404, detail="Job result file not found")
    
    # 2. Determine output path
    base_name, _ = os.path.splitext(job.file_path)
    if request.action == 'decimate':
        suffix = f"_decimate_{request.ratio:.2f}"
    else:
        suffix = f"_{request.action}"
    
    output_path = f"{base_name}{suffix}.{request.format}"
    
    # 3. Process (Offload to thread)
    try:
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(
            None, 
            processor.process, 
            job.file_path, 
            output_path, 
            request.action, 
            request.model_dump()
        )
        return {"file_path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
