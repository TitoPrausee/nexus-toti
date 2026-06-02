"""
SKILL: performance — Performance-Analyse und Optimierung
Analysiert Laufzeit, Speicher, Bottlenecks.
"""

import json
import os
import re
import time
import subprocess
from typing import Optional


def execute(path: str = "", code: str = "", mode: str = "profile",
            iterations: int = 100, llm_client=None, tools=None) -> dict:
    """
    Führe eine Performance-Analyse durch.

    Args:
        path: Pfad zum Script/Modul
        code: Code direkt (alternative zu path)
        mode: 'profile' (Laufzeit), 'memory' (Speicher), 'bottleneck' (Bottlenecks finden)
        iterations: Anzahl Iterationen für Benchmark
        llm_client: LLMClient
        tools: ToolRegistry

    Returns:
        dict mit Performance-Ergebnissen
    """
    results = {
        "skill": "performance",
        "mode": mode,
        "metrics": {},
        "bottlenecks": [],
        "suggestions": [],
        "summary": "",
    }

    if mode == "profile":
        results["metrics"] = _profile_code(path, code, iterations, tools)
    elif mode == "memory":
        results["metrics"] = _check_memory(path, tools)
    elif mode == "bottleneck":
        results.update(_find_bottlenecks(path, code, llm_client, tools))

    # Summary
    metrics = results["metrics"]
    if metrics:
        results["summary"] = (
            f"Ausführungszeit: {metrics.get('execution_time_ms', 'n/a')}ms | "
            f"Speicher: {metrics.get('memory_mb', 'n/a')}MB | "
            f"Bottlenecks: {len(results['bottlenecks'])}"
        )

    return results


def _profile_code(path: str, code: str, iterations: int, tools=None) -> dict:
    """Profiliere Code-Ausführungszeit."""
    metrics = {}

    if code and tools:
        # Quick-Benchmark via code_exec
        benchmark_code = f"""
import time
start = time.time()
for _ in range({iterations}):
    pass  # Placeholder — würde den eigentlichen Code ausführen
elapsed = time.time() - start
print(f"{{iterations}} iterations: {{elapsed*1000:.2f}}ms")
"""
        result = tools.dispatch("code_exec", code=benchmark_code)
        if isinstance(result, dict) and "stdout" in result:
            metrics["benchmark_output"] = result["stdout"]

    if path and os.path.exists(path):
        # cProfile
        try:
            proc = subprocess.run(
                ["python3", "-m", "cProfile", "-s", "cumulative", path],
                capture_output=True, text=True, timeout=30,
            )
            if proc.stdout:
                # Top 10 zeitaufwändigste Funktionen
                lines = proc.stdout.strip().split("\n")
                profile_lines = []
                for line in lines:
                    if "function calls" in line or re.match(r'\s*\d+\s+', line):
                        profile_lines.append(line)
                metrics["cprofile_top"] = profile_lines[:15]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Einfacher Zeit-Test
    start = time.time()
    # (Hier würde der Code ausgeführt)
    metrics["execution_time_ms"] = 0  # Placeholder

    return metrics


def _check_memory(path: str, tools=None) -> dict:
    """Prüfe Speichernutzung."""
    metrics = {}

    # System-Speicher
    try:
        proc = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            metrics["system_memory"] = proc.stdout.strip().split("\n")[:3]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Python-Object-Size (wenn code_exec verfügbar)
    if tools:
        mem_code = """
import sys
types_size = {}
for obj in globals().values():
    t = type(obj).__name__
    try:
        size = sys.getsizeof(obj)
        types_size[t] = types_size.get(t, 0) + size
    except TypeError:
        pass
for t, s in sorted(types_size.items(), key=lambda x: -x[1])[:10]:
    print(f"{t}: {s/1024:.1f}KB")
"""
        result = tools.dispatch("code_exec", code=mem_code)
        if isinstance(result, dict) and "stdout" in result:
            metrics["object_sizes"] = result["stdout"]

    return metrics


def _find_bottlenecks(path: str, code: str, llm_client=None, tools=None) -> dict:
    """Finde Performance-Bottlenecks."""
    result = {"bottlenecks": [], "suggestions": []}

    source_code = code
    if not source_code and path and tools:
        file_result = tools.dispatch("read_file", path=path)
        if isinstance(file_result, dict) and "content" in file_result:
            source_code = file_result["content"]

    if not source_code:
        return result

    # Lokale Pattern-Checks (Level 0)
    patterns = [
        (r'for\s+.*\n\s+.*\.append\(', "List-Append in Loop — nutze List-Comprehension", "medium"),
        (r'\.join\s*\(\s*str\s*\(', "String-Concatenation in Loop — nutze .join()", "medium"),
        (r'select\s+\*\s+from', "SELECT * — nur benötigte Spalten abfragen", "low"),
        (r'time\.sleep\s*\(\s*\d+', "time.sleep() — asynchrone Alternative prüfen", "low"),
        (r'requests\.get\s*\([^)]*\)\s*\n\s+[^#\n]*requests\.get', "Sequentielle HTTP-Requests — nutze async/aiohttp", "high"),
        (r'open\s*\([^)]+\)\s*:\s*\n\s+open\s*\(', "Verschachtelte Datei-Operationen — prüfe ob batchbar", "low"),
    ]

    for pattern, message, severity in patterns:
        if re.search(pattern, source_code, re.IGNORECASE | re.MULTILINE):
            result["bottlenecks"].append({
                "pattern": pattern,
                "message": message,
                "severity": severity,
                "source": "local_pattern",
            })

    # LLM-Analyse
    if llm_client and source_code:
        from core.llm_client import Message
        messages = [
            Message(role="system", content="Du bist ein Performance-Experte. Finde Bottlenecks und schlage Optimierungen vor."),
            Message(role="user", content=f"Analysiere diesen Code auf Performance-Probleme:\n\n{source_code[:3000]}"),
        ]
        response = llm_client.chat(messages, level=2)
        result["suggestions"] = [response.content[:1000]]

    return result
