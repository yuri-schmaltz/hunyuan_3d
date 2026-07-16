from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.meshops.processor import MeshProcessor
from hy3dgen.api.routes import router
from hy3dgen.api.config import SAVE_DIR

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
    version="1.0.0-alpha",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory=SAVE_DIR), name="files")

app.include_router(router)

if __name__ == "__main__":
    main()


def main():
    """Console entry point declared in setup.py: ``hy3dgen-api``."""
    import uvicorn
    import argparse
    parser = argparse.ArgumentParser(description="Archeon 3D Backend API server")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--host", type=str, default="0.0.0.0")
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
