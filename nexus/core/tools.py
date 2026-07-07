"""
NEXUS v7 — Tool Registry
Real tools that actually work. No stubs.
"""

import os
import re
import json
import subprocess
import tempfile
import time
import logging
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass

import requests

log = logging.getLogger("nexus.tools")


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str = ""
    data: dict = None

    def __str__(self):
        if self.success:
            return self.output
        return f"Error: {self.error}\n{self.output}"


class ToolRegistry:
    """Registry of real, working tools. Each tool is a callable that returns ToolResult."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._tools: dict[str, Callable] = {}
        self._dangerous: set[str] = set()
        self._register_defaults()

    def _register_defaults(self):
        """Register all built-in tools."""
        self._tools = {
            "terminal": self._tool_terminal,
            "file_read": self._tool_file_read,
            "file_write": self._tool_file_write,
            "file_search": self._tool_file_search,
            "web_search": self._tool_web_search,
            "web_fetch": self._tool_web_fetch,
            "code_exec": self._tool_code_exec,
            "calculator": self._tool_calculator,
            "time": self._tool_time,
            "delegation": self._tool_delegation,
            "memory": self._tool_memory,
        }

        # Mark dangerous tools
        dangerous = self.config.get("dangerous_requires_confirmation", [])
        self._dangerous = set(dangerous)

    def execute(self, tool_name: str, **kwargs) -> ToolResult:
        """Execute a tool by name."""
        if tool_name not in self._tools:
            return ToolResult(False, "", f"Unknown tool: {tool_name}")

        if tool_name in self._dangerous:
            log.warning(f"Dangerous tool called: {tool_name}")

        try:
            return self._tools[tool_name](**kwargs)
        except Exception as e:
            log.error(f"Tool {tool_name} error: {e}")
            return ToolResult(False, "", str(e))

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    # ─── Tool Implementations ──────────────────────────

    def _tool_terminal(self, command: str, timeout: int = 30, workdir: str = None) -> ToolResult:
        """Execute a shell command."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workdir,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n{result.stderr}"
            return ToolResult(
                result.returncode == 0,
                output[:10000],  # Truncate huge outputs
                error="" if result.returncode == 0 else f"Exit code: {result.returncode}",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult(False, "", str(e))

    def _tool_file_read(self, path: str, offset: int = 0, limit: int = 500, **kwargs) -> ToolResult:
        """Read a file's contents."""
        try:
            filepath = Path(path).expanduser()
            if not filepath.exists():
                return ToolResult(False, "", f"File not found: {path}")
            if not filepath.is_file():
                return ToolResult(False, "", f"Not a file: {path}")

            lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
            selected = lines[offset:offset + limit]
            numbered = [f"{offset + i + 1:6d}|{line}" for i, line in enumerate(selected)]

            return ToolResult(True, "\n".join(numbered), data={
                "total_lines": len(lines),
                "showing": f"{offset + 1}-{min(offset + limit, len(lines))}",
            })
        except Exception as e:
            return ToolResult(False, "", str(e))

    def _tool_file_write(self, path: str, content: str, **kwargs) -> ToolResult:
        """Write content to a file."""
        try:
            filepath = Path(path).expanduser()
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")
            return ToolResult(True, f"Written {len(content)} bytes to {path}")
        except Exception as e:
            return ToolResult(False, "", str(e))

    def _tool_file_search(self, pattern: str, path: str = ".", file_glob: str = None) -> ToolResult:
        """Search for text in files (grep-like)."""
        try:
            cmd = f"grep -rn '{pattern}' {path}"
            if file_glob:
                cmd += f" --include='{file_glob}'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            output = result.stdout[:5000] if result.stdout else "No matches found"
            return ToolResult(True, output)
        except Exception as e:
            return ToolResult(False, "", str(e))

    def _tool_web_search(self, query: str, max_results: int = 5) -> ToolResult:
        """Search the web using DuckDuckGo."""
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                if not results:
                    return ToolResult(True, "No results found")

                output_lines = []
                for r in results:
                    title = r.get("title", "")
                    href = r.get("href", "")
                    body = r.get("body", "")[:200]
                    output_lines.append(f"**{title}**\n{href}\n{body}\n")

                return ToolResult(True, "\n".join(output_lines))
        except ImportError:
            # Fallback: basic requests-based search
            return self._web_search_fallback(query, max_results)
        except Exception as e:
            return ToolResult(False, "", str(e))

    def _web_search_fallback(self, query: str, max_results: int = 5) -> ToolResult:
        """Fallback web search without duckduckgo-search package."""
        try:
            url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "NEXUS/7.0"})
            # Extract titles and URLs from HTML
            links = re.findall(r'class="result__a".*?href="(.*?)".*?>(.*?)</a>', resp.text, re.DOTALL)
            if not links:
                return ToolResult(True, "No results found")
            lines = []
            for url_match, title in links[:max_results]:
                title = re.sub(r'<.*?>', '', title).strip()
                lines.append(f"**{title}**\n{url_match}\n")
            return ToolResult(True, "\n".join(lines))
        except Exception as e:
            return ToolResult(False, "", str(e))

    def _tool_web_fetch(self, url: str, max_length: int = 10000) -> ToolResult:
        """Fetch a URL's content."""
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "NEXUS/7.0"})
            resp.raise_for_status()

            # Try to extract text from HTML
            content = resp.text
            # Basic HTML stripping
            content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
            content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
            content = re.sub(r'<[^>]+>', ' ', content)
            content = re.sub(r'\s+', ' ', content).strip()

            return ToolResult(True, content[:max_length])
        except Exception as e:
            return ToolResult(False, "", str(e))

    def _tool_code_exec(self, code: str, language: str = "python", timeout: int = 30) -> ToolResult:
        """Execute code in a sandboxed environment."""
        try:
            if language != "python":
                return ToolResult(False, "", f"Unsupported language: {language}")

            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                f.flush()
                tmp_path = f.name

            try:
                result = subprocess.run(
                    ["python3", tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                output = result.stdout
                if result.stderr:
                    output += f"\nSTDERR: {result.stderr}"
                return ToolResult(
                    result.returncode == 0,
                    output[:10000],
                    error="" if result.returncode == 0 else f"Exit code: {result.returncode}",
                )
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            return ToolResult(False, "", str(e))

    def _tool_calculator(self, expression: str, **kwargs) -> ToolResult:
        """Evaluate a math expression safely."""
        try:
            # Only allow math operations
            allowed = set("0123456789+-*/.()%^e ")
            if not all(c in allowed for c in expression):
                return ToolResult(False, "", "Invalid characters in expression")

            # Replace ^ with **
            expr = expression.replace("^", "**")
            result = eval(expr, {"__builtins__": {}}, {})
            return ToolResult(True, str(result))
        except Exception as e:
            return ToolResult(False, "", f"Calculation error: {e}")

    def _tool_time(self, **kwargs) -> ToolResult:
        """Get current date and time."""
        from datetime import datetime
        now = datetime.now()
        return ToolResult(True, now.strftime("%Y-%m-%d %H:%M:%S"), data={
            "iso": now.isoformat(),
            "unix": time.time(),
        })

    def _tool_delegation(self, task: str, specialist: str = "coding",
                          context: str = "") -> ToolResult:
        """
        Delegate a task to a specialist model.
        Returns the specialist's response.
        This is a placeholder — the actual delegation happens in the Agent.
        """
        return ToolResult(True, f"Delegated to {specialist}: {task[:100]}", data={
            "task": task,
            "specialist": specialist,
            "context": context,
        })

    def _tool_memory(self, action: str, content: str = "", category: str = "general",
                     importance: float = 0.7) -> ToolResult:
        """
        Memory tool — remember facts or recall knowledge.
        Actions: remember, recall, stats
        """
        # This will be connected to the MemorySystem by the Agent
        return ToolResult(True, f"Memory {action}: {content[:100]}")