# ── Builder stage ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

# Install system build dependencies for cyvcf2 / pysam (htslib)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        git \
        libhts-dev \
        libcurl4-openssl-dev \
        libssl-dev \
        zlib1g-dev \
        libbz2-dev \
        liblzma-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package installer)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project metadata first for layer caching
COPY pyproject.toml ./
COPY src/ ./src/

# Install dependencies into a virtual environment using uv
RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python .

# ── Runtime stage ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# Install runtime system dependencies (bioinformatics tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
        htslib \
        bcftools \
        ncbi-blast+ \
        libhts1 \
        libcurl4 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root user
RUN groupadd -r soymutdb && \
    useradd -r -g soymutdb -d /app -s /sbin/nologin soymutdb

WORKDIR /app

# Copy source code
COPY --from=builder /app/src ./src
COPY pyproject.toml ./

# Create directories for BLAST cache and temp files
RUN mkdir -p /tmp/blast_cache /tmp/exports && \
    chown -R soymutdb:soymutdb /tmp/blast_cache /tmp/exports /app

USER soymutdb

# Healthcheck: verify celery worker process is responsive
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD celery -A soymutdb_worker.main inspect ping -d celery@$$HOSTNAME || exit 1

# Run Celery worker
CMD ["celery", "-A", "soymutdb_worker.main", "worker", "--loglevel=info"]
