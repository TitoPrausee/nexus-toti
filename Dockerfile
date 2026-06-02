FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir rich pyyaml

ARG BUILD_WITH_TELEGRAM=0
RUN if [ "$BUILD_WITH_TELEGRAM" = "1" ]; then pip install --no-cache-dir python-telegram-bot; fi

COPY . .

RUN mkdir -p \
    memory/sessions \
    memory/skills \
    memory/longterm \
    data/state \
    data/checkpoints

COPY docker-setup-skills.py /tmp/setup_skills.py
RUN python3 /tmp/setup_skills.py && rm /tmp/setup_skills.py

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Ollama host — auf Mac host.docker.internal damit Container Ollama auf dem Host erreicht
ENV OLLAMA_HOST="http://host.docker.internal:11434"
# Modell-Overrides (optional)
ENV NEXUS_MODEL_FAST="qwen2.5:3b"
ENV NEXUS_MODEL_STANDARD="qwen2.5:3b"
ENV NEXUS_MODEL_THINK="qwen2.5:3b"
ENV NEXUS_TG_TOKEN=""

ENTRYPOINT ["python3", "nexus.py"]
CMD []
