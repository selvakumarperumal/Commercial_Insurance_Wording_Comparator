# Build from the repo root:
#   docker build -f src/commercial_insurance_wording_comparator/Dockerfile -t ciwc-api .
#   docker run --rm -p 8000:8000 ciwc-api

# Stage 1: install ciwc-api and its locked dependencies into /app/.venv
FROM python:3.15-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/ciwc_api packages/ciwc_api
RUN uv sync --frozen --no-dev --package ciwc-api --no-editable

# Stage 2: only the installed packages and the app, without uv or the source
FROM python:3.15-slim

WORKDIR /app

COPY --from=builder /app/.venv .venv
COPY src/commercial_insurance_wording_comparator commercial_insurance_wording_comparator

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["uvicorn", "commercial_insurance_wording_comparator.main:app", "--host", "0.0.0.0", "--port", "8000"]
