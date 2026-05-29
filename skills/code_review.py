"""
SKILL: code_review — Code-Review mit Qualitäts-Bewertung
Prüft Code auf Qualität, Sicherheit, Performance und Best Practices.
"""

import json
import re
import os
from typing import Optional


def execute(file_path: str = "", code: str = "", focus: str = "all",
            llm_client=None, tools=None) -> dict:
    """
    Führt ein Code-Review durch.

    Args:
        file_path: Pfad zur Datei
        code: Code direkt (alternative zu file_path)
        focus: 'all', 'security', 'performance', 'style', 'bugs'
        llm_client: LLMClient für Analyse
        tools: ToolRegistry für Datei-Zugriff und Linting

    Returns:
        dict mit Review-Ergebnissen
    """
    results = {
        "skill": "code_review",
        "file_path": file_path,
        "focus": focus,
        "score": 0.0,
        "issues": [],
        "suggestions": [],
        "summary": "",
        "auto_lint": None,
    }

    # 1. Code laden
    source_code = code
    if not source_code and file_path and tools:
        file_result = tools.dispatch("read_file", path=file_path)
        if isinstance(file_result, dict) and "content" in file_result:
            source_code = file_result["content"]

    if not source_code:
        results["issues"].append({"severity": "error", "message": "Kein Code zum Reviewen"})
        return results

    # 2. Automatisches Linting (Level 0 — lokal)
    if tools and file_path:
        lint_result = tools.dispatch("code_lint", action="lint", path=file_path)
        if isinstance(lint_result, dict) and "issues" in lint_result:
            results["auto_lint"] = lint_result
            for issue in lint_result.get("issues", [])[:10]:
                results["issues"].append({
                    "severity": "lint",
                    "message": str(issue)[:200],
                    "source": "auto_lint",
                })

    # 3. Lokale Checks (Level 0)
    local_issues = _local_checks(source_code, focus)
    results["issues"].extend(local_issues)

    # 4. LLM-Review
    if llm_client and source_code:
        from core.llm_client import Message

        focus_desc = {
            "all": "Qualität, Sicherheit, Performance, Best Practices",
            "security": "Sicherheitsschwachstellen, Injection, Auth",
            "performance": "Performance-Probleme, Speicherlecks, Langsame Operationen",
            "style": "Code-Style, Lesbarkeit, Naming",
            "bugs": "Logikfehler, Edge Cases, Race Conditions",
        }.get(focus, "alle Aspekte")

        review_prompt = f"""Review diesen Code mit Fokus auf: {focus_desc}

CODE:
```
{source_code[:4000]}
```

Bewerte als JSON:
{{
  "score": 0-10,
  "critical_issues": ["..."],
  "suggestions": ["..."],
  "summary": "Kurzzusammenfassung"
}}"""

        messages = [
            Message(role="system", content="Du bist ein erfahrener Code-Reviewer. Sei ehrlich und konkret. Antworte als JSON."),
            Message(role="user", content=review_prompt),
        ]
        response = llm_client.chat(messages, level=2)

        try:
            json_match = re.search(r'\{[\s\S]*\}', response.content)
            if json_match:
                analysis = json.loads(json_match.group())
                results["score"] = float(analysis.get("score", 5))
                for issue in analysis.get("critical_issues", []):
                    results["issues"].append({"severity": "critical", "message": issue, "source": "llm"})
                for suggestion in analysis.get("suggestions", []):
                    results["suggestions"].append(suggestion)
                results["summary"] = analysis.get("summary", "")
        except (json.JSONDecodeError, ValueError):
            results["summary"] = response.content[:500]
            results["score"] = 5.0

    # 5. Score basierend auf Issues berechnen wenn kein LLM-Score
    if results["score"] == 0.0:
        critical = sum(1 for i in results["issues"] if i.get("severity") == "critical")
        major = sum(1 for i in results["issues"] if i.get("severity") == "major")
        lint = sum(1 for i in results["issues"] if i.get("severity") == "lint")
        results["score"] = max(0, 10 - critical * 3 - major * 1.5 - lint * 0.3)

    return results


def _local_checks(code: str, focus: str) -> list[dict]:
    """Lokale Code-Checks (Level 0 — kein LLM)."""
    issues = []

    # Sichheits-Checks
    if focus in ["all", "security"]:
        # Hardcoded Secrets
        secret_patterns = [
            (r'password\s*=\s*["\'][^"\']{4,}["\']', "Mögliches hardcoded Passwort"),
            (r'api_key\s*=\s*["\'][^"\']{8,}["\']', "Möglicher hardcoded API-Key"),
            (r'secret\s*=\s*["\'][^"\']{8,}["\']', "Mögliches hardcoded Secret"),
            (r'token\s*=\s*["\'][^"\']{16,}["\']', "Möglicher hardcoded Token"),
            (r'eval\s*\(', "eval() ist gefährlich — vermeiden"),
            (r'exec\s*\(', "exec() ist gefährlich — vermeiden"),
            (r'subprocess\.call\s*\([^)]*shell\s*=\s*True', "shell=True ist gefährlich"),
        ]
        for pattern, message in secret_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                issues.append({"severity": "critical", "message": message, "source": "local_security"})

        # SQL-Injection
        if re.search(r'(execute|cursor)\s*\([^)]*%s.*\+', code, re.IGNORECASE) or \
           re.search(r'f["\'].*SELECT.*{.*}.*["\']', code, re.IGNORECASE):
            issues.append({"severity": "critical", "message": "Mögliche SQL-Injection", "source": "local_security"})

    # Performance-Checks
    if focus in ["all", "performance"]:
        if re.search(r'for\s+\w+\s+in\s+range\s*\(\s*len\s*\(', code):
            issues.append({"severity": "major", "message": "range(len()) — nutze enumerate()", "source": "local_performance"})
        if re.search(r'\.append\s*\(\s*\)\s*\n\s*for\s', code):
            issues.append({"severity": "minor", "message": "List-Comprehension könnte schneller sein", "source": "local_performance"})

    # Style-Checks
    if focus in ["all", "style"]:
        lines = code.split("\n")
        long_lines = [i + 1 for i, line in enumerate(lines) if len(line) > 120]
        if long_lines:
            issues.append({"severity": "minor", "message": f"{len(long_lines)} Zeilen > 120 Zeichen", "source": "local_style"})
        if code.count("TODO") > 3:
            issues.append({"severity": "minor", "message": f"{code.count('TODO')} TODOs gefunden", "source": "local_style"})

    # Bug-Checks
    if focus in ["all", "bugs"]:
        if re.search(r'if\s+\w+\s*=\s*[^=]', code):
            issues.append({"severity": "critical", "message": "Mögliche Zuweisung statt Vergleich (= statt ==)", "source": "local_bugs"})
        if re.search(r'except\s*:', code):
            issues.append({"severity": "major", "message": "Bare except — fängt alle Exceptions inkl. KeyboardInterrupt", "source": "local_bugs"})
        if "mutable default" not in code and re.search(r'def\s+\w+\s*\([^)]*=\s*\[\]', code):
            issues.append({"severity": "critical", "message": "Mutable Default-Argument (Liste) — klassischer Python-Bug", "source": "local_bugs"})
        if re.search(r'def\s+\w+\s*\([^)]*=\s*\{\}', code):
            issues.append({"severity": "critical", "message": "Mutable Default-Argument (Dict) — klassischer Python-Bug", "source": "local_bugs"})

    return issues
