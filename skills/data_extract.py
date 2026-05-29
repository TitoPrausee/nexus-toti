"""
SKILL: data_extract — Daten aus verschiedenen Quellen extrahieren
CSV, JSON, APIs, Web-Seiten, Datenbanken.
"""

import json
import os
import re
from typing import Optional


def execute(source: str = "", source_type: str = "auto", query: str = "",
            format: str = "json", llm_client=None, tools=None) -> dict:
    """
    Extrahiere Daten aus verschiedenen Quellen.

    Args:
        source: Pfad/URL/Query zur Datenquelle
        source_type: 'auto', 'csv', 'json', 'api', 'web', 'db', 'text'
        query: Filter/Query für die Daten
        format: Ausgabeformat 'json', 'csv', 'text'
        llm_client: LLMClient
        tools: ToolRegistry

    Returns:
        dict mit extrahierten Daten
    """
    results = {
        "skill": "data_extract",
        "source": source,
        "source_type": source_type,
        "data": None,
        "count": 0,
        "schema": None,
        "error": "",
    }

    # Auto-Erkennung
    if source_type == "auto":
        source_type = _detect_source_type(source)

    # Extraktion je nach Typ
    if source_type == "csv":
        result = _extract_csv(source, query, tools)
    elif source_type == "json":
        result = _extract_json(source, query, tools)
    elif source_type == "api":
        result = _extract_api(source, query, tools)
    elif source_type == "web":
        result = _extract_web(source, query, tools, llm_client)
    elif source_type == "db":
        result = _extract_db(source, query, tools)
    elif source_type == "text":
        result = _extract_text(source, query, tools, llm_client)
    else:
        return {"error": f"Unbekannter source_type: {source_type}"}

    results.update(result)
    return results


def _detect_source_type(source: str) -> str:
    """Erkennen des Quelltyps."""
    if source.endswith(".csv"):
        return "csv"
    if source.endswith(".json"):
        return "json"
    if source.startswith(("http://", "https://")):
        if "/api/" in source or "api." in source:
            return "api"
        return "web"
    if source.endswith(".db") or source.endswith(".sqlite"):
        return "db"
    return "text"


def _extract_csv(source: str, query: str, tools=None) -> dict:
    if tools:
        return tools.dispatch("csv_ops", action="read" if not query else "filter",
                              path=source, query=query)
    try:
        import csv
        with open(source, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return {"data": rows[:100], "count": len(rows), "schema": list(rows[0].keys()) if rows else []}
    except Exception as e:
        return {"error": str(e)}


def _extract_json(source: str, query: str, tools=None) -> dict:
    if tools:
        action = "query" if query else "parse_json"
        if action == "parse_json" and tools:
            result = tools.dispatch("read_file", path=source)
            if isinstance(result, dict) and "content" in result:
                return tools.dispatch("json_yaml", action="parse_json", data=result["content"])
        elif action == "query" and tools:
            result = tools.dispatch("read_file", path=source)
            if isinstance(result, dict) and "content" in result:
                return tools.dispatch("json_yaml", action="query", data=result["content"], query=query)
    try:
        with open(source, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"data": data, "count": len(data) if isinstance(data, list) else 1,
                "schema": list(data[0].keys()) if isinstance(data, list) and data else None}
    except Exception as e:
        return {"error": str(e)}


def _extract_api(source: str, query: str, tools=None) -> dict:
    if tools:
        return tools.dispatch("http_request", method="GET", url=source)
    return {"error": "Keine Tools verfügbar für API-Zugriff"}


def _extract_web(source: str, query: str, tools=None, llm_client=None) -> dict:
    """Extrahiere Daten von einer Web-Seite."""
    if llm_client:
        try:
            # Nutze z-ai function für Web-Content
            import subprocess
            result = subprocess.run(
                ["z-ai", "function", "--name", "web_reader", "--args",
                 json.dumps({"url": source})],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return {"data": result.stdout[:5000], "source_type": "web", "count": 1}
        except Exception:
            pass

    if tools:
        return tools.dispatch("http_request", method="GET", url=source)
    return {"error": "Web-Extraktion nicht verfügbar"}


def _extract_db(source: str, query: str, tools=None) -> dict:
    if tools:
        return tools.dispatch("db_query", action="query", db_path=source, query=query or "SELECT * FROM sqlite_master LIMIT 10", db_type="sqlite")
    return {"error": "Keine Tools verfügbar für DB-Zugriff"}


def _extract_text(source: str, query: str, tools=None, llm_client=None) -> dict:
    """Extrahiere strukturierte Daten aus Text."""
    if tools:
        result = tools.dispatch("read_file", path=source)
        if isinstance(result, dict) and "content" in result:
            content = result["content"]

            # Wenn Query angegeben, filtere
            if query and llm_client:
                from core.llm_client import Message
                messages = [
                    Message(role="system", content="Extrahiere die angeforderten Daten aus dem Text. Antworte als JSON."),
                    Message(role="user", content=f"Extrahiere aus diesem Text: {query}\n\nTEXT:\n{content[:3000]}"),
                ]
                response = llm_client.chat(messages, level=1)
                return {"data": response.content, "count": 1}

            return {"data": content[:5000], "count": 1}

    return {"error": "Text-Extraktion fehlgeschlagen"}
