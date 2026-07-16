FROM nvidia/cuda:12.1.0-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# Build dependencies. We need python3-dev for compiling the custom_rasterizer
# CUDA extension, and git for pip to fetch the requirements.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    git \
    wget \
    libgl1-mesa-glx \
    libglib2.0-0 \
    ninja-build \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps in their own layer so source changes don't bust the cache.
COPY requirements.txt .
RUN pip3 install --upgrade pip \
    && pip3 install -r requirements.txt

# Copy the package and install it. ``pip install .`` triggers the C++/CUDA
# extension build via setup.py.
COPY . .
RUN pip3 install .

# ----------------------------------------------------------------------
# Runtime image: same base, but without the build-only tools.
# ----------------------------------------------------------------------
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
# Don't write .pyc files in the container.
ENV PYTHONDONTWRITEBYTECODE=1

# Runtime shared libraries. The build stage already produced the
# compiled .so files inside the installed hy3dgen package, so we only
# need the system-level runtime deps here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy the installed package (with compiled extensions) from the builder.
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app

# Cache and log dirs become volumes in docker-compose so they survive
# container restarts.
RUN mkdir -p /app/logs /app/.cache
ENV XDG_CACHE_HOME=/app/.cache
ENV XDG_STATE_HOME=/app/.local/state

# Backend API (when APP_MODE=api) and legacy launcher both bind to 0.0.0.0
# when an API key is configured. CORS and auth are env-driven; see
# hy3dgen/api/config.py.
EXPOSE 9000 8080

# Default to the backend. Override with APP_MODE=launcher for the legacy UI.
ENV APP_MODE=api
# If you set ARCHEON_API_KEY the bind host upgrades to 0.0.0.0 automatically
# (see get_bind_host). Leave it unset and the server stays on 127.0.0.1.
ENV ARCHEON_API_KEY=""

ENTRYPOINT ["/bin/bash", "-c"]
CMD ["if [ \"$APP_MODE\" = 'launcher' ]; then \
        exec hy3dgen-launcher --host 0.0.0.0 --port 8080; \
      else \
        exec hy3dgen-api --host 0.0.0.0 --port 9000; \
      fi"]
