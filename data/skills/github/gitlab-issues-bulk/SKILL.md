---
name: gitlab-issues-bulk
description: Bulk create and manage GitLab issues with research notes, auto-close after analysis, and track via project board.
version: 1.0
tags: [gitlab, issues, project-management]
---

# GitLab Bulk Issue Management

## Authentication
- PAT stored in memory: `glpat-3_MBbz8_m7IR0TOsIT7yrGM6MQpvOjEKdTpoMnFhNQ8.01`
- Project ID: `81891894` (<GITHUB_USER>e/fsu-connect-info)
- Base URL: `https://gitlab.com/api/v4`

## Bulk Issue Creation Pattern

```python
from hermes_tools import terminal
import json

PAT = "YOUR_PAT"
PROJECT_ID = "YOUR_PROJECT_ID"
BASE = "https://gitlab.com/api/v4"

def create_issue(title, description, labels):
    payload = {"title": title, "description": description, "labels": labels}
    # Write to file to avoid shell escaping issues with special chars
    with open("/tmp/issue_payload.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    result = terminal(f"curl -s -X POST '{BASE}/projects/{PROJECT_ID}/issues' -H 'PRIVATE-TOKEN: {PAT}' -H 'Content-Type: application/json' -d @/tmp/issue_payload.json")
    data = json.loads(result.get("output", "{}"))
    return data.get("iid", data.get("message", "error"))
```

## Key Patterns

1. **Write JSON to temp file** before curl — avoids shell escaping nightmares with German text, special chars
2. **Labels as comma-separated string** — GitLab accepts `"Unklarheit,Recherche"` or list
3. **Add detailed research notes** via POST to `/projects/{ID}/issues/{IID}/notes`
4. **Close issues** with PUT to `/projects/{ID}/issues/{IID}` with `{"state_event": "close"}`
5. **Add checklists** in descriptions using `- [ ]` markdown syntax (GitLab renders as clickable)
6. **Query open issues**: GET `/projects/{ID}/issues?state=opened`
7. **Project ID lookup**: GET `/projects?search=PROJECT_NAME` then extract `id`

## Workflow for Research Issues

1. Create issues with categories as labels
2. After research, add detailed analysis as note with `✅` prefix
3. Close issues that are fully resolved with actionable recommendations
4. Keep open issues that need stakeholder decisions or conversations
5. Add checklists to open issues with concrete next steps

## Pitfalls
- Python `openpyxl` may not be pre-installed — use `apt-get install python3-openpyxl`
- `sshpass` and `expect` not available — use alternative auth methods for SSH
- macOS `shutdown -h now` blocks SSH immediately — ALWAYS use `shutdown -h +5` and keep cancel window
- iSH on iPhone requires single-line commands (ash shell breaks on newlines)
- GitLab project ID differs from the numeric in URLs — always look up via API