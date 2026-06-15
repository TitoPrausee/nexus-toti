# ─── NEXUS v7 — Multi-Stage Dockerfile ──────────────────────────
# Stage 1: Builder — install deps in a full image
# Stage 2: Runtime — minimal slim image, non-root user

# ── Builder ─────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build deps (some Python packages need gcc/libffi)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime ──────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="NEXUS v7"
LABEL org.opencontainers.image.description="Autonomer KI-Agent mit Seele — Soul-driven AI Agent"
LABEL org.opencontainers.image.version="7.0"
LABEL org.opencontainers.image.source="https://github.com/***REMOVED***/nexus-toti"

# Security: create non-root user
RUN groupadd --gid 1000 nexus && \
    useradd --uid 1000 --gid nexus --shell /bin/bash --create-home nexus

WORKDIR /app

# System deps — only curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /install /usr/local

# App code — .dockerignore keeps the image lean
COPY . .

# Create persistent data dirs with correct ownership
RUN mkdir -p data/memory data/sessions nexus/soul && \
    chown -R nexus:nexus /app

# Expose web UI port (only used by nexus-web service)
EXPOSE 3000

# Env defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEXUS_LOG_LEVEL=INFO \
    NEXUS_LOG_FORMAT=text \
    OLLAMA_HOST=http://host.docker.internal:11435

# Health check — uses lightweight import test (no LLM call)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD python3 nexus.py --health-check || exit 1

# Switch to non-root user
USER nexus

ENTRYPOINT ["python3", "nexus.py"]
CMD []