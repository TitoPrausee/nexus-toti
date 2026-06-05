FROM python:3.12-slim

WORKDIR /app

# System deps — minimal, no bloat
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Create data directories
RUN mkdir -p data/memory nexus/soul

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Ollama — container reaches host via host.docker.internal
ENV OLLAMA_HOST="http://host.docker.internal:11434"

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD python3 -c "from nexus.core.agent import NexusAgent; print('ok')" || exit 1

ENTRYPOINT ["python3", "nexus.py"]
CMD []