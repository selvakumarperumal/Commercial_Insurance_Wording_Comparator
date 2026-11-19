# Build from the repo root:
#   docker build -f src/ciwc_worker/Dockerfile -t ciwc-worker .
#   docker run --rm -e REDIS_URL=redis://host:6379/0 -e GEMINI_API_KEY ciwc-worker

# Stage 1: install ciwc-worker's locked dependencies into /app/.venv
FROM python:3.15-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Some dependencies (zstandard) have no Python 3.15 wheel yet and are compiled here; the final image needs no compiler.
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/ciwc_worker packages/ciwc_worker
RUN uv sync --frozen --no-dev --package ciwc-worker --no-editable

# Stage 2: only the installed packages, the worker code and its prompts, without uv
FROM python:3.15-slim

WORKDIR /app

COPY --from=builder /app/.venv .venv
COPY src/ciwc_worker ciwc_worker
COPY src/config config

# /app comes first on the path, so this ciwc_worker wins over the placeholder package installed in the venv.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# SIGTERM lets the worker finish its current job; give it time before docker kills it.
STOPSIGNAL SIGTERM

CMD ["python", "-m", "ciwc_worker.worker"]
