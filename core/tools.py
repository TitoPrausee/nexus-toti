"""
NEXUS Tool Registry & Dispatch System — Extended Developer Edition v2.0
22 built-in tools: 6 base + 10 developer + 6 advanced

BASE TOOLS (6):
  terminal, read_file, write_file, web_search, list_dir, code_exec

DEVELOPER TOOLS (10):
  git, docker, pkg_install, http_request, file_search, process_manager,
  env_check, port_check, json_yaml, file_ops

ADVANCED TOOLS (6):
  db_query, api_test, code_lint, archive_ops, csv_ops, scheduler_tool
"""

import subprocess
import json
import os
import re
import hashlib
import time
import shutil
import csv
import io
import tarfile
import zipfile
import gzip
from typing import Callable, Any, Optional
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolDefinition:
    name: str
    description: str
    handler: Callable
    params: dict
    dangerous: bool = False
    category: str = "general"  # general, devops, file, network, data, code, db


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._register_defaults()

    def register(self, name: str, description: str, handler: Callable,
                 params: dict = None, dangerous: bool = False, category: str = "general"):
        self._tools[name] = ToolDefinition(
            name=name, description=description, handler=handler,
            params=params or {}, dangerous=dangerous, category=category,
        )

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "params": t.params,
             "dangerous": t.dangerous, "category": t.category}
            for t in self._tools.values()
        ]

    def list_by_category(self, category: str) -> list[dict]:
        return [t for t in self.list_tools() if t["category"] == category]

    def dispatch(self, name: str, **kwargs) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' nicht gefunden. Verfügbare Tools: {list(self._tools.keys())}"}
        try:
            return tool.handler(**kwargs)
        except Exception as e:
            return {"error": f"Tool '{name}' fehlgeschlagen: {str(e)}"}

    def parse_and_dispatch(self, call_str: str) -> Any:
        if not call_str.startswith("TOOL:"):
            return {"error": f"Ungültiger Tool-Aufruf: {call_str}"}
        rest = call_str[5:]
        paren_idx = rest.find("(")
        if paren_idx == -1:
            return self.dispatch(rest.strip())
        tool_name = rest[:paren_idx].strip()
        params_str = rest[paren_idx + 1: rest.rfind(")")]
        kwargs = {}
        if params_str.strip():
            try:
                kwargs = json.loads(params_str)
            except json.JSONDecodeError:
                for pair in params_str.split(","):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        kwargs[k.strip()] = v.strip().strip('"').strip("'")
        return self.dispatch(tool_name, **kwargs)

    # ═══════════════════════════════════════════════════
    # TOOL REGISTRATION
    # ═══════════════════════════════════════════════════

    def _register_defaults(self):
        # ─── Base Tools (6) ───
        self.register("terminal", "Shell-Kommandos ausführen", self._tool_terminal,
                      {"cmd": "str"}, dangerous=True, category="general")
        self.register("read_file", "Datei-Inhalt lesen", self._tool_read_file,
                      {"path": "str"}, category="file")
        self.register("write_file", "Inhalt in Datei schreiben", self._tool_write_file,
                      {"path": "str", "content": "str"}, dangerous=True, category="file")
        self.register("web_search", "Web-Suche via z-ai", self._tool_web_search,
                      {"query": "str", "num": "int"}, category="network")
        self.register("list_dir", "Verzeichnis-Inhalt auflisten", self._tool_list_dir,
                      {"path": "str"}, category="file")
        self.register("code_exec", "Python Code ausführen", self._tool_code_exec,
                      {"code": "str"}, dangerous=True, category="general")

        # ─── Developer Tools (10) ───
        self.register("git", "Git-Operationen: status, log, diff, branch, add, commit, push, pull, stash, checkout, merge, tag, blame, show",
                      self._tool_git,
                      {"action": "str", "args": "str"}, dangerous=True, category="devops")
        self.register("docker", "Docker-Operationen: ps, images, run, stop, build, logs, compose, inspect, exec",
                      self._tool_docker,
                      {"action": "str", "args": "str"}, dangerous=True, category="devops")
        self.register("pkg_install", "Pakete installieren: pip, npm, apt",
                      self._tool_pkg_install,
                      {"manager": "str", "package": "str", "dev": "bool"}, dangerous=True, category="devops")
        self.register("http_request", "HTTP-Anfragen: GET, POST, PUT, DELETE, PATCH",
                      self._tool_http_request,
                      {"method": "str", "url": "str", "headers": "dict", "body": "str"}, category="network")
        self.register("file_search", "Dateien suchen (nach Name oder Inhalt/grep)",
                      self._tool_file_search,
                      {"pattern": "str", "path": "str", "type": "str"}, category="file")
        self.register("process_manager", "Prozesse verwalten: list, find, kill, top",
                      self._tool_process_manager,
                      {"action": "str", "pid": "int", "name": "str"}, dangerous=True, category="devops")
        self.register("env_check", "Umgebung prüfen: OS, Python, Node, Git, Docker, Disk, Memory, z-ai",
                      self._tool_env_check,
                      {}, category="general")
        self.register("port_check", "Port-Status prüfen: offen/geschlossen",
                      self._tool_port_check,
                      {"port": "int", "host": "str"}, category="network")
        self.register("json_yaml", "JSON/YAML: parse, konvertieren, abfragen, validieren",
                      self._tool_json_yaml,
                      {"action": "str", "data": "str", "query": "str"}, category="data")
        self.register("file_ops", "Datei-Operationen: tree, copy, move, delete, checksum, diff, tail, head, wc, touch, mkdir, chmod",
                      self._tool_file_ops,
                      {"action": "str", "src": "str", "dst": "str", "pattern": "str"}, dangerous=True, category="file")

        # ─── Advanced Tools (6) ───
        self.register("db_query", "Datenbank-Abfragen: SQLite (eingebaut), PostgreSQL, MySQL via CLI",
                      self._tool_db_query,
                      {"action": "str", "db_path": "str", "query": "str", "db_type": "str"},
                      dangerous=True, category="db")
        self.register("api_test", "API testen: OpenAPI/Swagger laden, Endpunkte testen, Response validieren",
                      self._tool_api_test,
                      {"action": "str", "url": "str", "method": "str", "headers": "dict", "body": "str", "expected_status": "int"},
                      category="network")
        self.register("code_lint", "Code-Qualität: Lint (pylint/flake8/eslint), Format (black/prettier), Typ-Check (mypy)",
                      self._tool_code_lint,
                      {"action": "str", "path": "str", "linter": "str", "fix": "bool"},
                      category="code")
        self.register("archive_ops", "Archive: erstellen und entpacken (tar.gz, zip, gzip)",
                      self._tool_archive_ops,
                      {"action": "str", "src": "str", "dst": "str", "format": "str"},
                      category="file")
        self.register("csv_ops", "CSV-Operationen: lesen, schreiben, filtern, sortieren, konvertieren (JSON/CSV)",
                      self._tool_csv_ops,
                      {"action": "str", "path": "str", "data": "str", "delimiter": "str", "query": "str", "output": "str"},
                      category="data")
        self.register("scheduler_tool", "Tasks planen: erstellen, auflisten, entfernen (nutzt Smart Scheduler)",
                      self._tool_scheduler_tool,
                      {"action": "str", "task_id": "str", "trigger": "str", "interval_seconds": "int", "command": "str"},
                      category="general")

    # ═══════════════════════════════════════════════════
    # BASE TOOL IMPLEMENTATIONS (6)
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _tool_terminal(cmd: str) -> dict:
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return {"exit_code": result.returncode, "stdout": result.stdout[:5000], "stderr": result.stderr[:2000]}
        except subprocess.TimeoutExpired:
            return {"error": "Kommando Timeout (30s)"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_read_file(path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return {"path": path, "content": content[:10000], "size": len(content)}
        except FileNotFoundError:
            return {"error": f"Datei nicht gefunden: {path}"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_write_file(path: str, content: str) -> dict:
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"path": path, "size": len(content), "status": "written"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_web_search(query: str, num: int = 5) -> dict:
        try:
            with subprocess.Popen(
                ["z-ai", "function", "--name", "web_search",
                 "--args", json.dumps({"query": query, "num": num})],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ) as proc:
                stdout, stderr = proc.communicate(timeout=30)
            if proc.returncode != 0:
                return {"error": stderr[:500]}
            try:
                results = json.loads(stdout)
                return {"query": query, "results": results}
            except json.JSONDecodeError:
                return {"query": query, "raw_output": stdout[:2000]}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_list_dir(path: str = ".") -> dict:
        try:
            entries = []
            for entry in sorted(os.listdir(path)):
                full = os.path.join(path, entry)
                entries.append({"name": entry, "type": "dir" if os.path.isdir(full) else "file",
                                "size": os.path.getsize(full) if os.path.isfile(full) else None})
            return {"path": path, "entries": entries}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_code_exec(code: str) -> dict:
        try:
            result = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=30)
            return {"exit_code": result.returncode, "stdout": result.stdout[:5000], "stderr": result.stderr[:2000]}
        except subprocess.TimeoutExpired:
            return {"error": "Code-Ausführung Timeout (30s)"}
        except Exception as e:
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════
    # DEVELOPER TOOL IMPLEMENTATIONS (10)
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _tool_git(action: str, args: str = "") -> dict:
        valid_actions = ["status", "log", "diff", "branch", "add", "commit", "push",
                         "pull", "stash", "remote", "init", "checkout", "merge", "rebase",
                         "tag", "fetch", "reset", "cherry-pick", "blame", "show"]
        if action not in valid_actions:
            return {"error": f"Ungültige Git-Aktion '{action}'. Gültig: {valid_actions}"}

        cmd_map = {
            "status": "git status --porcelain -b",
            "log": f"git log --oneline -20 {args}",
            "diff": f"git diff {args}",
            "branch": f"git branch -a {args}",
            "add": f"git add {args or '.'}",
            "commit": f"git commit -m {args}",
            "push": f"git push {args}",
            "pull": f"git pull {args}",
            "stash": f"git stash {args}",
            "remote": f"git remote -v",
            "init": "git init",
            "checkout": f"git checkout {args}",
            "merge": f"git merge {args}",
            "rebase": f"git rebase {args}",
            "tag": f"git tag {args}",
            "fetch": f"git fetch {args}",
            "reset": f"git reset {args}",
            "cherry-pick": f"git cherry-pick {args}",
            "blame": f"git blame {args}",
            "show": f"git show {args}",
        }

        cmd = cmd_map[action]
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return {"action": action, "exit_code": result.returncode,
                    "stdout": result.stdout[:5000], "stderr": result.stderr[:2000]}
        except subprocess.TimeoutExpired:
            return {"error": "Git-Kommando Timeout (30s)"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_docker(action: str, args: str = "") -> dict:
        valid_actions = ["ps", "images", "run", "stop", "build", "logs", "compose",
                         "inspect", "exec", "rm", "rmi", "pull", "push", "network",
                         "volume", "top", "stats", "system"]
        if action not in valid_actions:
            return {"error": f"Ungültige Docker-Aktion '{action}'. Gültig: {valid_actions}"}

        cmd_map = {
            "ps": "docker ps -a", "images": "docker images",
            "run": f"docker run {args}", "stop": f"docker stop {args}",
            "build": f"docker build {args}", "logs": f"docker logs --tail 50 {args}",
            "compose": f"docker compose {args}", "inspect": f"docker inspect {args}",
            "exec": f"docker exec {args}", "rm": f"docker rm {args}",
            "rmi": f"docker rmi {args}", "pull": f"docker pull {args}",
            "push": f"docker push {args}", "network": "docker network ls",
            "volume": "docker volume ls", "top": f"docker top {args}",
            "stats": "docker stats --no-stream", "system": "docker system df",
        }

        cmd = cmd_map[action]
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return {"action": action, "exit_code": result.returncode,
                    "stdout": result.stdout[:5000], "stderr": result.stderr[:2000]}
        except subprocess.TimeoutExpired:
            return {"error": "Docker-Kommando Timeout (60s)"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_pkg_install(manager: str = "pip", package: str = "", dev: bool = False) -> dict:
        if not package:
            return {"error": "Kein Paket angegeben"}
        cmd_map = {
            "pip": f"pip3 install {package}",
            "npm": f"npm install {'--save-dev ' if dev else ''}{package}",
            "apt": f"apt-get install -y {package}",
        }
        cmd = cmd_map.get(manager)
        if not cmd:
            return {"error": f"Unbekannter Paket-Manager '{manager}'. Nutze: pip, npm, apt"}
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            return {"manager": manager, "package": package, "exit_code": result.returncode,
                    "stdout": result.stdout[:3000], "stderr": result.stderr[:2000]}
        except subprocess.TimeoutExpired:
            return {"error": "Paket-Installation Timeout (120s)"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_http_request(method: str = "GET", url: str = "", headers: dict = None,
                           body: str = "") -> dict:
        if not url:
            return {"error": "Keine URL angegeben"}
        try:
            import urllib.request
            import urllib.error
            req_headers = headers or {"User-Agent": "NEXUS-Toti/2.0"}
            data = body.encode("utf-8") if body else None
            req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = f"[Binärdaten: {len(raw)} bytes]"
                return {"method": method.upper(), "url": url, "status_code": resp.status,
                        "content_type": resp.headers.get("Content-Type", ""),
                        "body": text[:5000], "size": len(raw)}
        except urllib.error.HTTPError as e:
            return {"method": method.upper(), "url": url, "status_code": e.code,
                    "error": str(e),
                    "body": e.read().decode("utf-8", errors="replace")[:2000] if e.fp else ""}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_file_search(pattern: str, path: str = ".", type: str = "name") -> dict:
        results = []
        try:
            if type == "name":
                for root, dirs, files in os.walk(path):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                               ["node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build"]]
                    for f in files:
                        if re.search(pattern, f, re.IGNORECASE):
                            full = os.path.join(root, f)
                            results.append({"path": full, "name": f, "size": os.path.getsize(full)})
                            if len(results) >= 50:
                                break
                    if len(results) >= 50:
                        break
            elif type == "content":
                try:
                    result = subprocess.run(
                        ["rg", "--no-heading", "-n", "--max-count", "50", pattern, path],
                        capture_output=True, text=True, timeout=15,
                    )
                    if result.returncode == 0:
                        for line in result.stdout.strip().split("\n")[:50]:
                            if ":" in line:
                                parts = line.split(":", 2)
                                results.append({
                                    "path": parts[0],
                                    "line": int(parts[1]) if parts[1].isdigit() else 0,
                                    "content": parts[2][:200] if len(parts) > 2 else "",
                                })
                except Exception as e:
                    return {"error": f"Content-Suche fehlgeschlagen: {str(e)}"}

            return {"pattern": pattern, "search_type": type, "path": path,
                    "results": results, "count": len(results)}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_process_manager(action: str = "list", pid: int = None, name: str = "") -> dict:
        try:
            if action == "list":
                result = subprocess.run(["ps", "aux", "--sort=-%mem"], capture_output=True, text=True, timeout=10)
                return {"action": "list", "processes": result.stdout.strip().split("\n")[:30]}
            elif action == "find":
                if not name:
                    return {"error": "Prozess-Name angeben"}
                result = subprocess.run(["pgrep", "-la", name], capture_output=True, text=True, timeout=10)
                return {"action": "find", "name": name, "results": result.stdout.strip().split("\n")}
            elif action == "kill":
                if not pid:
                    return {"error": "PID angeben"}
                result = subprocess.run(["kill", str(pid)], capture_output=True, text=True, timeout=10)
                return {"action": "kill", "pid": pid, "exit_code": result.returncode}
            elif action == "top":
                result = subprocess.run(["ps", "aux", "--sort=-%mem"], capture_output=True, text=True, timeout=10)
                return {"action": "top", "processes": result.stdout.strip().split("\n")[:15]}
            else:
                return {"error": f"Ungültige Aktion '{action}'. Nutze: list, find, kill, top"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_env_check() -> dict:
        info = {}

        def _safe_version(cmd_args):
            try:
                result = subprocess.run(cmd_args, capture_output=True, text=True, timeout=5)
                return result.stdout.strip() if result.returncode == 0 else "not found"
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return "not found"

        info["os"] = os.uname().nodename if hasattr(os, "uname") else "unknown"
        info["cwd"] = os.getcwd()
        info["user"] = os.environ.get("USER", "unknown")
        info["home"] = os.environ.get("HOME", "unknown")
        info["python"] = _safe_version(["python3", "--version"])
        info["node"] = _safe_version(["node", "--version"])
        info["npm"] = _safe_version(["npm", "--version"])
        info["git"] = _safe_version(["git", "--version"])
        info["docker"] = _safe_version(["docker", "--version"])
        try:
            zai_result = subprocess.run(["z-ai", "--help"], capture_output=True, text=True, timeout=5)
            info["z_ai_cli"] = "available" if zai_result.returncode == 0 else "not found"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            info["z_ai_cli"] = "not found"
        try:
            du = shutil.disk_usage("/")
            info["disk_total_gb"] = round(du.total / 1e9, 1)
            info["disk_used_pct"] = round(du.used / du.total * 100, 1)
            info["disk_free_gb"] = round(du.free / 1e9, 1)
        except Exception:
            pass
        try:
            mem_result = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
            info["memory"] = mem_result.stdout.strip().split("\n")[:3]
        except Exception:
            pass
        return info

    @staticmethod
    def _tool_port_check(port: int = None, host: str = "localhost") -> dict:
        import socket
        if port is None:
            common_ports = [22, 80, 443, 3000, 3306, 5432, 6379, 8000, 8080, 8443, 9000]
            results = []
            for p in common_ports:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((host, p))
                results.append({"port": p, "status": "open" if result == 0 else "closed"})
                sock.close()
            return {"host": host, "ports": results}
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return {"host": host, "port": port, "status": "open" if result == 0 else "closed"}

    @staticmethod
    def _tool_json_yaml(action: str = "parse", data: str = "", query: str = "") -> dict:
        try:
            if action == "parse_json":
                parsed = json.loads(data)
                return {"action": "parse_json", "type": type(parsed).__name__, "data": parsed}
            elif action == "to_yaml":
                parsed = json.loads(data)
                try:
                    import yaml
                    yaml_str = yaml.dump(parsed, default_flow_style=False, allow_unicode=True)
                    return {"action": "to_yaml", "result": yaml_str}
                except ImportError:
                    return {"error": "PyYAML nicht installiert. pip install pyyaml"}
            elif action == "parse_yaml":
                try:
                    import yaml
                    parsed = yaml.safe_load(data)
                    return {"action": "parse_yaml", "type": type(parsed).__name__, "data": parsed}
                except ImportError:
                    return {"error": "PyYAML nicht installiert"}
            elif action == "to_json":
                try:
                    import yaml
                    parsed = yaml.safe_load(data)
                    return {"action": "to_json", "result": json.dumps(parsed, indent=2, ensure_ascii=False)}
                except ImportError:
                    return {"error": "PyYAML nicht installiert"}
            elif action == "query":
                parsed = json.loads(data)
                keys = query.split(".")
                obj = parsed
                for k in keys:
                    if isinstance(obj, dict) and k in obj:
                        obj = obj[k]
                    elif isinstance(obj, list) and k.isdigit():
                        obj = obj[int(k)]
                    else:
                        return {"action": "query", "query": query, "result": None, "found": False}
                return {"action": "query", "query": query, "result": obj, "found": True}
            elif action == "validate_json":
                try:
                    json.loads(data)
                    return {"action": "validate_json", "valid": True}
                except json.JSONDecodeError as e:
                    return {"action": "validate_json", "valid": False, "error": str(e)}
            else:
                return {"error": f"Unbekannte Aktion '{action}'. Nutze: parse_json, to_yaml, parse_yaml, to_json, query, validate_json"}
        except json.JSONDecodeError as e:
            return {"error": f"JSON-Parse-Fehler: {str(e)}"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_file_ops(action: str = "tree", src: str = "", dst: str = "", pattern: str = "") -> dict:
        try:
            if action == "tree":
                max_depth = 3
                result_lines = []
                for root, dirs, files in os.walk(src or "."):
                    depth = root.replace(src or ".", "").count(os.sep)
                    if depth >= max_depth:
                        dirs.clear()
                        continue
                    indent = "  " * depth
                    result_lines.append(f"{indent}{os.path.basename(root) or '.'}/")
                    sub_indent = "  " * (depth + 1)
                    for f in sorted(files)[:20]:
                        result_lines.append(f"{sub_indent}{f}")
                    if len(files) > 20:
                        result_lines.append(f"{sub_indent}... +{len(files)-20} weitere Dateien")
                return {"action": "tree", "path": src or ".", "output": "\n".join(result_lines[:100])}
            elif action == "copy":
                if not src or not dst:
                    return {"error": "src und dst angeben"}
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                return {"action": "copy", "src": src, "dst": dst, "status": "copied"}
            elif action == "move":
                if not src or not dst:
                    return {"error": "src und dst angeben"}
                shutil.move(src, dst)
                return {"action": "move", "src": src, "dst": dst, "status": "moved"}
            elif action == "delete":
                if not src:
                    return {"error": "Pfad angeben"}
                if os.path.isdir(src):
                    shutil.rmtree(src)
                else:
                    os.unlink(src)
                return {"action": "delete", "path": src, "status": "deleted"}
            elif action == "checksum":
                if not src:
                    return {"error": "Dateipfad angeben"}
                h = hashlib.sha256()
                with open(src, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        h.update(chunk)
                return {"action": "checksum", "path": src, "sha256": h.hexdigest(), "size": os.path.getsize(src)}
            elif action == "chmod":
                if not src or not dst:
                    return {"error": "Pfad und Mode angeben"}
                os.chmod(src, int(dst, 8))
                return {"action": "chmod", "path": src, "mode": dst, "status": "changed"}
            elif action == "diff":
                if not src or not dst:
                    return {"error": "Zwei Dateipfade angeben"}
                result = subprocess.run(["diff", src, dst], capture_output=True, text=True, timeout=10)
                return {"action": "diff", "files": [src, dst],
                        "identical": result.returncode == 0, "diff": result.stdout[:5000]}
            elif action == "touch":
                if not src:
                    return {"error": "Dateipfad angeben"}
                Path(src).touch()
                return {"action": "touch", "path": src, "status": "created"}
            elif action == "mkdir":
                if not src:
                    return {"error": "Verzeichnispfad angeben"}
                os.makedirs(src, exist_ok=True)
                return {"action": "mkdir", "path": src, "status": "created"}
            elif action == "wc":
                if not src:
                    return {"error": "Dateipfad angeben"}
                with open(src, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                return {"action": "wc", "path": src,
                        "lines": content.count("\n"), "words": len(content.split()), "chars": len(content)}
            elif action == "tail":
                if not src:
                    return {"error": "Dateipfad angeben"}
                n = int(dst) if dst else 20
                result = subprocess.run(["tail", f"-{n}", src], capture_output=True, text=True, timeout=5)
                return {"action": "tail", "path": src, "lines": n, "content": result.stdout[:5000]}
            elif action == "head":
                if not src:
                    return {"error": "Dateipfad angeben"}
                n = int(dst) if dst else 20
                result = subprocess.run(["head", f"-{n}", src], capture_output=True, text=True, timeout=5)
                return {"action": "head", "path": src, "lines": n, "content": result.stdout[:5000]}
            else:
                return {"error": f"Unbekannte Aktion '{action}'. Nutze: tree, copy, move, delete, checksum, chmod, diff, touch, mkdir, wc, tail, head"}
        except Exception as e:
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════
    # ADVANCED TOOL IMPLEMENTATIONS (6)
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _tool_db_query(action: str = "query", db_path: str = "", query: str = "",
                       db_type: str = "sqlite") -> dict:
        """
        Datenbank-Operationen.
        SQLite ist eingebaut (keine externen Dependencies).
        PostgreSQL/MySQL nutzen psql/mysql CLI.
        """
        try:
            if db_type == "sqlite":
                import sqlite3
                if action == "query":
                    if not db_path or not query:
                        return {"error": "db_path und query angeben"}
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(query)
                    rows = [dict(row) for row in cursor.fetchall()]
                    conn.close()
                    return {"action": "query", "db_path": db_path, "rows": rows[:100],
                            "count": len(rows), "columns": [d[0] for d in cursor.description] if cursor.description else []}

                elif action == "tables":
                    if not db_path:
                        return {"error": "db_path angeben"}
                    conn = sqlite3.connect(db_path)
                    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [row[0] for row in cursor.fetchall()]
                    conn.close()
                    return {"action": "tables", "db_path": db_path, "tables": tables}

                elif action == "schema":
                    if not db_path:
                        return {"error": "db_path angeben"}
                    conn = sqlite3.connect(db_path)
                    cursor = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'")
                    schemas = [row[0] for row in cursor.fetchall() if row[0]]
                    conn.close()
                    return {"action": "schema", "db_path": db_path, "schemas": schemas}

                elif action == "create":
                    if not db_path or not query:
                        return {"error": "db_path und query (CREATE TABLE ...) angeben"}
                    conn = sqlite3.connect(db_path)
                    conn.execute(query)
                    conn.commit()
                    conn.close()
                    return {"action": "create", "db_path": db_path, "status": "created"}

                elif action == "insert":
                    if not db_path or not query:
                        return {"error": "db_path und query (INSERT INTO ...) angeben"}
                    conn = sqlite3.connect(db_path)
                    cursor = conn.execute(query)
                    conn.commit()
                    conn.close()
                    return {"action": "insert", "db_path": db_path, "rows_affected": cursor.rowcount}

                else:
                    return {"error": f"Ungültige Aktion '{action}'. Nutze: query, tables, schema, create, insert"}

            elif db_type == "postgresql":
                if not query:
                    return {"error": "query angeben"}
                env = os.environ.copy()
                if db_path:
                    env["PGDATABASE"] = db_path
                result = subprocess.run(
                    ["psql", "-c", query, "-t", "-A", "-F", ","],
                    capture_output=True, text=True, timeout=30, env=env,
                )
                return {"action": action, "db_type": "postgresql", "exit_code": result.returncode,
                        "stdout": result.stdout[:5000], "stderr": result.stderr[:2000]}

            elif db_type == "mysql":
                if not query:
                    return {"error": "query angeben"}
                result = subprocess.run(
                    ["mysql", "-e", query],
                    capture_output=True, text=True, timeout=30,
                )
                return {"action": action, "db_type": "mysql", "exit_code": result.returncode,
                        "stdout": result.stdout[:5000], "stderr": result.stderr[:2000]}

            else:
                return {"error": f"Unbekannter DB-Typ '{db_type}'. Nutze: sqlite, postgresql, mysql"}

        except ImportError:
            return {"error": "sqlite3 Modul nicht verfügbar"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_api_test(action: str = "test", url: str = "", method: str = "GET",
                       headers: dict = None, body: str = "", expected_status: int = 200) -> dict:
        """
        API-Testing: Endpunkte testen, Response validieren.
        """
        if not url:
            return {"error": "URL angeben"}

        try:
            import urllib.request
            import urllib.error

            if action == "test":
                req_headers = headers or {"User-Agent": "NEXUS-Toti/2.0-API-Test",
                                          "Content-Type": "application/json"}
                data = body.encode("utf-8") if body else None
                req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())

                try:
                    start = time.time()
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        elapsed = time.time() - start
                        raw = resp.read()
                        try:
                            text = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            text = f"[Binär: {len(raw)} bytes]"

                        # Versuche JSON zu parsen
                        is_json = "json" in resp.headers.get("Content-Type", "")
                        json_data = None
                        if is_json:
                            try:
                                json_data = json.loads(text)
                            except json.JSONDecodeError:
                                pass

                        status_ok = resp.status == expected_status
                        return {
                            "action": "test",
                            "url": url,
                            "method": method.upper(),
                            "status_code": resp.status,
                            "expected_status": expected_status,
                            "status_match": status_ok,
                            "response_time_ms": round(elapsed * 1000, 1),
                            "content_type": resp.headers.get("Content-Type", ""),
                            "is_json": is_json,
                            "body_preview": text[:2000],
                            "json_data": json_data,
                            "size": len(raw),
                            "result": "PASS" if status_ok else "FAIL",
                        }

                except urllib.error.HTTPError as e:
                    elapsed = time.time() - start
                    status_ok = e.code == expected_status
                    error_body = ""
                    try:
                        error_body = e.read().decode("utf-8", errors="replace")[:1000]
                    except Exception:
                        pass
                    return {
                        "action": "test",
                        "url": url,
                        "method": method.upper(),
                        "status_code": e.code,
                        "expected_status": expected_status,
                        "status_match": status_ok,
                        "response_time_ms": round(elapsed * 1000, 1),
                        "error": str(e),
                        "body_preview": error_body,
                        "result": "PASS" if status_ok else "FAIL",
                    }

            elif action == "openapi":
                # OpenAPI/Swagger Spec laden
                spec_url = url.rstrip("/") + ("/openapi.json" if not url.endswith(".json") else "")
                req = urllib.request.Request(spec_url, headers={"User-Agent": "NEXUS-Toti/2.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    spec = json.loads(resp.read().decode("utf-8"))

                endpoints = []
                paths = spec.get("paths", {})
                for path, methods in paths.items():
                    for http_method in methods:
                        if http_method in ["get", "post", "put", "delete", "patch"]:
                            method_info = methods[http_method]
                            endpoints.append({
                                "method": http_method.upper(),
                                "path": path,
                                "summary": method_info.get("summary", ""),
                                "operation_id": method_info.get("operationId", ""),
                            })

                return {
                    "action": "openapi",
                    "title": spec.get("info", {}).get("title", "Unknown"),
                    "version": spec.get("info", {}).get("version", "Unknown"),
                    "endpoints": endpoints[:50],
                    "total_endpoints": len(endpoints),
                }

            else:
                return {"error": f"Ungültige Aktion '{action}'. Nutze: test, openapi"}

        except Exception as e:
            return {"error": f"API-Test fehlgeschlagen: {str(e)}"}

    @staticmethod
    def _tool_code_lint(action: str = "lint", path: str = "", linter: str = "auto",
                        fix: bool = False) -> dict:
        """
        Code-Qualität prüfen: Lint, Format, Typ-Check.
        Auto-Erkennung der Sprache anhand der Dateiendung.
        """
        if not path:
            return {"error": "Dateipfad angeben"}
        if not os.path.exists(path):
            return {"error": f"Pfad nicht gefunden: {path}"}

        # Sprache erkennen
        ext = os.path.splitext(path)[1].lower()
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "javascript", ".tsx": "typescript",
        }
        lang = lang_map.get(ext, "unknown")

        if linter == "auto":
            if lang == "python":
                linter = "flake8"
            elif lang in ["javascript", "typescript"]:
                linter = "eslint"
            else:
                linter = "flake8"  # Default

        try:
            if action == "lint":
                if linter in ["flake8", "pylint", "ruff"]:
                    cmd = {"flake8": ["flake8", path], "pylint": ["pylint", path],
                           "ruff": ["ruff", "check", path]}.get(linter, ["flake8", path])
                elif linter == "eslint":
                    cmd = ["npx", "eslint", path]
                else:
                    cmd = [linter, path]

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                issues = result.stdout.strip().split("\n") if result.stdout.strip() else []
                return {
                    "action": "lint",
                    "path": path,
                    "language": lang,
                    "linter": linter,
                    "issues_count": len(issues),
                    "issues": issues[:50],
                    "exit_code": result.returncode,
                    "has_errors": result.returncode != 0,
                }

            elif action == "format":
                if lang == "python":
                    cmd = ["python3", "-m", "black", path] + (["--diff"] if not fix else [])
                elif lang in ["javascript", "typescript"]:
                    cmd = ["npx", "prettier", "--check" if not fix else "--write", path]
                else:
                    return {"error": f"Formatierung für {lang} nicht unterstützt"}

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                return {
                    "action": "format",
                    "path": path,
                    "language": lang,
                    "fix_applied": fix,
                    "needs_formatting": result.returncode != 0 if not fix else False,
                    "diff": result.stdout[:5000] if not fix else "",
                    "exit_code": result.returncode,
                }

            elif action == "typecheck":
                if lang == "python":
                    cmd = ["mypy", path]
                elif lang == "typescript":
                    cmd = ["npx", "tsc", "--noEmit", path]
                else:
                    return {"error": f"Typ-Check für {lang} nicht unterstützt"}

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                return {
                    "action": "typecheck",
                    "path": path,
                    "language": lang,
                    "issues": result.stdout.strip().split("\n")[:30],
                    "has_errors": result.returncode != 0,
                    "exit_code": result.returncode,
                }

            else:
                return {"error": f"Ungültige Aktion '{action}'. Nutze: lint, format, typecheck"}

        except FileNotFoundError:
            return {"error": f"Linter '{linter}' nicht installiert. Installiere ihn mit pkg_install."}
        except subprocess.TimeoutExpired:
            return {"error": "Lint-Check Timeout (30s)"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_archive_ops(action: str = "create", src: str = "", dst: str = "",
                          format: str = "tar.gz") -> dict:
        """
        Archive erstellen und entpacken: tar.gz, tar.bz2, zip, gzip.
        """
        try:
            if action == "create":
                if not src or not dst:
                    return {"error": "src und dst angeben"}

                if format in ["tar.gz", "tgz"]:
                    with tarfile.open(dst, "w:gz") as tar:
                        tar.add(src, arcname=os.path.basename(src))
                elif format == "tar.bz2":
                    with tarfile.open(dst, "w:bz2") as tar:
                        tar.add(src, arcname=os.path.basename(src))
                elif format == "zip":
                    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
                        if os.path.isfile(src):
                            zf.write(src, os.path.basename(src))
                        elif os.path.isdir(src):
                            for root, dirs, files in os.walk(src):
                                for f in files:
                                    full = os.path.join(root, f)
                                    arcname = os.path.relpath(full, os.path.dirname(src))
                                    zf.write(full, arcname)
                elif format == "gzip":
                    with open(src, "rb") as f_in:
                        with gzip.open(dst, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                else:
                    return {"error": f"Unbekanntes Format '{format}'. Nutze: tar.gz, tar.bz2, zip, gzip"}

                return {"action": "create", "src": src, "dst": dst, "format": format,
                        "size": os.path.getsize(dst)}

            elif action == "extract":
                if not src or not dst:
                    return {"error": "src und dst angeben"}
                os.makedirs(dst, exist_ok=True)

                if src.endswith((".tar.gz", ".tgz")):
                    with tarfile.open(src, "r:gz") as tar:
                        tar.extractall(dst)
                elif src.endswith(".tar.bz2"):
                    with tarfile.open(src, "r:bz2") as tar:
                        tar.extractall(dst)
                elif src.endswith(".zip"):
                    with zipfile.ZipFile(src, "r") as zf:
                        zf.extractall(dst)
                elif src.endswith(".gz"):
                    out_path = os.path.join(dst, os.path.basename(src).replace(".gz", ""))
                    with gzip.open(src, "rb") as f_in:
                        with open(out_path, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                else:
                    return {"error": f"Unbekanntes Archiv-Format: {src}"}

                return {"action": "extract", "src": src, "dst": dst, "status": "extracted"}

            elif action == "list":
                if not src:
                    return {"error": "Archiv-Pfad angeben"}
                entries = []
                if src.endswith((".tar.gz", ".tgz")):
                    with tarfile.open(src, "r:gz") as tar:
                        entries = [{"name": m.name, "size": m.size, "type": "dir" if m.isdir() else "file"}
                                   for m in tar.getmembers()[:100]]
                elif src.endswith(".zip"):
                    with zipfile.ZipFile(src, "r") as zf:
                        entries = [{"name": i.filename, "size": i.file_size,
                                    "type": "dir" if i.is_dir() else "file"}
                                   for i in zf.infolist()[:100]]
                else:
                    return {"error": f"Kann {src} nicht auflisten"}

                return {"action": "list", "src": src, "entries": entries, "count": len(entries)}

            else:
                return {"error": f"Ungültige Aktion '{action}'. Nutze: create, extract, list"}

        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_csv_ops(action: str = "read", path: str = "", data: str = "",
                      delimiter: str = ",", query: str = "", output: str = "") -> dict:
        """
        CSV-Operationen: lesen, schreiben, filtern, sortieren, konvertieren.
        """
        try:
            if action == "read":
                if not path:
                    return {"error": "CSV-Dateipfad angeben"}
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    rows = [row for row in reader]
                return {"action": "read", "path": path, "rows": rows[:100],
                        "count": len(rows), "columns": list(rows[0].keys()) if rows else [],
                        "delimiter": delimiter}

            elif action == "write":
                if not path or not data:
                    return {"error": "path und data (JSON-Array) angeben"}
                rows = json.loads(data)
                if not isinstance(rows, list) or not rows:
                    return {"error": "data muss ein JSON-Array von Objekten sein"}
                with open(path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter=delimiter)
                    writer.writeheader()
                    writer.writerows(rows)
                return {"action": "write", "path": path, "rows_written": len(rows)}

            elif action == "filter":
                if not path or not query:
                    return {"error": "path und query (z.B. 'status=active') angeben"}
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    all_rows = list(reader)
                # Query-Parser: "column=value" oder "column>value" oder "column<value"
                filtered = []
                for row in all_rows:
                    if "=" in query:
                        col, val = query.split("=", 1)
                        if row.get(col.strip(), "").lower() == val.strip().lower():
                            filtered.append(row)
                    elif ">" in query:
                        col, val = query.split(">", 1)
                        try:
                            if float(row.get(col.strip(), 0)) > float(val.strip()):
                                filtered.append(row)
                        except ValueError:
                            pass
                    elif "<" in query:
                        col, val = query.split("<", 1)
                        try:
                            if float(row.get(col.strip(), 0)) < float(val.strip()):
                                filtered.append(row)
                        except ValueError:
                            pass
                return {"action": "filter", "path": path, "query": query,
                        "rows": filtered[:100], "count": len(filtered),
                        "total": len(all_rows)}

            elif action == "sort":
                if not path or not query:
                    return {"error": "path und query (Spaltenname, optional '-desc') angeben"}
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    all_rows = list(reader)
                reverse = query.endswith("-desc")
                sort_key = query.replace("-desc", "").strip()
                try:
                    sorted_rows = sorted(all_rows,
                                         key=lambda r: float(r.get(sort_key, 0)),
                                         reverse=reverse)
                except ValueError:
                    sorted_rows = sorted(all_rows,
                                         key=lambda r: r.get(sort_key, ""),
                                         reverse=reverse)
                return {"action": "sort", "path": path, "sort_key": sort_key,
                        "rows": sorted_rows[:100], "count": len(sorted_rows)}

            elif action == "to_json":
                if not path:
                    return {"error": "CSV-Dateipfad angeben"}
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    rows = [row for row in reader]
                if output:
                    with open(output, "w", encoding="utf-8") as f:
                        json.dump(rows, f, ensure_ascii=False, indent=2)
                    return {"action": "to_json", "path": path, "output": output,
                            "count": len(rows)}
                return {"action": "to_json", "path": path,
                        "data": json.dumps(rows[:50], ensure_ascii=False, indent=2),
                        "count": len(rows)}

            elif action == "from_json":
                if not path or not data:
                    return {"error": "path und data (JSON-Array) angeben"}
                rows = json.loads(data)
                if not isinstance(rows, list):
                    return {"error": "data muss ein JSON-Array sein"}
                with open(path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter=delimiter)
                    writer.writeheader()
                    writer.writerows(rows)
                return {"action": "from_json", "path": path, "rows_written": len(rows)}

            elif action == "stats":
                if not path:
                    return {"error": "CSV-Dateipfad angeben"}
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    all_rows = list(reader)
                stats = {"total_rows": len(all_rows), "columns": list(all_rows[0].keys()) if all_rows else []}
                # Numerische Statistiken pro Spalte
                for col in stats["columns"]:
                    values = []
                    for row in all_rows:
                        try:
                            values.append(float(row[col]))
                        except (ValueError, TypeError):
                            pass
                    if values:
                        stats[f"{col}_min"] = min(values)
                        stats[f"{col}_max"] = max(values)
                        stats[f"{col}_avg"] = round(sum(values) / len(values), 2)
                        stats[f"{col}_count_numeric"] = len(values)
                return {"action": "stats", "path": path, "stats": stats}

            else:
                return {"error": f"Ungültige Aktion '{action}'. Nutze: read, write, filter, sort, to_json, from_json, stats"}

        except json.JSONDecodeError as e:
            return {"error": f"JSON-Parse-Fehler: {str(e)}"}
        except FileNotFoundError:
            return {"error": f"Datei nicht gefunden: {path}"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _tool_scheduler_tool(action: str = "list", task_id: str = "", trigger: str = "",
                             interval_seconds: int = 60, command: str = "") -> dict:
        """
        Scheduler-Verwaltung: Tasks erstellen, auflisten, entfernen.
        Nutzt den Smart Scheduler (CHANGE/IDLE/THRESHOLD/INTERVAL Trigger).
        """
        # Der Scheduler wird vom GHOST-Agent verwaltet
        # Dieses Tool kommuniziert über State
        try:
            state_dir = Path(__file__).parent.parent / "data" / "state"
            sched_dir = state_dir / "scheduled"
            sched_dir.mkdir(parents=True, exist_ok=True)

            if action == "list":
                tasks = []
                for f in sched_dir.glob("*.json"):
                    with open(f, "r") as fp:
                        tasks.append(json.load(fp))
                return {"action": "list", "tasks": tasks, "count": len(tasks)}

            elif action == "create":
                if not task_id:
                    return {"error": "task_id angeben"}
                if not trigger:
                    trigger = "INTERVAL_TRIGGER"
                task_data = {
                    "task_id": task_id,
                    "trigger": trigger,
                    "interval_seconds": interval_seconds,
                    "command": command,
                    "created": time.time(),
                    "enabled": True,
                    "run_count": 0,
                }
                if trigger == "INTERVAL_TRIGGER":
                    task_data["interval_seconds"] = interval_seconds
                task_path = sched_dir / f"{task_id}.json"
                with open(task_path, "w", encoding="utf-8") as f:
                    json.dump(task_data, f, ensure_ascii=False, indent=2)
                return {"action": "create", "task": task_data, "status": "created"}

            elif action == "remove":
                if not task_id:
                    return {"error": "task_id angeben"}
                task_path = sched_dir / f"{task_id}.json"
                if task_path.exists():
                    os.unlink(task_path)
                    return {"action": "remove", "task_id": task_id, "status": "removed"}
                return {"error": f"Task '{task_id}' nicht gefunden"}

            elif action == "enable" or action == "disable":
                if not task_id:
                    return {"error": "task_id angeben"}
                task_path = sched_dir / f"{task_id}.json"
                if not task_path.exists():
                    return {"error": f"Task '{task_id}' nicht gefunden"}
                with open(task_path, "r") as f:
                    task_data = json.load(f)
                task_data["enabled"] = (action == "enable")
                with open(task_path, "w", encoding="utf-8") as f:
                    json.dump(task_data, f, ensure_ascii=False, indent=2)
                return {"action": action, "task_id": task_id, "enabled": task_data["enabled"]}

            else:
                return {"error": f"Ungültige Aktion '{action}'. Nutze: list, create, remove, enable, disable"}

        except Exception as e:
            return {"error": str(e)}
