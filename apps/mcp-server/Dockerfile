# syntax=docker/dockerfile:1.7
# =====================================================================
# SoyMutDB MCP server image — uv-based multi-stage build (B1 skeleton)
# Unified Python toolchain: pinned uv (same version as api/worker images).
# =====================================================================
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

# Pin uv to the same release used by the api/worker images.
COPY --from=ghcr.io/astral-sh/uv:0.11.33 /uv /usr/local/bin/uv

WORKDIR /app

# Install the package (fastmcp / httpx / uvicorn / redis via uv.lock) into a
# default venv under /opt/venv. The project itself is installed so that
# `python -m mcp_server.server` resolves from the venv at runtime.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-dev

# ---- runtime stage ----------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/src"

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src /app/src

WORKDIR /app

# Streamable HTTP endpoint.
EXPOSE 9000

CMD ["python", "-m", "mcp_server.server", "--host", "0.0.0.0", "--port", "9000"]
