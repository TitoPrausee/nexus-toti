"""
SKILL: deploy_prep — Deployment vorbereiten und validieren
Prüft Readiness, generiert Dockerfiles, validiert Konfiguration.
"""

import json
import os
import re
from typing import Optional


def execute(path: str = ".", target: str = "docker", check_only: bool = False,
            llm_client=None, tools=None) -> dict:
    """
    Bereite Deployment vor.

    Args:
        path: Projektpfad
        target: 'docker', 'k8s', 'serverless', 'vps'
        check_only: Nur Readiness-Check, keine Dateien generieren
        llm_client: LLMClient
        tools: ToolRegistry

    Returns:
        dict mit Deployment-Ergebnissen
    """
    results = {
        "skill": "deploy_prep",
        "path": path,
        "target": target,
        "ready": False,
        "checks": [],
        "missing": [],
        "generated_files": [],
        "warnings": [],
    }

    # 1. Readiness-Checks
    checks = _deployment_checks(path, target, tools)
    results["checks"] = checks["checks"]
    results["missing"] = checks["missing"]
    results["warnings"] = checks["warnings"]
    results["ready"] = len(checks["missing"]) == 0

    # 2. Dateien generieren (wenn nicht check_only)
    if not check_only and not results["ready"]:
        if target == "docker":
            if "Dockerfile" in checks["missing"]:
                dockerfile = _generate_dockerfile(path, tools, llm_client)
                if dockerfile:
                    results["generated_files"].append({"name": "Dockerfile", "content": dockerfile})
                    if tools:
                        tools.dispatch("write_file", path=os.path.join(path, "Dockerfile"), content=dockerfile)

            if "docker-compose.yml" in checks["missing"] or "docker-compose.yaml" in checks["missing"]:
                compose = _generate_docker_compose(path, tools, llm_client)
                if compose:
                    results["generated_files"].append({"name": "docker-compose.yml", "content": compose})
                    if tools:
                        tools.dispatch("write_file", path=os.path.join(path, "docker-compose.yml"), content=compose)

            if ".dockerignore" in checks["missing"]:
                dockerignore = _generate_dockerignore(path, tools)
                if dockerignore:
                    results["generated_files"].append({"name": ".dockerignore", "content": dockerignore})
                    if tools:
                        tools.dispatch("write_file", path=os.path.join(path, ".dockerignore"), content=dockerignore)

    # 3. Docker Build Test (wenn Dockerfile existiert)
    if target == "docker" and os.path.exists(os.path.join(path, "Dockerfile")) and tools:
        build_result = tools.dispatch("docker", action="build", args=f"-t nexus-deploy-test {path}")
        if isinstance(build_result, dict):
            results["build_test"] = build_result

    return results


def _deployment_checks(path: str, target: str, tools=None) -> dict:
    """Prüfe Deployment-Readiness."""
    checks = {"checks": [], "missing": [], "warnings": []}

    files_in_dir = set(os.listdir(path)) if os.path.isdir(path) else set()

    if target == "docker":
        required = ["Dockerfile"]
        recommended = [".dockerignore", "docker-compose.yml", "requirements.txt", "package.json"]

        for f in required:
            exists = f in files_in_dir
            checks["checks"].append({"item": f, "required": True, "exists": exists})
            if not exists:
                checks["missing"].append(f)

        for f in recommended:
            exists = f in files_in_dir
            checks["checks"].append({"item": f, "required": False, "exists": exists})
            if not exists:
                checks["warnings"].append(f"{f} fehlt (empfohlen)")

    elif target == "k8s":
        required = ["Dockerfile", "k8s/", "deployment.yaml"]
        for f in required:
            exists = f in files_in_dir or os.path.exists(os.path.join(path, f))
            checks["checks"].append({"item": f, "required": True, "exists": exists})
            if not exists:
                checks["missing"].append(f)

    elif target == "vps":
        required = ["requirements.txt"]
        for f in required:
            exists = f in files_in_dir
            checks["checks"].append({"item": f, "required": True, "exists": exists})
            if not exists:
                checks["missing"].append(f)

    # Allgemeine Checks
    if ".env" in files_in_dir:
        checks["warnings"].append(".env-Datei gefunden — Secrets nicht committen!")
    if ".gitignore" not in files_in_dir:
        checks["warnings"].append(".gitignore fehlt — sollte erstellt werden")

    return checks


def _generate_dockerfile(path: str, tools=None, llm_client=None) -> str:
    """Generiere Dockerfile."""
    files = set(os.listdir(path)) if os.path.isdir(path) else set()
    is_python = "requirements.txt" in files or "setup.py" in files or "pyproject.toml" in files
    is_node = "package.json" in files

    if is_python:
        return """FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "main.py"]
"""
    elif is_node:
        return """FROM node:20-slim

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY . .

EXPOSE 3000

CMD ["node", "server.js"]
"""
    return "# Dockerfile — bitte manuell anpassen\nFROM ubuntu:22.04\n"


def _generate_docker_compose(path: str, tools=None, llm_client=None) -> str:
    """Generiere docker-compose.yml."""
    return """version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
"""


def _generate_dockerignore(path: str, tools=None) -> str:
    """Generiere .dockerignore."""
    return """.git
.gitignore
__pycache__
*.pyc
node_modules
.env
.venv
venv
*.md
.dockerignore
Dockerfile
docker-compose*.yml
"""
