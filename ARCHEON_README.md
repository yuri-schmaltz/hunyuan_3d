# Archeon 3D

> **A FastAPI + React + SSE fork of [Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)**
> with persistent job state, real-time event streams, and a single unified
> request schema.

Archeon turns Hunyuan3D-2 into a real **service**: queue jobs, stream
status over Server-Sent Events, persist them across restarts, and drive
everything from a React UI. The original 4 request types
(`text_to_3d`, `image_to_3d`, `multiview`, `texture_mesh`) are merged
into a single unified `GenerationRequest` — fill in any combination of
inputs and the backend figures out the rest.

## What's in the box

- **Backend** (Python 3.10+, FastAPI, Pydantic v2)
  - `POST /v1/generate` — unified request, 1 endpoint for 4 modes
  - `POST /v1/jobs` — legacy discriminated union (still works, deprecated)
  - `GET /v1/jobs/{uid}/events` — per-job SSE stream
  - `GET /v1/jobs/events` — list-level SSE stream (full snapshot per change)
  - `GET /v1/system/metrics` — CPU/GPU/RAM
  - `POST /v1/meshops/process` — decimate / convert
  - `GET /health` — liveness + readiness with `uptime`, `queue_size`,
    `jobs_in_store`, capabilities
  - SQLite-backed persistence (WAL mode) — survives restarts, replays
    in-flight jobs from their stored payload
  - CLI client (`hy3dgen-cli`) for scripting

- **Frontend** (React 19, Vite, TypeScript)
  - Single dynamic `CreateJobForm` (4 chips: Text / Image / 4 Views / Re-texture)
  - Live `JobGallery` with SSE-backed updates (auto-falls-back to polling)
  - "live / polling / connecting" indicator on every connection
  - Status filter tabs, mesh preview, GLB download

- **Ops** (everything below)
  - `pyproject.toml`, Makefile, `docker-compose.yml`, `.env.example`,
    GitHub Actions CI, structured logging, nginx config

## Quickstart

### A. Docker (recommended for most users)

```bash
git clone https://github.com/yuri-schmaltz/my-hunyuan-3D
cd my-hunyuan-3D
cp .env.example .env
# edit .env: set ARCHEON_API_KEY, ARCHEON_DEVICE=cuda, etc.
docker compose up --build
```

The API is on `http://localhost:8081`, the UI on `http://localhost:8080`.
Generated meshes land in the `archeon-data` named volume.

### B. Local dev (no Docker)

Prereqs: Python 3.10+, Node 20+, NVIDIA GPU (recommended).

```bash
git clone https://github.com/yuri-schmaltz/my-hunyuan-3D
cd my-hunyuan-3D
make install           # creates .venv + installs Python deps
make install-frontend  # installs npm deps
make dev               # starts API on :8081 and Vite dev server on :5173
```

Open <http://localhost:5173> for the UI, or hit the API directly:

```bash
curl -X POST http://localhost:8081/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"text": "a small red cube", "seed": 1234}'
```

### C. Quick CLI run

```bash
hy3dgen-cli generate --text "a small red cube" --output red.glb
```

The CLI waits for completion, downloads the mesh, and writes it to the
path you passed.

## Environment variables

The full list lives in [`.env.example`](.env.example). The most important
ones:

| Var | Default | Purpose |
|---|---|---|
| `ARCHEON_API_KEY` | _(empty)_ | When set, requires `X-API-Key` header. Empty = open (dev only). |
| `ARCHEON_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allow-list. |
| `ARCHEON_DEVICE` | `cuda` | `cuda` or `cpu`. CPU is for tests only. |
| `ARCHEON_MODEL` | `tencent/Hunyuan3D-2` | HuggingFace model id. |
| `ARCHEON_SAVE_DIR` | `$XDG_CACHE_HOME/hy3dgen/archeon` | Where generated meshes are written. |
| `ARCHEON_JOB_DB` | `$XDG_STATE_HOME/hy3dgen/archeon/jobs.db` | SQLite file. Empty = no persistence. |
| `ARCHEON_MAX_HISTORY` | `1000` | Cap on in-memory jobs; eviction deletes from DB. |
| `ARCHEON_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. |
| `ARCHEON_LOG_FILE` | _(empty)_ | Optional rotated log file (50 MB × 5). |
| `ARCHEON_HOST` / `ARCHEON_PORT` | `127.0.0.1` / `8081` | API bind address. |
| `HF_HOME` | (HF default) | Local HuggingFace model cache. |

The frontend reads its own `archeon_frontend/.env` — see
[`.env.example`](archeon_frontend/.env.example).

## Model setup

The first run downloads the models from HuggingFace. To pre-warm or pin
a specific version:

```bash
# Standard shape model (~10 GB on disk)
python -c "from huggingface_hub import snapshot_download; snapshot_download('tencent/Hunyuan3D-2')"

# Optional: paint model for textures (~6 GB)
python -c "from huggingface_hub import snapshot_download; snapshot_download('tencent/Hunyuan3D-2')"
```

Models land in `~/.cache/huggingface` by default — point `HF_HOME` at a
larger disk on a dedicated GPU box.

For systems with <6 GB VRAM, set `ARCHEON_DEVICE=cuda` and the
launcher/profile handling will offload aggressively (this is the
"GPU Poor" path inherited from the upstream `mmgp` integration).

## API surface (summary)

### `POST /v1/generate` — unified request

```json
{
  "text": "a small red cube",          // or
  "image": "<base64 png>",             // or
  "views": {                            // or
    "front": "<base64>", "back": "<base64>",
    "left":  "<base64>", "right": "<base64>"
  },
  "mesh": "<base64 glb>",              // for re-texture (with text or image)

  "seed": 1234, "steps": 50, "guidance": 5.0,
  "octree_resolution": 256, "format": "glb",
  "texture": false, "face_count": 40000
}
```

Returns `202` with the same `JobResponse` shape as `POST /v1/jobs`. The
backend infers the mode (text_to_3d / image_to_3d / multiview /
texture_mesh) from the populated fields.

### `GET /v1/jobs/{uid}/events` — per-job SSE

Stream of `event: status` payloads, one per transition. First event is
the current state. Stream closes after a terminal status.

### `GET /v1/jobs/events` — list-level SSE

Stream of `event: list` payloads, each the full sorted job list.
Stream stays open until the client disconnects.

### `GET /health`

Liveness + readiness with: `model_loaded`, `queue_size`, `jobs_in_store`,
`persistence_enabled`, `auth_required`, `last_error`, `uptime_seconds`.

## Architecture

```
┌─────────────────┐      HTTP/SSE       ┌──────────────────────────┐
│  React frontend │ ───────────────────▶ │  FastAPI (uvicorn)       │
│  (Vite, port    │ ◀─────────────────── │   ├─ /v1/generate        │
│   5173 dev /    │                      │   ├─ /v1/jobs/...        │
│   80 docker)    │                      │   └─ /v1/jobs/events     │
└─────────────────┘                      │                          │
                                         │  PriorityRequestManager  │
                                         │   ├─ asyncio queue       │
                                         │   ├─ ModelWorker         │
                                         │   └─ JobStore (SQLite)   │
                                         └────────────┬─────────────┘
                                                      │ writes
                                                      ▼
                                         ┌──────────────────────────┐
                                         │  ./archeon-data volume   │
                                         │   ├─ meshes/             │
                                         │   ├─ jobs.db (WAL)       │
                                         │   └─ logs/archeon-api.log│
                                         └──────────────────────────┘
```

## Development

```bash
make help        # show all targets
make install     # full install (Python + ML deps + dev tools)
make dev         # API on :8081 + Vite on :5173
make test        # pytest
make lint        # mypy + tsc + eslint
make build       # build the frontend bundle
make clean       # remove caches + node_modules
make status      # hit /health on a running API
```

## Troubleshooting

**`RuntimeError: No CUDA GPUs are available`**
You're on a machine without an NVIDIA GPU. Set `ARCHEON_DEVICE=cpu` or
use the Docker compose profile that pins the NVIDIA runtime.

**`HF_HUB_OFFLINE=1` / model download fails**
Pre-download with the `snapshot_download` snippet above. Make sure
`HF_HOME` is on a disk with at least 30 GB free.

**Frontend can't reach the API (CORS)**
Set `ARCHEON_CORS_ORIGINS` to include the frontend URL. Default is
`http://localhost:5173`. For Docker on the same host, use
`http://localhost:8080`.

**`X-API-Key` 401 even though I set the env var**
The API key is loaded once at startup. Restart the API after changing
`ARCHEON_API_KEY`. The key is logged as `<hidden>` in the health
endpoint when present.

**SSE connection drops after ~1 minute**
This is usually a reverse proxy (nginx, Caddy) without `proxy_buffering
off; proxy_read_timeout 86400s;` set. The included `nginx.conf` already
has these. If you fronted the API with your own proxy, copy those
settings.

## License

Inherits the upstream Tencent Hunyuan3D-2 license (see `LICENSE`).
Archeon-specific additions are MIT-licensed unless otherwise noted.
