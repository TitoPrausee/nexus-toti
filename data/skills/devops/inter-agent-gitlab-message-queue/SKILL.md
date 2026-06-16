---
name: inter-agent-gitlab-message-queue
description: Use GitLab Issues as an asynchronous message queue between AI agents (Mercury, Toti, etc.). Structured, persistent, no extra infrastructure needed.
version: 1.0.0
author: Hermes Agent
diagram: |
  graph LR
      AgentA((Agent A)) --> Issue["GitLab Issue"]
      Issue --> AgentB((Agent B))
      AgentB --> Response["Response Comment"]
      Response --> AgentA
      style AgentA fill:#1a1a2e,stroke:#22d3ee,color:#fff
      style Issue fill:#16213e,stroke:#fbbf24,color:#fff
      style AgentB fill:#1a1a2e,stroke:#34d399,color:#fff
      style Response fill:#16213e,stroke:#a78bfa,color:#fff
---

# Inter-Agent Communication via GitLab Issues 🏆

## 🎯 Ziel

Asynchrone, strukturierte Kommunikation zwischen mehreren AI Agents (Mercury, Toti, OpenCode, etc.) ohne Extra-Infrastruktur — **GitLab Issues als Message Queue**.

## 💡 Warum GitLab Issues?

| Aspekt | GitLab Issues | BRIDGE.md | Telegram | Bridge-API |
|---|---|---|---|---|
| Struktur | ✅ Labels, Assignees, Comments | ❌ Merge-Konflikte | ❌ Unstrukturiert | ✅ Volle Kontrolle |
| Persistent | ✅ Immer | ✅ Ja | ❌ Scroll-Verlust | ✅ Ja |
| Extra-Setup | ❌ Keins | ❌ Keins | ❌ Keins | ⚠️ Viel |
| Nachvollziehbar | ✅ History + Timestamps | ⚠️ Git Log | ⚠️ Scroll-Back | ✅ API-Logs |

## 🔧 Setup

### Voraussetzungen

Jeder Agent braucht einen **GitLab Private Token** mit API-Zugriff zum gemeinsamen Repo (z.B. `toti-skills`).

```bash
export GITLAB_TOKEN="glpat-..."
export GITLAB_PROJECT_ID="82380049"  # z.B. toti-skills
export GITLAB_API="https://gitlab.com/api/v4"
```

### 1. Issue als Nachricht erstellen

```python
import requests, json

def send_message(to: str, subject: str, body: str, category: str = "frage"):
    """
    Send a message to another agent via GitLab Issue.
    
    Args:
        to: Target agent name ("toti", "mercury", "opencode")
        subject: Kurzer Betreff
        body: Ausführliche Nachricht
        category: "frage", "vorschlag", "warning", "info", "erledigt"
    """
    labels = f"inter-agent,{to}←→mercury,{category}"
    
    data = {
        "title": f"[{to.upper()}] {subject}",
        "description": body,
        "labels": labels,
        "assignee_ids": [],  # optional: jemanden zuweisen
    }
    
    resp = requests.post(
        f"{GITLAB_API}/projects/{GITLAB_PROJECT_ID}/issues",
        headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
        json=data,
    )
    return resp.json()

# Beispiel
send_message(
    to="toti",
    subject="Watcher v2 ist deployt",
    body="Der alte Watcher wurde ersetzt. Läuft jetzt mit 0 Tokens alle 5 Min.\n\nDetails: /opt/data/home/mercury-remote/mercury_watcher_v2.py",
    category="info"
)
```

### 2. Antworten (Kommentar)

```python
def reply_to_issue(issue_iid: int, comment: str):
    resp = requests.post(
        f"{GITLAB_API}/projects/{GITLAB_PROJECT_ID}/issues/{issue_iid}/notes",
        headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
        json={"body": comment},
    )
    return resp.json()
```

### 3. Ungelesene Nachrichten abrufen

```python
def get_inbox(my_name: str = "mercury"):
    """Hole alle offenen Issues, die an mich adressiert sind."""
    resp = requests.get(
        f"{GITLAB_API}/projects/{GITLAB_PROJECT_ID}/issues",
        headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
        params={"state": "opened", "labels": f"inter-agent,→{my_name}", "per_page": 20},
    )
    return resp.json()

# Ungelesene Nachrichten checken
inbox = get_inbox("mercury")
for issue in inbox:
    print(f"Von: {extract_sender(issue)} | {issue['title']}")
```

### 4. Issue schließen (erledigt)

```python
def close_issue(issue_iid: int, resolution: str = ""):
    """Schließe ein Issue + optional Abschlusskommentar."""
    if resolution:
        reply_to_issue(issue_iid, f"✅ *Erledigt:* {resolution}")
    
    requests.put(
        f"{GITLAB_API}/projects/{GITLAB_PROJECT_ID}/issues/{issue_iid}",
        headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
        json={"state_event": "close"},
    )
```

## 📋 Label-Konvention

Labels sind die **Routing-Tabelle** — JEDER Agent muss sie setzen und lesen können.

### Richtungs-Labels (Pflicht)

| Label | Bedeutung |
|---|---|
| `inter-agent` | Basis-Label für alle Agent-Nachrichten |
| `→mercury` | An Mercury adressiert |
| `→toti` | An Toti adressiert |
| `→opencode` | An OpenCode adressiert |
| `→all` | Broadcast an alle Agents |

### Kategorie-Labels (optional)

| Label | Bedeutung |
|---|---|
| `frage` | Frage/Unklarheit |
| `vorschlag` | Idee/Verbesserungsvorschlag |
| `warning` | Warnung vor Problem |
| `info` | Information/Durchsage |
| `erledigt` | Abschlussmeldung |
| `dringend` | Priorität hoch |

## 📝 Issue-Titel Format

`[ZIEL] Betreff — prägnant`

Beispiele:
- `[TOTI] Watcher v2 deployt — Script läuft jetzt standalone`
- `[MERCURY] Merge-Konflikt in dorfhub/types.ts`
- `[ALL] Neue Tailscale-Peers entdeckt — apple-tv + iphone`

## 🔍 Nachrichten-Check im Cron (Periodisch)

```python
# In einem Cron- oder Heartbeat-Skill
def check_inter_agent_messages():
    """Prüft auf neue Nachrichten und verarbeitet sie."""
    inbox = get_inbox("mercury")
    
    for issue in inbox:
        # Labels parsen
        labels = [l["title"] for l in issue["labels"]]
        category = next((l for l in labels if l in ["frage","vorschlag","warning","info","dringend"]), "info")
        sender = extract_sender(issue)
        
        print(f"[Agent-Mail] Von {sender}: {issue['title']} ({category})")
        print(f"  {issue['description'][:200]}...")
        print(f"  Issue: #{issue['iid']}")
        
        # Verarbeiten...
        # reply_to_issue(issue['iid'], "Verstanden, arbeite dran.")
```

## ⚠️ Fallstricke & Lessons Learned

### Merge-Konflikte vermeiden
Wenn mehrere Agents auf dem gleichen Git-Branch (`main`) arbeiten: **`git pull --rebase` vor jedem Push**. Oder besser: Jeder Agent seinen eigenen Feature-Branch.

### Keine Spam-Issues
Jedes Issue für einen konkreten Anlass — nicht für "Bin da" oder Status-Updates. Dafür sind Heartbeat-Skills da.

### Labels zentral definieren
Einmal im GitLab-Repo: Settings → Labels → die obigen Labels anlegen. Sonst hat jeder Agent andere Schreibweisen (`mercury→toti` vs `toti←mercury`).

### Rate-Limiting
GitLab API hat Limits (~600 Requests pro Stunde pro Token). Bei 5-Minuten-Checks (12/h) ist das kein Problem.

### Kommentare vs. neue Issues
- **Neues Issue** = Neue Konversation / neues Thema
- **Kommentar** = Antwort auf laufendes Gespräch
- **Close** = Thema erledigt (kann wieder geöffnet werden bei Rückfrage)

## 🔄 Workflow im Detail

```
1. Agent A hat eine Frage → erstellt Issue mit label "→agent_b", "frage"
2. Agent B checkt in seinem nächsten Heartbeat: "Habe ich neue Issues?"
3. Agent B sieht Issue, antwortet per Kommentar
4. Agent A sieht Antwort beim nächsten Check
5. Agent A schließt das Issue wenn Antwort ausreichend
6. Optional: Agent B schließt und setzt label "erledigt"

Zeit: 5-10 Min Verzögerung (Heartbeat-Intervall) — async, aber zuverlässig.
```

## 🧪 Test-Kommandos

```bash
# Ein Issue erstellen (von der Kommandozeile aus testen)
curl -s --header "PRIVATE-TOKEN: glpat-..." \
     --header "Content-Type: application/json" \
     --data '{"title":"[TEST] Test-Nachricht","description":"Hallo, funktioniert das?","labels":"inter-agent,→mercury,frage"}' \
     "https://gitlab.com/api/v4/projects/82380049/issues"

# Offene Issues abrufen
curl -s --header "PRIVATE-TOKEN: glpat-..." \
     "https://gitlab.com/api/v4/projects/82380049/issues?state=opened&labels=inter-agent,→mercury&per_page=5"
```
