"""
SKILL: doc_gen — Dokumentation generieren
Generiert README, API-Docs, Docstrings, CHANGELOGs.
"""

import json
import re
import os
from typing import Optional


def execute(path: str = ".", doc_type: str = "readme", output: str = "",
            llm_client=None, tools=None) -> dict:
    """
    Generiere Dokumentation.

    Args:
        path: Pfad zum Projekt
        doc_type: 'readme', 'api', 'docstrings', 'changelog'
        output: Ausgabedatei (optional)
        llm_client: LLMClient
        tools: ToolRegistry

    Returns:
        dict mit generierter Dokumentation
    """
    results = {
        "skill": "doc_gen",
        "path": path,
        "doc_type": doc_type,
        "content": "",
        "files_processed": 0,
    }

    # Projektdaten sammeln
    project_info = _gather_project_info(path, tools)
    results["files_processed"] = project_info.get("file_count", 0)

    if doc_type == "readme":
        results["content"] = _gen_readme(project_info, llm_client)
    elif doc_type == "api":
        results["content"] = _gen_api_docs(path, project_info, llm_client, tools)
    elif doc_type == "docstrings":
        results["content"] = _gen_docstrings(path, tools, llm_client)
    elif doc_type == "changelog":
        results["content"] = _gen_changelog(path, tools, llm_client)
    else:
        results["content"] = f"Unbekannter doc_type: {doc_type}"

    # In Datei schreiben
    if output and results["content"] and tools:
        tools.dispatch("write_file", path=output, content=results["content"])
        results["output_file"] = output

    return results


def _gather_project_info(path: str, tools=None) -> dict:
    """Sammle Projekt-Informationen."""
    info = {"path": path, "files": [], "file_count": 0, "has_git": False,
            "has_docker": False, "has_tests": False, "languages": set()}

    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                   ["node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build"]]
        for f in files:
            full = os.path.join(root, f)
            info["files"].append(full)
            ext = os.path.splitext(f)[1]
            if ext in [".py"]:
                info["languages"].add("Python")
            elif ext in [".js", ".jsx"]:
                info["languages"].add("JavaScript")
            elif ext in [".ts", ".tsx"]:
                info["languages"].add("TypeScript")
            if f == "Dockerfile" or f == "docker-compose.yml":
                info["has_docker"] = True
            if "test" in root.lower() or f.startswith("test_"):
                info["has_tests"] = True
        if len(info["files"]) > 100:
            break

    info["file_count"] = len(info["files"])
    info["languages"] = list(info["languages"])
    info["has_git"] = os.path.exists(os.path.join(path, ".git"))

    # README/Package-Info
    for name in ["package.json", "setup.py", "pyproject.toml", "requirements.txt"]:
        full = os.path.join(path, name)
        if os.path.exists(full) and tools:
            result = tools.dispatch("read_file", path=full)
            if isinstance(result, dict) and "content" in result:
                info[name] = result["content"][:1000]

    return info


def _gen_readme(project_info: dict, llm_client=None) -> str:
    """Generiere README."""
    if llm_client:
        from core.llm_client import Message
        messages = [
            Message(role="system", content="Generiere eine professionelle README.md. Nutze Markdown. Keine Platzhalter."),
            Message(role="user", content=f"Projekt-Info: {json.dumps(project_info, ensure_ascii=False)[:3000]}\n\nGeneriere eine vollständige README.md."),
        ]
        response = llm_client.chat(messages, level=2)
        return response.content

    # Fallback: Template
    return f"""# {os.path.basename(project_info['path'])}

## Übersicht
Sprachen: {', '.join(project_info.get('languages', ['Unknown']))}
Dateien: {project_info.get('file_count', 0)}
Docker: {'Ja' if project_info.get('has_docker') else 'Nein'}
Tests: {'Ja' if project_info.get('has_tests') else 'Nein'}

## Installation
```bash
pip install -r requirements.txt
```

## Nutzung
Siehe Dokumentation.

## Lizenz
MIT
"""


def _gen_api_docs(path: str, project_info: dict, llm_client=None, tools=None) -> str:
    """Generiere API-Dokumentation."""
    api_files = [f for f in project_info.get("files", [])
                 if "api" in f.lower() or "route" in f.lower() or "endpoint" in f.lower()]

    if not api_files:
        return "Keine API-Dateien gefunden."

    # Sammle API-Code
    api_code = ""
    for f in api_files[:10]:
        if tools:
            result = tools.dispatch("read_file", path=f)
            if isinstance(result, dict) and "content" in result:
                api_code += f"\n\n# {f}\n{result['content'][:2000]}"

    if llm_client and api_code:
        from core.llm_client import Message
        messages = [
            Message(role="system", content="Generiere API-Dokumentation in Markdown. Mit Endpunkten, Parametern, Responses."),
            Message(role="user", content=f"API-Code:\n{api_code[:4000]}\n\nGeneriere API-Dokumentation."),
        ]
        response = llm_client.chat(messages, level=2)
        return response.content

    return f"API-Dateien gefunden: {len(api_files)}. Nutze LLM für detaillierte Dokumentation."


def _gen_docstrings(path: str, tools=None, llm_client=None) -> str:
    """Generiere Docstrings für Funktionen ohne Docstrings."""
    py_files = [f for f in os.listdir(path) if f.endswith(".py")] if os.path.isdir(path) else []

    results = []
    for py_file in py_files[:20]:
        full = os.path.join(path, py_file)
        if tools:
            result = tools.dispatch("read_file", path=full)
            if isinstance(result, dict) and "content" in result:
                code = result["content"]
                # Finde Funktionen ohne Docstrings
                funcs = re.findall(r'def\s+(\w+)\s*\([^)]*\):\s*\n(\s+)(?!\1\s+""")', code)
                if funcs:
                    results.append(f"## {py_file}\n{len(funcs)} Funktionen ohne Docstrings")

    return "\n".join(results) if results else "Alle Funktionen haben Docstrings."


def _gen_changelog(path: str, tools=None, llm_client=None) -> str:
    """Generiere CHANGELOG aus Git-Historie."""
    if tools:
        result = tools.dispatch("git", action="log", args="--oneline -30")
        if isinstance(result, dict) and "stdout" in result:
            commits = result["stdout"].strip()
            if llm_client:
                from core.llm_client import Message
                messages = [
                    Message(role="system", content="Erstelle einen CHANGELOG.md aus den Git-Commits. Gruppiere nach Typ (feat, fix, etc.)."),
                    Message(role="user", content=f"Git-Commits:\n{commits}\n\nErstelle CHANGELOG.md."),
                ]
                response = llm_client.chat(messages, level=1)
                return response.content
            return f"## Changelog\n\n{commits}"

    return "Keine Git-Historie gefunden."
