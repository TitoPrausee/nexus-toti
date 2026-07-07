"""
NEXUS v9.3 — L3-Git Cold Memory

Git-versioned, on-demand loaded memory layer. Markdown files organized
by topic, searched by keyword match on MEMORY.md index. Never loaded
into system prompt automatically — only when recall or recall_deep
explicitly requests it.

Handles Docker waitpid bug by using Popen instead of subprocess.run.
Falls back to file-only mode if git is unavailable.
"""

import os
import time
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import yaml

log = logging.getLogger("nexus.git_memory")


class GitMemory:
    """L3-Git Cold Memory — versioned .md files, loaded on demand.

    Provides:
    - init_repo(): Initialize git repo if not exists
    - search(query, limit): Search MEMORY.md index + file contents
    - load_file(path): Load a specific memory file
    - save_file(path, content): Write/update a memory file and git commit
    - append_fact(path, content, category, importance): Add a fact to an existing file
    - create_session_summary(session_data): Write a session summary file
    - migrate_from_l3(l3_entries): One-time migration of L3 data to git memory
    - git_push/pull: Periodic sync with remote
    - maybe_sync(): Called periodically from heartbeat
    """

    def __init__(self, data_dir: str = "data/memory", config: dict = None):
        self.data_dir = Path(data_dir)
        self.repo_path = self.data_dir / "git"
        cfg = config or {}

        self.git_enabled = cfg.get("git_enabled", True)
        self.remote_url = cfg.get("git_remote", "")
        self.sync_interval = cfg.get("git_sync_interval_seconds", 3600)
        self.author_name = cfg.get("git_author_name", "Nexus")
        self.author_email = cfg.get("git_author_email", "nexus@local")

        self._last_sync = 0
        self._git_available = None  # None = not checked yet

        self._init_repo()

    # ─── Repo Initialization ────────────────────────────────

    def _init_repo(self):
        """Initialize git repo if not exists."""
        self.repo_path.mkdir(parents=True, exist_ok=True)

        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            log.info("Initializing git memory repo")
            self._git_command("init")

            # Create .gitignore
            gitignore = self.repo_path / ".gitignore"
            gitignore.write_text("*.tmp\n*.swp\n.DS_Store\nembeddings*\n")

            # Create initial MEMORY.md
            memory_md = self.repo_path / "MEMORY.md"
            if not memory_md.exists():
                memory_md.write_text(self._default_memory_md())

            # Create directory structure
            for subdir in ["projects", "infrastructure", "learnings", "decisions", "sessions"]:
                (self.repo_path / subdir).mkdir(exist_ok=True)

            self._git_command("add", ".")
            self._git_command("commit", "-m", "Initial commit: Nexus cold memory")
            log.info("Git memory repo initialized")
        else:
            log.info("Git memory repo already exists")

    def _default_memory_md(self) -> str:
        """Generate default MEMORY.md index."""
        return """# Nexus Memory Index

> This file is the index for all cold memory documents.
> Nexus reads this first when searching for context.

## Projects
- [nexus](projects/nexus.md) — Autonomer KI-Agent mit Seele

## Infrastructure
- [docker](infrastructure/docker.md) — Container-Setup, Ports
- [ollama](infrastructure/ollama.md) — LLM-Inferenz

## Learnings
- [python-bugs](learnings/python-bugs.md) — Wiederkehrende Bug-Patterns
- [architecture](learnings/architecture.md) — Architektur-Entscheidungen

## Decisions
- [memory-system](decisions/memory-system.md) — Memory-Architektur

## Sessions
<!-- Recent session summaries are added here automatically -->
"""

    # ─── Git Command Execution ─────────────────────────────

    def _git_command(self, *args, check: bool = True, timeout: int = 10) -> Optional[str]:
        """Execute a git command, handling Docker waitpid issues.

        Uses Popen instead of subprocess.run to avoid the Docker waitpid bug.
        Falls back gracefully if git is unavailable.
        """
        if not self.git_enabled:
            return None

        # Check git availability once
        if self._git_available is False:
            return None

        # Use absolute path for cwd
        repo_path = str(self.repo_path.resolve())
        cmd = ["git"] + list(args)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": self.author_name,
            "GIT_AUTHOR_EMAIL": self.author_email,
            "GIT_COMMITTER_NAME": self.author_name,
            "GIT_COMMITTER_EMAIL": self.author_email,
        }

        try:
            proc = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=repo_path
            )
            stdout, stderr = proc.communicate(timeout=timeout)

            if proc.returncode != 0:
                err_msg = stderr.decode().strip()[:200]
                if check:
                    log.warning(f"Git command failed: {' '.join(args)}: {err_msg}")
                return None

            self._git_available = True
            return stdout.decode().strip()

        except subprocess.TimeoutExpired:
            proc.kill()
            log.warning(f"Git command timed out: {' '.join(args)}")
            return None
        except FileNotFoundError:
            log.warning("Git not available, falling back to file-only mode")
            self._git_available = False
            return None
        except Exception as e:
            log.warning(f"Git command error: {e}")
            return None

    # ─── Search ─────────────────────────────────────────────

    def search(self, query: str, limit: int = 3) -> list[Tuple[str, str]]:
        """Search MEMORY.md index and file contents for keyword matches.

        Returns list of (file_path, relevant_excerpt) tuples.
        """
        if not query:
            return []

        results = []
        query_lower = query.lower()
        query_words = set(query_lower.split())

        # Step 1: Search MEMORY.md index
        memory_md = self.repo_path / "MEMORY.md"
        if not memory_md.exists():
            return []

        with open(memory_md, "r", encoding="utf-8") as f:
            index_content = f.read()

        # Parse index for matching files
        matching_files = set()
        for line in index_content.split("\n"):
            line_lower = line.lower()
            # Check if any query word appears in this line
            if any(word in line_lower for word in query_words):
                # Extract file path from markdown link: [text](path.md)
                import re
                match = re.search(r'\(([^)]+\.md)\)', line)
                if match:
                    matching_files.add(match.group(1))

        # Step 2: Load matching files and search their content
        for file_path in matching_files:
            full_path = self.repo_path / file_path
            if not full_path.exists():
                continue

            try:
                content = full_path.read_text(encoding="utf-8")
            except Exception:
                continue

            # Find relevant excerpt around matching words
            content_lower = content.lower()
            best_pos = -1
            for word in query_words:
                pos = content_lower.find(word)
                if pos != -1 and (best_pos == -1 or pos < best_pos):
                    best_pos = pos

            if best_pos == -1:
                # File matched in index but not in content — use first 200 chars
                excerpt = content[:200].strip()
            else:
                # Extract excerpt around the match
                start = max(0, best_pos - 100)
                end = min(len(content), best_pos + 200)
                excerpt = content[start:end].strip()
                if start > 0:
                    excerpt = "..." + excerpt
                if end < len(content):
                    excerpt = excerpt + "..."

            results.append((file_path, excerpt))

            if len(results) >= limit:
                break

        # Step 3: If no index matches, search all .md files directly
        if not results:
            for md_file in sorted(self.repo_path.rglob("*.md")):
                if md_file.name == "MEMORY.md":
                    continue
                rel_path = str(md_file.relative_to(self.repo_path))
                try:
                    content = md_file.read_text(encoding="utf-8")
                    content_lower = content.lower()
                    matches = sum(1 for word in query_words if word in content_lower)
                    if matches > 0:
                        # Find best excerpt
                        best_pos = -1
                        for word in query_words:
                            pos = content_lower.find(word)
                            if pos != -1 and (best_pos == -1 or pos < best_pos):
                                best_pos = pos
                        if best_pos != -1:
                            start = max(0, best_pos - 100)
                            end = min(len(content), best_pos + 200)
                            excerpt = content[start:end].strip()
                            if start > 0:
                                excerpt = "..." + excerpt
                            if end < len(content):
                                excerpt = excerpt + "..."
                            results.append((rel_path, excerpt))
                            if len(results) >= limit:
                                break
                except Exception:
                    continue

        return results

    # ─── File Operations ────────────────────────────────────

    def load_file(self, path: str) -> str:
        """Load a specific memory file."""
        full_path = self.repo_path / path
        if not full_path.exists():
            return ""
        try:
            return full_path.read_text(encoding="utf-8")
        except Exception as e:
            log.warning(f"Failed to load git memory file {path}: {e}")
            return ""

    def save_file(self, path: str, content: str, commit_message: str = None) -> bool:
        """Write/update a memory file and git commit."""
        full_path = self.repo_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            full_path.write_text(content, encoding="utf-8")
        except Exception as e:
            log.error(f"Failed to write git memory file {path}: {e}")
            return False

        if self.git_enabled:
            msg = commit_message or f"Update {path}"
            self._git_command("add", path)
            self._git_command("commit", "-m", msg)

        return True

    def append_fact(self, path: str, content: str, category: str = "general", importance: float = 0.7) -> bool:
        """Append a fact to an existing memory file, or create it if it doesn't exist."""
        full_path = self.repo_path / path

        if full_path.exists():
            # Read existing content and append
            existing = full_path.read_text(encoding="utf-8")
            # Add fact under Key Facts section
            if "## Key Facts" in existing:
                # Append after Key Facts section
                parts = existing.split("## Key Facts", 1)
                after_header = parts[1].split("\n", 1)
                if len(after_header) > 1:
                    # Find next section
                    next_section = after_header[1].find("\n## ")
                    if next_section != -1:
                        existing = (parts[0] + "## Key Facts" + after_header[0] + "\n"
                                    + f"- {content} (importance: {importance})\n"
                                    + after_header[1][:next_section] + "\n"
                                    + after_header[1][next_section:])
                    else:
                        existing = (parts[0] + "## Key Facts" + after_header[0] + "\n"
                                    + f"- {content} (importance: {importance})\n"
                                    + after_header[1])
                else:
                    existing += f"\n## Key Facts\n- {content} (importance: {importance})\n"
            else:
                existing += f"\n## Key Facts\n- {content} (importance: {importance})\n"

            # Update Last Updated date
            import re
            existing = re.sub(
                r"Last Updated.*",
                f"Last Updated: {time.strftime('%Y-%m-%d')}",
                existing
            )
            return self.save_file(path, existing, f"Add fact: {content[:50]}")
        else:
            # Create new file with template
            title = Path(path).stem.replace("-", " ").replace("_", " ").title()
            new_content = f"""# {title}

## Summary
{content}

## Key Facts
- {content} (importance: {importance})

## Last Updated
{time.strftime('%Y-%m-%d')}
"""
            return self.save_file(path, new_content, f"Create: {path}")

    # ─── Session Summaries ──────────────────────────────────

    def create_session_summary(self, session_data: dict) -> bool:
        """Create a session summary file in sessions/ directory."""
        timestamp = session_data.get("timestamp", time.time())
        date_str = time.strftime("%Y-%m-%d", time.localtime(timestamp))
        path = f"sessions/{date_str}.md"

        topics = session_data.get("topics", [])
        key_facts = session_data.get("key_facts", [])
        decisions = session_data.get("decisions", [])
        summary = session_data.get("summary", "")

        content = f"""# Session: {date_str}

## Topics
{chr(10).join(f'- {t}' for t in topics) if topics else '- (no topics)'}

## Key Facts
{chr(10).join(f'- {f}' for f in key_facts) if key_facts else '- (no key facts)'}

## Decisions
{chr(10).join(f'- {d}' for d in decisions) if decisions else '- (no decisions)'}

## Summary
{summary or '(no summary)'}

## Last Updated
{time.strftime('%Y-%m-%d')}
"""
        result = self.save_file(path, content, f"Session summary: {date_str}")

        # Update MEMORY.md index with link to this session
        if result:
            self._update_memory_index(path, f"Session {date_str}", "sessions")

        return result

    def _update_memory_index(self, path: str, description: str, category: str):
        """Add a link to a file in MEMORY.md index."""
        memory_md = self.repo_path / "MEMORY.md"
        if not memory_md.exists():
            return

        content = memory_md.read_text(encoding="utf-8")

        # Find the appropriate section
        section_header = f"## {category.title()}"
        link_line = f"- [{Path(path).stem}]({path}) — {description}"

        if section_header in content:
            # Add link after the section header
            lines = content.split("\n")
            new_lines = []
            added = False
            for line in lines:
                new_lines.append(line)
                if line.strip() == section_header and not added:
                    new_lines.append(link_line)
                    added = True
            content = "\n".join(new_lines)
        else:
            # Add new section before Sessions section
            new_section = f"\n{section_header}\n{link_line}\n"
            if "## Sessions" in content:
                content = content.replace("## Sessions", new_section + "\n## Sessions")
            else:
                content += new_section

        self.save_file("MEMORY.md", content, f"Update index: {path}")

    # ─── Migration ──────────────────────────────────────────

    def migrate_from_l3(self, l3_entries: list) -> int:
        """One-time migration of L3 data to git memory format.

        Groups entries by category and creates corresponding .md files.
        Returns number of entries migrated.
        """
        migrated = 0

        # Category mapping
        category_map = {
            "user_identity": "projects/nexus.md",
            "identity": "projects/nexus.md",
            "technical": "learnings/python-bugs.md",
            "config": "infrastructure/docker.md",
            "infrastructure": "infrastructure/docker.md",
            "decision": "decisions/memory-system.md",
            "project": "projects/nexus.md",
            "general": "decisions/general.md",
            "preference": "projects/nexus.md",
        }

        # Group entries by target file
        file_entries = {}
        for entry in l3_entries:
            content = entry.get("content", "").strip()
            if not content:
                continue

            category = entry.get("category", "general")
            importance = entry.get("importance", 0.5)
            target = category_map.get(category, "decisions/general.md")

            if target not in file_entries:
                file_entries[target] = []
            file_entries[target].append(f"- {content} (importance: {importance})")
            migrated += 1

        # Create files
        for file_path, entries in file_entries.items():
            title = Path(file_path).stem.replace("-", " ").replace("_", " ").title()
            content = f"""# {title}

## Summary
Migrated from L3 long-term memory.

## Key Facts
{chr(10).join(entries)}

## Last Updated
{time.strftime('%Y-%m-%d')}
"""
            self.save_file(file_path, content, f"Migrate L3: {file_path}")

        # Update MEMORY.md index
        for file_path in file_entries:
            title = Path(file_path).stem.replace("-", " ").replace("_", " ").title()
            category = Path(file_path).parent.name
            self._update_memory_index(file_path, title, category)

        log.info(f"Migrated {migrated} L3 entries to git memory")
        return migrated

    # ─── Git Sync ───────────────────────────────────────────

    def maybe_sync(self):
        """Called periodically from heartbeat. Push/pull if interval elapsed."""
        now = time.time()
        if now - self._last_sync < self.sync_interval:
            return

        self._last_sync = now

        if self.remote_url:
            self.git_pull()
            self.git_push()

    def git_push(self) -> bool:
        """Push to remote if configured."""
        if not self.remote_url:
            return True  # Local-only mode, no push needed

        result = self._git_command("push", "origin", "main", check=False)
        return result is not None

    def git_pull(self) -> bool:
        """Pull from remote if configured."""
        if not self.remote_url:
            return True  # Local-only mode, no pull needed

        result = self._git_command("pull", "--rebase", "origin", "main", check=False)
        return result is not None

    # ─── File Listing ───────────────────────────────────────

    def list_files(self) -> list[str]:
        """List all .md files in the repo (excluding MEMORY.md)."""
        files = []
        for md_file in sorted(self.repo_path.rglob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            rel_path = str(md_file.relative_to(self.repo_path))
            files.append(rel_path)
        return files

    # ─── Stats ──────────────────────────────────────────────

    def stats(self) -> dict:
        """Return git memory statistics."""
        files = self.list_files()
        return {
            "enabled": self.git_enabled,
            "git_available": self._git_available is not False,
            "files": len(files),
            "remote_configured": bool(self.remote_url),
            "last_sync": self._last_sync,
        }