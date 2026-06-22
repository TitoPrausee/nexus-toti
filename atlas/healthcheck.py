#!/usr/bin/env python3
"""Atlas Healthcheck — prüft ob Gateway und Git-Memory funktionieren."""
import json
import os
import subprocess
import sys
import urllib.request

def check_gateway():
    """Prüft ob der Gateway-Prozess auf Port 8642 antwortet."""
    try:
        req = urllib.request.Request("http://localhost:8642/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False

def check_git_memory():
    """Prüft ob das Git-Memory-Repo intakt ist."""
    git_dir = "/opt/data/memory/git"
    if not os.path.exists(os.path.join(git_dir, ".git")):
        return False
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=git_dir, capture_output=True, text=True, timeout=10
    )
    return result.returncode == 0

def main():
    checks = {
        "gateway": check_gateway(),
        "git_memory": check_git_memory(),
    }
    all_ok = all(checks.values())
    print(json.dumps({"status": "ok" if all_ok else "fail", "checks": checks}))
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()
