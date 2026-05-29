"""
SKILL: test_gen — Test-Code automatisch generieren
Generiert Unit-Tests basierend auf vorhandenem Code.
"""

import json
import re
import os
from typing import Optional


def execute(file_path: str = "", code: str = "", framework: str = "pytest",
            coverage_target: float = 0.8, llm_client=None, tools=None) -> dict:
    """
    Generiert Test-Code für eine gegebene Datei.

    Args:
        file_path: Pfad zur Quelldatei
        code: Quellcode direkt
        framework: 'pytest' (default), 'unittest', 'jest'
        coverage_target: Angestrebte Code-Abdeckung (0.0-1.0)
        llm_client: LLMClient für Test-Generierung
        tools: ToolRegistry

    Returns:
        dict mit generiertem Test-Code
    """
    results = {
        "skill": "test_gen",
        "file_path": file_path,
        "framework": framework,
        "test_code": "",
        "test_cases": [],
        "estimated_coverage": 0.0,
    }

    # 1. Code laden
    source_code = code
    if not source_code and file_path and tools:
        file_result = tools.dispatch("read_file", path=file_path)
        if isinstance(file_result, dict) and "content" in file_result:
            source_code = file_result["content"]

    if not source_code:
        results["test_cases"].append({"error": "Kein Code zum Testen"})
        return results

    # 2. Funktionen/Methoden extrahieren (Level 0 — lokal)
    functions = _extract_functions(source_code)
    classes = _extract_classes(source_code)

    results["test_cases"] = [
        {"type": "function", "name": f["name"], "args": f["args"]}
        for f in functions
    ] + [
        {"type": "class", "name": c["name"], "methods": c["methods"]}
        for c in classes
    ]

    # 3. LLM-Test-Generierung
    if llm_client:
        from core.llm_client import Message

        func_list = ", ".join(f["name"] for f in functions)
        class_list = ", ".join(c["name"] for c in classes)

        test_prompt = f"""Generiere {framework}-Tests für diesen Code.

FUNKTIONEN: {func_list or 'keine gefunden'}
KLASSEN: {class_list or 'keine gefunden'}
COVERAGE-ZIEL: {int(coverage_target * 100)}%

CODE:
```
{source_code[:4000]}
```

Regeln:
- Nutze {framework}
- Teste Edge Cases, nicht nur Happy Path
- Teste Fehlerfälle (Exceptions, ungültige Inputs)
- Nutze parametrize wo sinnvoll
- Aussagekräftige Test-Namen: test_<was>_<bedingung>_<erwartung>
- Kein Fülltext, nur der Test-Code

Generiere NUR den Test-Code, keine Erklärungen."""

        messages = [
            Message(role="system", content=f"Du bist ein Test-Experte. Generiere {framework}-Tests. Nur Code, keine Erklärungen."),
            Message(role="user", content=test_prompt),
        ]
        response = llm_client.chat(messages, level=2)
        results["test_code"] = response.content

        # Coverage-Schätzung
        results["estimated_coverage"] = min(coverage_target, 0.7 + 0.03 * len(functions))

    # 4. Fallback: Template-basierte Tests (Level 0)
    if not results["test_code"] and functions:
        results["test_code"] = _generate_template_tests(functions, classes, framework)
        results["estimated_coverage"] = 0.4

    return results


def _extract_functions(code: str) -> list[dict]:
    """Extrahiere Funktions-Signaturen aus Python-Code."""
    functions = []
    pattern = r'def\s+(\w+)\s*\(([^)]*)\)'
    for match in re.finditer(pattern, code):
        name = match.group(1)
        if name.startswith("_"):
            continue
        args = match.group(2).strip()
        functions.append({"name": name, "args": args})
    return functions


def _extract_classes(code: str) -> list[dict]:
    """Extrahiere Klassen und ihre Methoden."""
    classes = []
    class_pattern = r'class\s+(\w+)[^(]*:'
    for match in re.finditer(class_pattern, code):
        name = match.group(1)
        # Finde Methoden in der Klasse (vereinfacht)
        class_start = match.end()
        next_class = code.find("\nclass ", class_start)
        class_body = code[class_start:next_class] if next_class > 0 else code[class_start:]
        methods = [m.group(1) for m in re.finditer(r'def\s+(\w+)\s*\(', class_body)
                    if not m.group(1).startswith("__")]
        classes.append({"name": name, "methods": methods})
    return classes


def _generate_template_tests(functions: list, classes: list, framework: str) -> str:
    """Generiere einfache Template-Tests (Level 0 — kein LLM)."""
    lines = ["import pytest", "", ""]

    for func in functions:
        lines.append(f"def test_{func['name']}():")
        lines.append(f"    # TODO: Test für {func['name']}({func['args']})")
        lines.append(f"    # Happy Path")
        lines.append(f"    result = {func['name']}()  # Anpassen")
        lines.append(f"    assert result is not None")
        lines.append(f"    # Edge Cases")
        lines.append(f"    # TODO: Teste ungültige Inputs")
        lines.append("")

    for cls in classes:
        lines.append(f"class Test{cls['name']}:")
        lines.append(f"    def setup_method(self):")
        lines.append(f"        self.obj = {cls['name']}()")
        lines.append("")
        for method in cls["methods"]:
            lines.append(f"    def test_{method}(self):")
            lines.append(f"        # TODO: Test für {cls['name']}.{method}()")
            lines.append(f"        result = self.obj.{method}()")
            lines.append(f"        assert result is not None")
            lines.append("")

    return "\n".join(lines)
