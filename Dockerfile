FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG BUILD_WITH_TELEGRAM=1
RUN if [ "$BUILD_WITH_TELEGRAM" = "1" ]; then pip install --no-cache-dir python-telegram-bot; fi

COPY . .

RUN mkdir -p \
    memory/sessions \
    memory/skills \
    memory/longterm \
    data/state \
    data/checkpoints \
    data/rag

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Ollama host — auf Mac host.docker.internal damit Container Ollama auf dem Host erreicht
ENV OLLAMA_HOST="http://host.docker.internal:11434"
# v5 Model Routing — kimi-k2.6:cloud als Orchestrator (best available)
ENV NEXUS_MODEL_FAST="deepseek-v4-flash:cloud"
ENV NEXUS_MODEL_STANDARD="kimi-k2.6:cloud"
ENV NEXUS_MODEL_THINK="kimi-k2.6:cloud"
ENV NEXUS_TG_TOKEN=""

ENTRYPOINT ["python3", "nexus.py"]
CMD []