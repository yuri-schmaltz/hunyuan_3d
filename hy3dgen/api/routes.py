import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from hy3dgen.api.config import SAVE_DIR
from hy3dgen.api.deps import get_manager, get_mesh_processor
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.schemas import (
    GenerationRequest,
    JobRequest,
    JobResponse,
    MeshOpsRequest,
)
from hy3dgen.meshops.processor import MeshProcessor
from hy3dgen.monitoring import get_system_metrics

router = APIRouter(prefix="/v1", tags=["generation"])

# Terminal job states that should close the SSE stream.
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# Type aliases for the modern Annotated-dependency style.
# (FastAPI >= 0.95 prefers `x: Annotated[T, Depends(...)]` over
# `x: T = Depends(...)` for type-checker compatibility.)
ManagerDep = Annotated[PriorityRequestManager, Depends(get_manager)]
MeshProcessorDep = Annotated[MeshProcessor, Depends(get_mesh_processor)]


# ---------------------------------------------------------------------------
# Submission endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=202,
    summary="Submit a generation job (legacy polymorphic)",
    description=(
        "Accepts the discriminated-union body "
        "`{ \"type\": \"text_to_3d\" | \"image_to_3d\" | \"multiview\" | \"texture_mesh\", ... }`. "
        "New code should use `POST /v1/generate` instead — the unified schema "
        "infers the mode from the fields you fill in."
    ),
)
async def submit_job(
    request: JobRequest,
    manager: ManagerDep,
) -> JobResponse:
    """Submit a generation job. Returns 202 with the initial status."""
    uid = await manager.submit_job(request, SAVE_DIR)
    return manager.get_job(uid)  # type: ignore[return-value]


@router.post(
    "/generate",
    response_model=JobResponse,
    status_code=202,
    summary="Submit a unified generation job",
    description=(
        "All input fields are optional at the type level; the backend infers "
        "the generation mode from what's filled in. See `GenerationRequest` "
        "for the dispatch rules. Common params (`seed`, `steps`, `guidance`, "
        "`octree_resolution`, `format`, `face_count`, `texture`, "
        "`remove_background`) are shared across all modes."
    ),
)
async def submit_unified_job(
    request: GenerationRequest,
    manager: ManagerDep,
) -> JobResponse:
    """Submit a generation job using the unified request schema."""
    uid = await manager.submit_unified(request, SAVE_DIR)
    return manager.get_job(uid)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Query endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/jobs",
    response_model=list[JobResponse],
    summary="List all jobs currently in memory",
)
async def list_jobs(manager: ManagerDep) -> list[JobResponse]:
    """List all jobs in memory (most recent first)."""
    return sorted(
        manager.jobs.values(),
        key=lambda j: j.created_at or "",
        reverse=True,
    )


@router.get(
    "/jobs/{uid}",
    response_model=JobResponse,
    responses={404: {"description": "Job not found"}},
)
async def get_job_status(uid: str, manager: ManagerDep) -> JobResponse:
    """Retrieve job status and result path."""
    job = manager.get_job(uid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/jobs/{uid}")
async def cancel_job(uid: str, manager: ManagerDep) -> dict:
    """Request job cancellation. Idempotent — unknown uids return ok."""
    manager.cancel_job(uid)
    return {"status": "cancellation_requested", "uid": uid}


# ---------------------------------------------------------------------------
# Real-time endpoints (SSE)
# ---------------------------------------------------------------------------

@router.get("/jobs/events", summary="SSE stream of the full job list")
async def stream_jobs_events(
    request: Request,
    manager: ManagerDep,
) -> EventSourceResponse:
    """Server-Sent Events stream of the full job list.

    The first event is the current snapshot (sorted by created_at desc),
    so a client that connects after jobs have already been created
    still gets the latest state. Subsequent events are full snapshots
    whenever any job transitions, or when a job is added/evicted. The
    stream stays open until the client disconnects.
    """
    queue = manager.subscribe_list()

    async def list_publisher() -> AsyncIterator[dict]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    jobs: list[JobResponse] = await asyncio.wait_for(
                        queue.get(), timeout=15.0,
                    )
                except asyncio.TimeoutError:
                    # Keep-alive ping so proxies don't time out the connection.
                    yield {"event": "ping", "data": "{}"}
                    continue
                payload = json.dumps(
                    [j.model_dump(mode="json") for j in jobs],
                    default=str,
                )
                yield {"event": "list", "data": payload}
        finally:
            manager.unsubscribe_list(queue)

    return EventSourceResponse(list_publisher())


@router.get(
    "/jobs/{uid}/events",
    summary="SSE stream of a single job's transitions",
    responses={404: {"description": "Job not found"}},
)
async def stream_job_events(
    uid: str,
    request: Request,
    manager: ManagerDep,
) -> EventSourceResponse:
    """Server-Sent Events stream of job state changes.

    The first event is the current state, so a client that connects after
    a job has already started still gets the latest status. Subsequent
    events are sent whenever the job transitions to a new state. The
    stream closes after a terminal status (completed/failed/cancelled)
    is sent, or when the client disconnects.
    """
    # 404 if the uid is unknown.
    if manager.get_job(uid) is None:
        if manager.store is None:
            raise HTTPException(status_code=404, detail="Job not found")
        stored = await manager.store.get(uid)
        if stored is None:
            raise HTTPException(status_code=404, detail="Job not found")

    queue = manager.subscribe(uid)

    async def event_publisher() -> AsyncIterator[dict]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    job: JobResponse = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
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


# ---------------------------------------------------------------------------
# System + post-processing
# ---------------------------------------------------------------------------

@router.get(
    "/admin/stats",
    tags=["admin"],
    summary="Operational stats (job counts per status, model + queue state)",
)
async def admin_stats(manager: ManagerDep) -> dict:
    """Counts of jobs by status, plus the queue depth and persistence state.

    Useful for dashboards and health checks that want more detail
    than ``/health``. Auth-gated like every other ``/v1/*`` route.
    """
    jobs_in_memory = len(manager.jobs)
    counts_by_status: dict[str, int] = {}
    for j in manager.jobs.values():
        key = j.status.value if hasattr(j.status, "value") else str(j.status)
        counts_by_status[key] = counts_by_status.get(key, 0) + 1
    jobs_in_store = (await manager.store.count()) if manager.store is not None else 0
    return {
        "queue_depth": manager.queue.qsize(),
        "jobs_in_memory": jobs_in_memory,
        "jobs_in_store": jobs_in_store,
        "by_status": counts_by_status,
        "persistence_enabled": manager.store is not None,
        "model_loaded": manager.worker is not None,
        "max_history": manager.max_history,
    }


@router.get("/system/metrics", tags=["system"], summary="CPU/GPU/RAM usage")
async def get_metrics() -> dict:
    """Get system resource usage (CPU, GPU, RAM)."""
    return get_system_metrics()


@router.post(
    "/meshops/process",
    summary="Decimate or convert an existing job's mesh",
    responses={
        404: {"description": "Source job or its mesh not found"},
        500: {"description": "Mesh processing failed"},
    },
)
async def process_mesh(
    request: MeshOpsRequest,
    manager: ManagerDep,
    processor: MeshProcessorDep,
) -> dict:
    """Process an existing job's output mesh (decimate / convert)."""
    job = manager.get_job(request.job_uid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.file_path or not Path(job.file_path).exists():  # noqa: ASYNC240
        raise HTTPException(status_code=404, detail="Job result file not found")

    base_name = Path(job.file_path).stem
    if request.action == 'decimate':
        suffix = f"_decimate_{request.ratio:.2f}"
    else:
        suffix = f"_{request.action}"
    output_path = f"{base_name}{suffix}.{request.format}"

    try:
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(
            None,
            processor.process,
            job.file_path,
            output_path,
            request.action,
            request.model_dump(),
        )
        return {"file_path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
