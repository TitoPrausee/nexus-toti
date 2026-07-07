#!/usr/bin/env python3
"""
Atlas Git Memory Engine
Git-basiertes, unendliches Memory — nie komprimieren, immer versionieren.

L4: Git Archive — unendlich, versioniert, durchsuchbar
L3: Long-term Memory — git-versionierte .md Dateien
L2: Session Memory — vergangene Sessions
L1: Working Memory — aktuelle Konversation (nie komprimiert)
L0: Hot Memory — immer im Context
"""

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


class GitMemory:
    """Git-basiertes Memory — nie komprimieren, immer versionieren."""

    def __init__(self, repo_path: str = None):
        self.repo_path = repo_path or os.environ.get(
            "ATLAS_MEMORY_PATH",
            os.path.expanduser("~/.atlas/memory/git")
        )
        self._init_repo()

    def _init_repo(self):
        """Initialisiert Git-Repo falls nicht vorhanden."""
        git_dir = os.path.join(self.repo_path, ".git")
        if not os.path.exists(git_dir):
            os.makedirs(self.repo_path, exist_ok=True)
            self._git("init")
            self._git("config", "user.name", "Atlas")
            self._git("config", "user.email", "atlas@local")
            self._git("config", "core.autocrlf", "input")
            self._git("config", "pull.rebase", "true")

    def _git(self, *args, timeout: int = 30) -> subprocess.CompletedProcess:
        """Führt einen Git-Befehl aus."""
        try:
            return subprocess.run(
                ["git"] + list(args),
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args, returncode=124, stdout="", stderr="timeout"
            )
        except FileNotFoundError:
            # Fallback: Git nicht verfügbar (z.B. im Container mit waitpid-Bug)
            return subprocess.CompletedProcess(
                args, returncode=0, stdout="", stderr=""
            )

    # ─── L4: Git Archive ─────────────────────────────────────

    def save(self, path: str, content: str, message: str) -> bool:
        """Speichert eine Datei mit Git-Commit."""
        full_path = os.path.join(self.repo_path, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Prüfe ob sich Inhalt geändert hat
        if os.path.exists(full_path):
            with open(full_path) as f:
                if f.read() == content:
                    return False  # Keine Änderung

        with open(full_path, "w") as f:
            f.write(content)

        self._git("add", path)
        result = self._git("commit", "-m", message)
        return result.returncode == 0

    def load(self, path: str) -> Optional[str]:
        """Lädt eine Datei aus dem Git-Repo."""
        full_path = os.path.join(self.repo_path, path)
        if os.path.exists(full_path):
            with open(full_path) as f:
                return f.read()
        return None

    def delete(self, path: str, message: str) -> bool:
        """Löscht eine Datei aus dem Git-Repo."""
        full_path = os.path.join(self.repo_path, path)
        if not os.path.exists(full_path):
            return False
        os.remove(full_path)
        self._git("add", path)
        result = self._git("commit", "-m", message)
        return result.returncode == 0

    def search(self, keyword: str, file_pattern: str = "*.md") -> list[dict]:
        """Volltext-Suche über alle Memory-Dateien via git grep."""
        result = self._git("grep", "-n", keyword, "--", file_pattern)
        if result.returncode != 0:
            return []
        return self._parse_grep_output(result.stdout)

    def _parse_grep_output(self, output: str) -> list[dict]:
        results = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":", 2)
            if len(parts) == 3:
                results.append({
                    "file": parts[0],
                    "line": int(parts[1]),
                    "content": parts[2],
                })
        return results

    def log(self, path: Optional[str] = None, max_count: int = 20) -> list[dict]:
        """Git-Log für eine Datei oder das ganze Repo."""
        cmd = [
            "log", f"--max-count={max_count}",
            "--format=%H|%ai|%s"
        ]
        if path:
            cmd.extend(["--", path])
        result = self._git(*cmd)
        return self._parse_log_output(result.stdout)

    def _parse_log_output(self, output: str) -> list[dict]:
        entries = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                entries.append({
                    "hash": parts[0],
                    "date": parts[1],
                    "message": parts[2],
                })
        return entries

    def diff(self, path: str, hash1: str = "HEAD~1", hash2: str = "HEAD") -> str:
        """Git-Diff zwischen zwei Versionen einer Datei."""
        result = self._git("diff", hash1, hash2, "--", path)
        return result.stdout

    def rollback(self, path: str, hash: str) -> bool:
        """Setzt eine Datei auf eine frühere Version zurück."""
        result = self._git("checkout", hash, "--", path)
        if result.returncode == 0:
            self._git("commit", "-m", f"rollback: {path} to {hash[:8]}")
            return True
        return False

    def show(self, hash: str) -> str:
        """Zeigt den vollständigen Inhalt eines Commits."""
        result = self._git("show", hash, "--format=%H%n%ai%n%s%n%n%b", "--no-stat")
        return result.stdout

    def blame(self, path: str) -> list[dict]:
        """Zeigt wer welche Zeile zuletzt geändert hat."""
        result = self._git("blame", "--porcelain", path)
        return self._parse_blame_output(result.stdout)

    def _parse_blame_output(self, output: str) -> list[dict]:
        lines = []
        for line in output.strip().split("\n"):
            if not line or line.startswith("\t"):
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2:
                lines.append({"hash": parts[0], "info": parts[1]})
        return lines

    def push(self, remote: str = "origin", branch: str = "main") -> bool:
        """Push zu Remote."""
        result = self._git("push", remote, branch)
        return result.returncode == 0

    def pull(self, remote: str = "origin", branch: str = "main") -> bool:
        """Pull von Remote."""
        result = self._git("pull", "--rebase", remote, branch)
        return result.returncode == 0

    def status(self) -> dict:
        """Zeigt den Status des Repos."""
        result = self._git("status", "--porcelain")
        log_result = self._git("log", "--oneline", "--max-count=1")
        branch_result = self._git("branch", "--show-current")

        return {
            "dirty": bool(result.stdout.strip()),
            "last_commit": log_result.stdout.strip() if log_result.returncode == 0 else "none",
            "branch": branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown",
            "file_count": len(list(Path(self.repo_path).rglob("*.md"))),
        }

    # ─── L3: Long-term Memory ────────────────────────────────

    def save_fact(self, domain: str, name: str, content: str) -> bool:
        """Speichert einen Fakt in der entsprechenden Domain."""
        path = f"{domain}/{name}.md"
        return self.save(path, content, f"fact: {domain}/{name}")

    def load_fact(self, domain: str, name: str) -> Optional[str]:
        """Lädt einen Fakt aus einer Domain."""
        return self.load(f"{domain}/{name}.md")

    def list_domain(self, domain: str) -> list[str]:
        """Listet alle Dateien in einer Domain."""
        domain_path = os.path.join(self.repo_path, domain)
        if not os.path.exists(domain_path):
            return []
        return sorted([
            f for f in os.listdir(domain_path)
            if f.endswith(".md")
        ])

    # ─── L2: Session Memory ───────────────────────────────────

    def archive_session(self, session_data: dict) -> bool:
        """Archiviert eine Session als Git-commitierte Datei."""
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        path = f"sessions/{timestamp}.md"

        content = f"""# Session: {session_data.get('topic', 'Unbenannt')}

**Datum:** {session_data.get('date', timestamp)}
**Dauer:** {session_data.get('duration', 'unbekannt')}
**Topics:** {', '.join(session_data.get('topics', []))}

## Key Facts
{session_data.get('key_facts', 'Keine')}

## Decisions
{session_data.get('decisions', 'Keine')}

## Zusammenfassung
{session_data.get('summary', 'Keine')}
"""
        return self.save(path, content, f"session: {session_data.get('topic', 'unbenannt')}")

    def find_sessions(self, topic: str, max_results: int = 5) -> list[dict]:
        """Findet Sessions zu einem Topic."""
        results = self.search(topic, "sessions/*.md")
        # Deduplizieren nach Datei
        seen = set()
        unique = []
        for r in results:
            if r["file"] not in seen:
                seen.add(r["file"])
                unique.append(r)
        return unique[:max_results]

    # ─── L0: Hot Memory ───────────────────────────────────────

    def load_hot_memory(self) -> dict:
        """Lädt das Hot Memory (immer im Context)."""
        content = self.load("hot.yaml")
        if not content:
            return {}
        try:
            import yaml
            return yaml.safe_load(content) or {}
        except ImportError:
            return {}
        except yaml.YAMLError:
            return {}

    def update_hot_memory(self, key: str, value: any) -> bool:
        """Aktualisiert einen Eintrag im Hot Memory."""
        import yaml
        hot = self.load_hot_memory()
        hot[key] = value
        content = yaml.dump(hot, default_flow_style=False, allow_unicode=True)
        return self.save("hot.yaml", content, f"hot: update {key}")

    # ─── Migration ───────────────────────────────────────────

    def import_file(self, source_path: str, target_path: str,
                    source_name: str, message: str) -> bool:
        """Importiert eine Datei mit Provenance-Tag."""
        if not os.path.exists(source_path):
            return False

        with open(source_path) as f:
            content = f.read()

        # Provenance-Header hinzufügen
        provenance = f"""---
source: {source_name}
original_path: {source_path}
imported_at: {datetime.now().isoformat()}
content_hash: {hashlib.sha256(content.encode()).hexdigest()[:16]}
---

"""
        return self.save(target_path, provenance + content, message)

    def get_content_hash(self, content: str) -> str:
        """Erzeugt einen Content-Hash für Deduplizierung."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# ─── CLI ─────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Atlas Git Memory Engine")
    parser.add_argument("command", choices=[
        "save", "load", "search", "log", "diff", "status",
        "rollback", "show", "blame", "push", "pull"
    ])
    parser.add_argument("args", nargs="*", help="Kommandospezifische Argumente")
    args = parser.parse_args()

    mem = GitMemory()

    if args.command == "save":
        path, content, message = args.args[0], sys.stdin.read(), args.args[1]
        mem.save(path, content, message)
    elif args.command == "load":
        print(mem.load(args.args[0]) or "Nicht gefunden")
    elif args.command == "search":
        results = mem.search(args.args[0])
        for r in results:
            print(f"{r['file']}:{r['line']}: {r['content']}")
    elif args.command == "log":
        entries = mem.log(args.args[0] if args.args else None)
        for e in entries:
            print(f"{e['hash'][:8]} {e['date']} {e['message']}")
    elif args.command == "diff":
        print(mem.diff(*args.args))
    elif args.command == "status":
        s = mem.status()
        print(f"Branch: {s['branch']}")
        print(f"Letzter Commit: {s['last_commit']}")
        print(f"Dateien: {s['file_count']}")
        print(f"Uncommitted: {'ja' if s['dirty'] else 'nein'}")
    elif args.command == "rollback":
        mem.rollback(args.args[0], args.args[1])
    elif args.command == "show":
        print(mem.show(args.args[0]))
    elif args.command == "blame":
        lines = mem.blame(args.args[0])
        for l in lines:
            print(f"{l['hash'][:8]} {l['info']}")
    elif args.command == "push":
        mem.push()
    elif args.command == "pull":
        mem.pull()


if __name__ == "__main__":
    import sys
    main()
