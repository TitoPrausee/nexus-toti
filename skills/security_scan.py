"""
SKILL: security_scan — Sicherheits-Scan für Code und Dependencies
Prüft auf bekannte Schwachstellen, veraltete Dependencies, unsichere Patterns.
"""

import json
import re
import os
import subprocess
from typing import Optional


def execute(path: str = ".", scan_type: str = "full",
            llm_client=None, tools=None) -> dict:
    """
    Führt einen Sicherheits-Scan durch.

    Args:
        path: Pfad zum Scannen
        scan_type: 'full', 'deps', 'code', 'config'
        llm_client: LLMClient für Analyse
        tools: ToolRegistry

    Returns:
        dict mit Scan-Ergebnissen
    """
    results = {
        "skill": "security_scan",
        "path": path,
        "scan_type": scan_type,
        "vulnerabilities": [],
        "warnings": [],
        "score": 10.0,
        "summary": "",
    }

    # 1. Dependency-Scan
    if scan_type in ["full", "deps"]:
        dep_results = _scan_dependencies(path, tools)
        results["vulnerabilities"].extend(dep_results.get("vulnerabilities", []))
        results["warnings"].extend(dep_results.get("warnings", []))

    # 2. Code-Pattern-Scan
    if scan_type in ["full", "code"]:
        code_results = _scan_code_patterns(path, tools)
        results["vulnerabilities"].extend(code_results.get("vulnerabilities", []))
        results["warnings"].extend(code_results.get("warnings", []))

    # 3. Config-Scan
    if scan_type in ["full", "config"]:
        config_results = _scan_configs(path, tools)
        results["vulnerabilities"].extend(config_results.get("vulnerabilities", []))
        results["warnings"].extend(config_results.get("warnings", []))

    # 4. Score berechnen
    critical = sum(1 for v in results["vulnerabilities"] if v.get("severity") == "critical")
    high = sum(1 for v in results["vulnerabilities"] if v.get("severity") == "high")
    medium = sum(1 for v in results["vulnerabilities"] if v.get("severity") == "medium")
    results["score"] = max(0, 10 - critical * 3 - high * 1.5 - medium * 0.5)

    # 5. Summary
    results["summary"] = (
        f"Score: {results['score']:.1f}/10 | "
        f"{len(results['vulnerabilities'])} Schwachstellen | "
        f"{len(results['warnings'])} Warnungen"
    )

    return results


def _scan_dependencies(path: str, tools=None) -> dict:
    """Scanne Dependencies auf bekannte Schwachstellen."""
    results = {"vulnerabilities": [], "warnings": []}

    # Prüfe requirements.txt / package.json
    req_files = ["requirements.txt", "Pipfile", "package.json", "package-lock.json"]
    for req_file in req_files:
        full_path = os.path.join(path, req_file)
        if os.path.exists(full_path):
            results["warnings"].append({
                "severity": "info",
                "message": f"Dependency-File gefunden: {req_file}",
                "file": req_file,
            })

            # Prüfe auf bekannte unsichere Packages
            try:
                with open(full_path, "r") as f:
                    content = f.read().lower()
                unsafe_packages = {
                    "pickle": "pickle kann zu Remote Code Execution führen",
                    "yaml.load(": "yaml.load() ohne SafeLoader ist unsicher — nutze yaml.safe_load()",
                    "subprocess.call": "subprocess mit shell=True prüfen",
                }
                for pkg, warning in unsafe_packages.items():
                    if pkg in content:
                        results["warnings"].append({
                            "severity": "medium",
                            "message": warning,
                            "file": req_file,
                        })
            except Exception:
                pass

    # pip-audit falls verfügbar
    try:
        result = subprocess.run(
            ["pip-audit", "--desc"], capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0 and result.stdout:
            for line in result.stdout.strip().split("\n")[:10]:
                if line.strip():
                    results["vulnerabilities"].append({
                        "severity": "high",
                        "message": f"pip-audit: {line.strip()[:200]}",
                        "source": "pip-audit",
                    })
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return results


def _scan_code_patterns(path: str, tools=None) -> dict:
    """Scanne Code auf unsichere Patterns."""
    results = {"vulnerabilities": [], "warnings": []}

    # Unsichere Patterns
    patterns = [
        (r'eval\s*\(', "eval() — Remote Code Execution möglich", "critical"),
        (r'exec\s*\(', "exec() — Remote Code Execution möglich", "critical"),
        (r'subprocess\.\w+\([^)]*shell\s*=\s*True', "shell=True — Command Injection möglich", "critical"),
        (r'os\.system\s*\(', "os.system() — Command Injection möglich", "high"),
        (r'pickle\.loads?\s*\(', "pickle — Deserialisierungs-Angriff möglich", "high"),
        (r'yaml\.load\s*\(', "yaml.load() — ohne SafeLoader unsicher", "medium"),
        (r'hashlib\.md5\s*\(', "MD5 ist kryptografisch gebrochen", "medium"),
        (r'hashlib\.sha1\s*\(', "SHA1 ist kryptografisch schwach", "low"),
        (r'random\.random\s*\(', "random — nicht kryptografisch sicher, nutze secrets", "low"),
        (r'assert\s+', "assert kann mit -O deaktiviert werden — nicht für Security nutzen", "medium"),
        (r'open\s*\([^)]*[\'\"]w[\'\"]', "Datei-Schreiboperation — prüfe Pfad-Traversal", "low"),
        (r'cors.*\*.*allow', "CORS wildcard — erlaubt alle Origins", "high"),
    ]

    # Scanne Python-Dateien
    py_files = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                   ["node_modules", "__pycache__", ".git", "venv", ".venv"]]
        for f in files:
            if f.endswith((".py", ".js", ".ts")):
                py_files.append(os.path.join(root, f))
        if len(py_files) > 50:
            break

    for file_path in py_files[:50]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            for pattern, message, severity in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    line_num = content[:match.start()].count("\n") + 1
                    results["vulnerabilities"].append({
                        "severity": severity,
                        "message": message,
                        "file": file_path,
                        "line": line_num,
                        "source": "pattern_scan",
                    })
        except Exception:
            pass

    return results


def _scan_configs(path: str, tools=None) -> dict:
    """Scanne Konfigurationsdateien auf Sicherheitsprobleme."""
    results = {"vulnerabilities": [], "warnings": []}

    config_files = [".env", ".env.local", ".env.production", "config.yaml", "config.json",
                    "docker-compose.yml", "Dockerfile", ".gitignore"]

    for cf in config_files:
        full = os.path.join(path, cf)
        if not os.path.exists(full):
            continue

        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Secrets in .env
            if cf.startswith(".env"):
                secret_patterns = [
                    (r'(PASSWORD|SECRET|API_KEY|TOKEN|PRIVATE_KEY)\s*=\s*\S+',
                     "Secret in .env-Datei — nicht committen!", "high"),
                ]
                for pattern, message, severity in secret_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        results["warnings"].append({
                            "severity": severity,
                            "message": message,
                            "file": cf,
                        })

            # Docker-Checks
            if cf == "Dockerfile":
                if "latest" in content:
                    results["warnings"].append({
                        "severity": "medium",
                        "message": "Dockerfile nutzt :latest Tag — pinne die Version",
                        "file": cf,
                    })
                if "root" not in content.lower() and "USER" not in content:
                    results["warnings"].append({
                        "severity": "medium",
                        "message": "Dockerfile hat keinen USER — läuft als root",
                        "file": cf,
                    })

            # .gitignore Check
            if cf == ".gitignore":
                if ".env" not in content:
                    results["vulnerabilities"].append({
                        "severity": "high",
                        "message": ".env nicht in .gitignore — Secrets könnten committed werden",
                        "file": cf,
                    })

        except Exception:
            pass

    return results
