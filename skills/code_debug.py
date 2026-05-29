"""
SKILL: code_debug — Code debuggen mit Error-Root-Cause-Analyse
Analysiert Fehlermeldungen, findet Root Causes, schlägt Fixes vor.
"""

import json
import re
import os
from typing import Optional


def execute(error_message: str = "", file_path: str = "", code: str = "",
            llm_client=None, tools=None, error_learning=None) -> dict:
    """
    Debuggt Code durch systematische Fehleranalyse.

    Args:
        error_message: Die Fehlermeldung
        file_path: Pfad zur problematischen Datei
        code: Der Code zum Analysieren (alternativ zu file_path)
        llm_client: LLMClient für Analyse
        tools: ToolRegistry für Datei-Zugriff
        error_learning: ErrorLearningSystem für bekannte Fehler

    Returns:
        dict mit Debug-Ergebnissen
    """
    results = {
        "skill": "code_debug",
        "error_message": error_message,
        "file_path": file_path,
        "root_cause": "",
        "fix_suggestion": "",
        "error_class": "",
        "known_error": False,
        "auto_fix_available": False,
        "confidence": 0.0,
    }

    # 1. Prüfe Error Learning auf bekannte Fehler
    if error_learning:
        warnings = error_learning.check_before_action(
            action=f"debug:{error_message[:100]}",
            tool="code_debug",
        )
        if warnings:
            results["known_error"] = True
            results["fix_suggestion"] = warnings[0].solution or warnings[0].hint
            results["confidence"] = warnings[0].confidence

    # 2. Code laden
    source_code = code
    if not source_code and file_path and tools:
        file_result = tools.dispatch("read_file", path=file_path)
        if isinstance(file_result, dict) and "content" in file_result:
            source_code = file_result["content"]

    # 3. Fehlerklasse bestimmen (Level 0 — lokal)
    results["error_class"] = _classify_error(error_message)

    # 4. Stack-Trace-Analyse (Level 0 — lokal)
    trace_info = _parse_traceback(error_message)
    if trace_info:
        results["traceback"] = trace_info

    # 5. LLM-Analyse für Root Cause
    if llm_client and source_code:
        from core.llm_client import Message
        debug_prompt = f"""Analysiere diesen Fehler und finde die ROOT CAUSE (nicht das Symptom).

FEHLER: {error_message[:500]}
{'DATEI: ' + file_path if file_path else ''}
{'TRACEBACK: ' + str(trace_info) if trace_info else ''}

CODE:
```
{source_code[:3000]}
```

Antworte als JSON:
{{
  "root_cause": "<die eigentliche Ursache, nicht das Symptom>",
  "fix": "<konkreter Fix-Vorschlag>",
  "confidence": 0.0-1.0,
  "auto_fixable": true/false
}}"""

        messages = [
            Message(role="system", content="Du bist ein Debug-Experte. Finde die Root Cause, nicht das Symptom. Antworte als JSON."),
            Message(role="user", content=debug_prompt),
        ]
        response = llm_client.chat(messages, level=2)

        # Parse die LLM-Antwort
        try:
            json_match = re.search(r'\{[\s\S]*\}', response.content)
            if json_match:
                analysis = json.loads(json_match.group())
                results["root_cause"] = analysis.get("root_cause", "")
                results["fix_suggestion"] = analysis.get("fix", "")
                results["confidence"] = max(results["confidence"], float(analysis.get("confidence", 0.5)))
                results["auto_fix_available"] = analysis.get("auto_fixable", False)
        except (json.JSONDecodeError, ValueError):
            results["root_cause"] = response.content[:500]
            results["confidence"] = 0.6

    # 6. Fehler im Error Learning aufzeichnen
    if error_learning and results["error_class"]:
        rec = error_learning.record_error(
            error_class=results["error_class"],
            context=file_path or code[:200] if code else "",
            action=f"debug:{error_message[:100]}",
            error_message=error_message[:300],
            tool="code_debug",
        )
        # Wenn wir eine Lösung haben, speichere sie
        if results["fix_suggestion"]:
            error_learning.record_solution(rec.fingerprint, results["fix_suggestion"])

    return results


def _classify_error(error_msg: str) -> str:
    """Klassifiziere einen Fehler lokal (Level 0)."""
    error_msg_lower = (error_msg or "").lower()

    if "importerror" in error_msg_lower or "modulenotfound" in error_msg_lower:
        return "DEPENDENCY_ERROR"
    if "permission" in error_msg_lower or "access denied" in error_msg_lower:
        return "PERMISSION_ERROR"
    if "timeout" in error_msg_lower or "timed out" in error_msg_lower:
        return "TIMEOUT_ERROR"
    if "syntax" in error_msg_lower:
        return "PARSE_ERROR"
    if "typeerror" in error_msg_lower or "attributeerror" in error_msg_lower:
        return "AGENT_ERROR"
    if "filenotfound" in error_msg_lower or "no such file" in error_msg_lower:
        return "TOOL_ERROR"
    if "connection" in error_msg_lower or "network" in error_msg_lower:
        return "LLM_ERROR"
    if "keyerror" in error_msg_lower or "indexerror" in error_msg_lower:
        return "VALIDATION_ERROR"

    return "UNKNOWN"


def _parse_traceback(error_msg: str) -> Optional[dict]:
    """Parse einen Python-Traceback."""
    if not error_msg:
        return None

    lines = error_msg.strip().split("\n")
    trace_lines = []
    error_line = ""

    for line in lines:
        if line.strip().startswith("File "):
            match = re.match(r'\s*File "(.+)", line (\d+)', line)
            if match:
                trace_lines.append({"file": match.group(1), "line": int(match.group(2))})
        if "Error:" in line or "Exception:" in line:
            error_line = line.strip()

    if trace_lines or error_line:
        return {"trace": trace_lines[-5:], "error_line": error_line}
    return None
