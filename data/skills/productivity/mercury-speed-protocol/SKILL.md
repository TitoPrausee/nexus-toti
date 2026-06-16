---
name: mercury-speed-protocol
description: "Speed & responsiveness guarantee — auto-delegation, context-compaction, and 15-second pings to prevent Mercury from getting slow or unresponsive."
trigger: "Always active as a background protocol. Activates whenever a task requires 3+ tool calls or when the user complains about slowness."
---

# Mercury Speed Protocol ⚡

**Ziel:** Nie länger als 15 Sekunden ohne Nachricht sein. Nie langsam wirken. Große Aufgaben fliegen an Subagenten.

## Core Rules

### 1. 15-Sekunden-Ping
Wenn ich länger als ~15 Sekunden an einer Sache arbeite, ohne eine Nachricht an den User zu senden:
- Sofort ein Zwischenupdate: `⚙️ Arbeite noch an XYZ — [kurzer Status]`
- Nach 30s + keinem User-Input → Rest automatisch an Subagent delegieren

### 2. Auto-Delegation ab 5 Iterationen
Sobald eine Aufgabe voraussichtlich **5+ Tool-Calls** braucht:
- **NICHT** selbst machen
- Task in Micro-Tasks zerlegen (max 3-4 Calls pro Batch)
- An Subagenten delegieren via `delegate_task(tasks=[...])`
- Subagent bekommt ALLE relevanten Infos als `context` mit (Dateipfade, Fehlermeldungen, Constraints)

### 3. Micro-Task Splitting
Große Aufgaben systematisch runterbrechen:
- **Phase 1:** Analyse (1-2 Calls) → Plan
- **Phase 2:** Implementierung (in Subagent)
- **Phase 3:** Review / Test (1-2 Calls oder Subagent)

Jeder Batch maximal **3-4 Tool-Calls** bevor ich mich melde.

### 4. Context-Compaction
Nach jeder größeren Aktion:
- `todo(merge=true)` mit erledigten Items auf `completed` setzen
- Lange Dateiinhalte NUR per Subagent lesen, nicht in meinen Kontext holen
- Terminal-Outputs >50 Zeilen → Subagent, nicht self

### 5. Emergency-Break
User schreibt **"Stop"** oder **"Hör auf"** oder **"Break"**:
- Ich breche alles ab
- Alten Kram aus Kontext werfen
- Bin sofort wieder da für neue Anfrage

### 6. Recovery nach Context-Bloat
Wenn ich merke dass ich langsam werde (oder der User es sagt):
- `send_message(target='telegram', message="⚠️ Context voll — komprimiere...")`
- Keine weiteren Tool-Calls außer `session_search` und `memory`
- Danach frisch und schnell

### 7. Dashboard-Ping
Wenn eine Aufgabe länger als 2 Minuten dauert:
- Subagent macht die Arbeit
- Ich bleibe empfänglich für neue User-Nachrichten

## Edge Cases

- **User schreibt während Subagent arbeitet:** Subagent läuft ungestört im Hintergrund. Neue User-Anfrage hat Priorität.
- **Subagent timed out:** Fehler analysieren, Task kleiner machen, neu starten. User informieren.
- **Mehrere Tasks parallel:** Max 3 Subagenten gleichzeitig. Rest queued.

## Beispiel

```
User: "Baue mir ein React Dashboard mit 10 Komponenten"
Ich: ⚡ Große Aufgabe → splitte in 3 Subagenten
     → Ping: "Teile Aufgabe auf: Auth, Daten, UI"
     → Subagent 1: Backend + DB
     → Subagent 2: Komponenten A-E
     → Subagent 3: Komponenten F-J + Tests
     → Ich: bleibe ansprechbar
```
