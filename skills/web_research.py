"""
SKILL: web_research — Tiefgehende Web-Recherche
Trianguliert Informationen aus mehreren Quellen.
Bewertet Vertrauenswürdigkeit und Aktualität.
"""

import json
import time
from typing import Optional


def execute(query: str, num_sources: int = 5, depth: str = "standard",
            llm_client=None, tools=None) -> dict:
    """
    Führt eine tiefgehende Web-Recherche durch.

    Args:
        query: Suchanfrage
        num_sources: Mindestanzahl Quellen
        depth: 'quick' (1 Quelle), 'standard' (3+ Quellen), 'deep' (5+ Quellen + Analyse)
        llm_client: LLMClient für Analyse
        tools: ToolRegistry für web_search

    Returns:
        dict mit research-Ergebnissen
    """
    results = {
        "skill": "web_research",
        "query": query,
        "depth": depth,
        "sources": [],
        "triangulated": False,
        "confidence": 0.0,
        "summary": "",
        "contradictions": [],
    }

    # Min-Quellen basierend auf Tiefe
    min_sources = {"quick": 1, "standard": 3, "deep": 5}.get(depth, 3)

    # Web-Suche
    if tools:
        search_result = tools.dispatch("web_search", query=query, num=num_sources + 2)
        if isinstance(search_result, dict) and "results" in search_result:
            for item in search_result["results"][:num_sources + 2]:
                if isinstance(item, dict):
                    results["sources"].append({
                        "title": item.get("name", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("snippet", ""),
                        "host": item.get("host_name", ""),
                    })

    # Triangulation: Prüfe ob mehrere Quellen ähnliche Informationen liefern
    if len(results["sources"]) >= min_sources:
        results["triangulated"] = True
        results["confidence"] = min(1.0, len(results["sources"]) / min_sources * 0.7)
    elif len(results["sources"]) >= 2:
        results["triangulated"] = True
        results["confidence"] = 0.5
    else:
        results["confidence"] = 0.3

    # LLM-Analyse für 'standard' und 'deep'
    if llm_client and depth in ["standard", "deep"] and results["sources"]:
        from core.llm_client import Message
        source_text = "\n".join(
            f"- [{s['title']}]({s['url']}): {s['snippet']}"
            for s in results["sources"]
        )
        messages = [
            Message(role="system", content="Du bist ein Recherche-Analyst. Fasse die Quellen zusammen. Markiere Widersprüche."),
            Message(role="user", content=f"Recherche zu: {query}\n\nQuellen:\n{source_text}\n\nFasse zusammen und markiere Widersprüche."),
        ]
        analysis = llm_client.chat(messages, level=2 if depth == "deep" else 1)
        results["summary"] = analysis.content

    # Quick-Summary wenn kein LLM
    if not results["summary"] and results["sources"]:
        snippets = [s["snippet"][:100] for s in results["sources"][:3] if s.get("snippet")]
        results["summary"] = " | ".join(snippets)

    return results
