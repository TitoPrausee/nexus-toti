"""
SKILL: dependency_check — Dependencies prüfen auf Updates, Conflicts, Sicherheitslücken
"""

import json
import os
import re
import subprocess
from typing import Optional


def execute(path: str = ".", check_type: str = "all",
            llm_client=None, tools=None) -> dict:
    """
    Prüfe Dependencies.

    Args:
        path: Projektpfad
        check_type: 'all', 'outdated', 'security', 'conflicts', 'missing'
        llm_client: LLMClient
        tools: ToolRegistry

    Returns:
        dict mit Check-Ergebnissen
    """
    results = {
        "skill": "dependency_check",
        "path": path,
        "check_type": check_type,
        "outdated": [],
        "security_issues": [],
        "conflicts": [],
        "missing": [],
        "summary": "",
    }

    # Erkennen ob Python oder Node-Projekt
    files = set(os.listdir(path)) if os.path.isdir(path) else set()
    is_python = "requirements.txt" in files or "setup.py" in files or "pyproject.toml" in files
    is_node = "package.json" in files

    if is_python:
        results.update(_check_python_deps(path, check_type, tools))
    if is_node:
        results.update(_check_node_deps(path, check_type, tools))

    # Summary
    total_issues = len(results["outdated"]) + len(results["security_issues"]) + len(results["conflicts"]) + len(results["missing"])
    results["summary"] = (
        f"{total_issues} Probleme gefunden: "
        f"{len(results['outdated'])} veraltet, "
        f"{len(results['security_issues'])} Sicherheitslücken, "
        f"{len(results['conflicts'])} Konflikte, "
        f"{len(results['missing'])} fehlend"
    )

    return results


def _check_python_deps(path: str, check_type: str, tools=None) -> dict:
    """Prüfe Python-Dependencies."""
    result = {}

    # pip-outdated
    if check_type in ["all", "outdated"]:
        try:
            proc = subprocess.run(
                ["pip3", "list", "--outdated", "--format=json"],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0:
                outdated = json.loads(proc.stdout)
                result["outdated"] = [
                    {"package": p["name"], "current": p["version"], "latest": p["latest_version"]}
                    for p in outdated[:20]
                ]
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    # pip-audit für Security
    if check_type in ["all", "security"]:
        try:
            proc = subprocess.run(
                ["pip-audit", "--format=json"],
                capture_output=True, text=True, timeout=30,
            )
            if proc.stdout:
                audit = json.loads(proc.stdout)
                result["security_issues"] = [
                    {"package": v.get("package", ""), "id": v.get("id", ""),
                     "description": v.get("description", "")[:200]}
                    for v in audit.get("vulnerabilities", [])[:20]
                ]
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    # Fehlende Dependencies
    if check_type in ["all", "missing"]:
        req_path = os.path.join(path, "requirements.txt")
        if os.path.exists(req_path):
            try:
                with open(req_path, "r") as f:
                    requirements = f.read().strip().split("\n")
                missing = []
                for req in requirements:
                    req = req.strip()
                    if not req or req.startswith("#"):
                        continue
                    pkg_name = re.split(r'[><=!]', req)[0].strip()
                    try:
                        __import__(pkg_name.replace("-", "_"))
                    except ImportError:
                        missing.append(pkg_name)
                result["missing"] = missing[:20]
            except Exception:
                pass

    return result


def _check_node_deps(path: str, check_type: str, tools=None) -> dict:
    """Prüfe Node.js-Dependencies."""
    result = {}

    # npm outdated
    if check_type in ["all", "outdated"]:
        try:
            proc = subprocess.run(
                ["npm", "outdated", "--json"],
                capture_output=True, text=True, timeout=30, cwd=path,
            )
            if proc.stdout:
                outdated = json.loads(proc.stdout)
                result["outdated"] = [
                    {"package": name, "current": info.get("current", ""),
                     "latest": info.get("latest", "")}
                    for name, info in outdated.items()
                ]
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    # npm audit
    if check_type in ["all", "security"]:
        try:
            proc = subprocess.run(
                ["npm", "audit", "--json"],
                capture_output=True, text=True, timeout=30, cwd=path,
            )
            if proc.stdout:
                audit = json.loads(proc.stdout)
                vulns = audit.get("vulnerabilities", {})
                result["security_issues"] = [
                    {"package": name, "severity": info.get("severity", ""),
                     "title": info.get("title", "")}
                    for name, info in vulns.items()
                ]
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    return result
