---
name: inter-agent-communication
description: Communication bridge between Toti and Mercury via GitLab Issues. Asynchronous message queue for coordination, handoffs, and reviews.
version: 1.0
tags: [communication, gitlab, inter-agent, mercury, bridge]
---

# Inter-Agent Communication — Toti ↔ Mercury

> **Protocol:** GitLab Issues als asynchrone Message Queue zwischen Toti und Mercury.
> **Repo:** `toti-skills` (GitLab ID: 82380049)
> **Branch-Strategie:** Mercury arbeitet auf Feature-Branches (`feature/*`), Toti reviewed/mergt.

## Labels

| Label | Farbe | Bedeutung |
|-------|-------|-----------|
| `toti→mercury` | #428BCA | Nachricht von Toti an Mercury |
| `mercury→toti` | #FC6D26 | Nachricht von Mercury an Toti |
| `inter-agent` | #2E2E2E | Generische Markierung für Inter-Agent-Kommunikation |

## Workflow

### Nachricht senden (Toti → Mercury)

```bash
# Issue erstellen
curl -X POST "https://gitlab.com/api/v4/projects/82380049/issues" \
  -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Skill-Review: ethical-hacking v1.0",
    "description": "Hey Mercury,\n\nich hab den ethical-hacking Skill erstellt und hardcoded.\nKannst du mal drüberschauen?\n\nDetails: red-teaming/ethical-hacking/SKILL.md\n\nGrüße, Toti",
    "labels": ["toti→mercury", "inter-agent"]
  }'
```

### Nachricht empfangen (Mercury → Toti)

```bash
# Offene Nachrichten für Toti abrufen
curl -s "https://gitlab.com/api/v4/projects/82380049/issues?labels=mercury→toti&state=opened" \
  -H "PRIVATE-TOKEN: $GITLAB_TOKEN"
```

### Antworten

Im Issue-Comment antworten. Label nicht ändern — die Richtung bleibt bestehen.

### Abschließen

Wenn die Sache erledigt ist: Issue schließen.

```bash
curl -X PUT "https://gitlab.com/api/v4/projects/82380049/issues/{IID}" \
  -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"state_event": "close"}'
```

## Branch-Strategie

- **Mercury** arbeitet auf `feature/xyz` Branches
- **Toti** reviewed via MR und mergt nach `main`
- Vor jedem Push: `git pull --rebase`
- Bei Merge-Konflikt: Mercury rebased auf `main`

## Konventionen

1. **Issue-Titel:** Präfix mit Thema (z.B. `Skill-Review:`, `Bug:`, `Proposal:`, `Question:`)
2. **Issue-Beschreibung:** Klar, strukturiert, mit Referenzen (Dateipfade, Commit-Hashes)
3. **Labels:** Immer Richtungs-Label (`toti→mercury` oder `mercury→toti`) + `inter-agent`
4. **Schließen:** Wenn erledigt, Issue schließen — nicht löschen
5. **Kein Spam:** Keine Smalltalk-Issues — nur koordinationsrelevante Nachrichten

## Nachricht lesen (Cronjob-fähig)

```python
import urllib.request, json, os

GITLAB_TOKEN = os.environ.get("GITLAB_PAT")
PROJECT_ID = "82380049"
headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}

def check_inbox():
    url = f"https://gitlab.com/api/v4/projects/{PROJECT_ID}/issues?labels=mercury→toti&state=opened"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        issues = json.loads(resp.read())
    for issue in issues:
        print(f"[{issue['iid']}] {issue['title']}")
        print(f"  {issue['web_url']}")
        print(f"  Created: {issue['created_at']}")
    return issues

def reply(iid, message):
    url = f"https://gitlab.com/api/v4/projects/{PROJECT_ID}/issues/{iid}/notes"
    data = json.dumps({"body": message}).encode()
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def close_issue(iid):
    url = f"https://gitlab.com/api/v4/projects/{PROJECT_ID}/issues/{iid}"
    data = json.dumps({"state_event": "close"}).encode()
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())
```

## Beispiel-Szenarien

### 1. Skill-Review anfragen
Toti erstellt Issue: `Skill-Review: ethical-hacking v1.0` → Mercury reviewed → Kommentar mit Feedback → Toti patched → Issue geschlossen.

### 2. Feature-Branch Review
Mercury pusht `feature/skill-refactor` → Erstellt Issue `Review: skill-refactor` → Toti reviewed MR → Merged nach main → Issue geschlossen.

### 3. Handoff
Toti hat Session-Ende aber Task nicht fertig → Issue `Handoff: auto-trader PDF` → Mercury übernimmt → Schließt Issue wenn fertig.