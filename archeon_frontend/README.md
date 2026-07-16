# Archeon 3D — Frontend

React + TypeScript + Vite UI for the [Archeon 3D](https://github.com/yuri-schmaltz/my-hunyuan-3D) backend.

The backend is the FastAPI server in `../hy3dgen/api/server.py` (entry point `hy3dgen-api`).
This app talks to it over HTTP and polls the `/v1/jobs` and `/v1/system/metrics` endpoints.

## Stack

- React 19 + TypeScript 5.9
- Vite 7 (dev server + bundler)
- Tailwind CSS v4 (via `@tailwindcss/vite`)
- Axios for HTTP

## Prerequisites

- Node.js ≥ 20
- A running Archeon 3D backend (see the project root README)

## Setup

```bash
npm install
cp .env.example .env       # then edit VITE_API_URL if your backend is not on localhost:9000
npm run dev                # http://localhost:5173
```

## Scripts

| Script | Purpose |
| --- | --- |
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | Type-check (`tsc -b`) + production build to `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | ESLint (flat config) |

## Environment variables

| Name | Default | Description |
| --- | --- | --- |
| `VITE_API_URL` | `http://localhost:9000` | Backend base URL. The app appends `/v1` itself. |

## Project layout

```
src/
├── api/                      # HTTP client + shared types
│   ├── client.ts             # Axios instance, reads VITE_API_URL
│   └── types.ts              # JobStatus, JobRequest, SystemMetrics, etc.
├── components/
│   ├── common/               # Cross-cutting (ErrorBoundary, …)
│   ├── jobs/                 # CreateJobForm, JobGallery
│   └── monitoring/           # SystemMonitor
├── App.tsx                   # Top-level layout
├── main.tsx                  # React root + ErrorBoundary wrap
└── index.css                 # Tailwind theme tokens
```

## Conventions

- All async API calls go through `apiClient` (never `fetch` directly).
- Polling components check `document.hidden` and pause when the tab is in the
  background.
- `<form>` inputs always use a paired `<label htmlFor>` / `id`.
- Status-driven UI uses the typed `JobStatus` const, not raw strings.
