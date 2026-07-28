from contextlib import asynccontextmanager
import os

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from hy3dgen.api.auth import require_api_key
from hy3dgen.api.config import SAVE_DIR, get_bind_host, get_cors_origins
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.api.routes import router
from hy3dgen.meshops.processor import MeshProcessor


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle (start/stop background workers)."""
    # Initialize manager
    app.state.manager = PriorityRequestManager()
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
    return {"status": "ok"}

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
