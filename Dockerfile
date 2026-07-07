FROM python:3.12-slim

WORKDIR /app

# Install git for Atlas Memory
RUN apt-get update && apt-get install -y git && apt-get clean

# Copy dependency file first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Nexus code
COPY atlas/ atlas/
COPY nexus/ nexus/
COPY nexus.py .
COPY config.yaml .
COPY SOUL.md .
COPY USER.md .

# Git config for Atlas Memory
RUN git config --global user.name "Nexus" \
    && git config --global user.email "nexus@local"

EXPOSE 8642

CMD ["python3", "nexus.py", "--telegram"]
