from contextlib import asynccontextmanager
import logging
import os

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from hy3dgen.api import auth as _auth_module
from hy3dgen.api.auth import require_api_key
from hy3dgen.api.config import (
    SAVE_DIR,
    get_bind_host,
    get_cors_origins,
    get_job_db_path,
)
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.persistence import JobStore
from hy3dgen.api.routes import router
from hy3dgen.meshops.processor import MeshProcessor

logger = logging.getLogger("hy3dgen.api.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle (start/stop background workers)."""
    # Initialize the persistent store (or None to disable).
    db_path = get_job_db_path()
    store = JobStore(db_path) if db_path else None
    if store is not None:
        logger.info("JobStore initialized at %s", db_path)

    # Initialize manager with optional store, then start the worker loop.
    # ``start()`` rehydrates from the store before kicking off the
    # processing task, so jobs that were mid-flight when the process
    # died are recovered.
    app.state.manager = PriorityRequestManager(store=store)
    await app.state.manager.start()

    # Initialize processor
    app.state.mesh_processor = MeshProcessor()

    yield
    # Cleanup
    await app.state.manager.stop()


app = FastAPI(
    title="Archeon 3D Backend",
    description="High-performance local 3D generation backend with priority queuing and polymorphic API.",
    version="1.0.1",
    lifespan=lifespan,
)

# CORS: spec-compliant. When origins == ['*'] we must disable credentials
# (browsers reject the combination). For real deployments, set
# ARCHEON_CORS_ORIGINS to a comma-separated allow-list and optionally
# ARCHEON_ALLOW_CREDENTIALS=true.
_cors_origins = get_cors_origins()
_cors_allow_credentials = (
    os.environ.get('ARCHEON_ALLOW_CREDENTIALS', 'false').lower() == 'true'
    and _cors_origins != ['*']
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# /health stays unauthenticated so load balancers / the launcher can probe it
# without needing the API key.
@app.get("/health")
async def health_check():
    """Liveness + readiness probe.

    Returns 200 with a body that includes:
    - ``status``: ``"ok"`` if the server is up (even if the model has not loaded yet).
    - ``model_loaded``: whether the inference worker has been initialized.
    - ``queue_size``: how many jobs are pending.
    - ``version``: server version.
    - ``auth_required``: whether X-API-Key is enforced on /v1/*.
    - ``last_error``: the most recent worker error, if any. Cleared on success.
    """
    manager = getattr(app.state, "manager", None)
    queue_size = manager.queue.qsize() if manager is not None else 0
    last_error = getattr(manager, "last_error", None) if manager is not None else None
    return {
        "status": "ok",
        "version": app.version,
        "model_loaded": manager is not None and manager.worker is not None,
        "queue_size": queue_size,
        "auth_required": _auth_module.get_api_key() is not None,
        "last_error": last_error,
    }

app.mount("/files", StaticFiles(directory=SAVE_DIR), name="files")

# Apply API-key auth to everything else (the routes registered below).
# /health is already registered above; FastAPI dependencies apply per-route.
# The router endpoints protect themselves with ``require_api_key``.
app.include_router(router, dependencies=[Depends(require_api_key)])


if __name__ == "__main__":
    main()


def main():
    """Console entry point declared in setup.py: ``hy3dgen-api``."""
    import uvicorn
    import argparse
    parser = argparse.ArgumentParser(description="Archeon 3D Backend API server")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--host", type=str, default=get_bind_host())
    parser.add_argument(
        "--workers", type=int, default=1,
        help="Number of uvicorn workers. Use >1 only if the model is loaded lazily per worker.",
    )
    args = parser.parse_args()
    uvicorn.run(
        "hy3dgen.api.server:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
    )
