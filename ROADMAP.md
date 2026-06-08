# NEXUS v7 — ROADMAP

## Status: ALPHA — Circular Chain Detection v7.6 Complete

Letztes Update: 2026-06-06 (v7.6: Circular Chain Detection im Agent-Loop)

---

## ✅ ERLEDIGT

- [x] Agent Core (`nexus/core/agent.py`) — Think-Act Loop mit Tool-Call Parsing
- [x] LLM Client (`nexus/core/llm_client.py`) — Ollama Cloud, Model-Routing, Streaming
- [x] Memory System (`nexus/core/memory.py`) — L1-L4 Layer, Auto-Compression, Persistenz
- [x] Soul Engine (`nexus/soul/__init__.py`) — Persönlichkeit, Beziehungen, Lernen
- [x] Tool Registry (`nexus/core/tools.py`) — 11 Tools (terminal, file, web, code, etc.)
- [x] Telegram Bot (`nexus/interfaces/telegram_bot.py`) — Streaming, Auth, User-Recognition
- [x] Web UI (`nexus/interfaces/web_ui.py`) — FastAPI Chat, Invite-Gate, Rate-Limiting
- [x] CLI Interface (`nexus/interfaces/cli.py`) — Testing-Modus
- [x] Contributor Bot (`nexus/contributor_bot.py`) — Discord Onboarding
- [x] Config System (`config.yaml`) — Zentral, YAML, alle Module
- [x] Agent-Loop: XML Tool-Call Parsing (`<tool>...</tool>`)
- [x] Self-Test (`nexus.py --test`)
- [x] 🔧 LLM Retry-Logik repariert — Exponential Backoff, Config-Fallback-Chain, Error-Kategorisierung
- [x] 🔧 Agent-Loop: Loop Detection (gleicher Tool-Call >3x = Break)
- [x] 🔧 Agent-Loop: Fuzzy JSON Repair für Tool-Call Parsing
- [x] 🔧 Agent-Loop: Error Recovery (LLM-Fehler → Retry statt Crash)
- [x] 🔧 Agent-Loop: Tool-Error Feedback an LLM ("versuche anderen Ansatz")
- [x] 🔧 Config-Hot-Reload (`nexus/core/config.py`) — File-Watcher + Callbacks + SIGHUP
- [x] 🔧 **v7.1**: Memory-System Verbesserung — L2 strukturierte Summaries (Topics, Key Facts, Decisions)
- [x] 🔧 **v7.1**: L3 Fuzzy-Dedup — `_topic_key()` statt exakter String-Matches
- [x] 🔧 **v7.1**: Kontext-Deduplikation — keine redundanten Fakten im LLM-Kontext
- [x] 🔧 **v7.1**: Topic Extraction — deutsche + englische Stopword-Filterung, Frequency-Ranking
- [x] 🔧 **v7.2**: Conversations-Storage (`nexus/core/conversations.py`) — Sessions persistieren, laden, resumen, cleanup
- [x] 🔧 **v7.3**: Telegram Per-User Rate Limiting (`nexus/core/rate_limiter.py`) — Token-Bucket: 1msg/3s, Burst 5, Auto-Cleanup
- [x] 🔧 **v7.4**: Vector Search für L3 Memory (`nexus/core/vector_store.py`) — sentence-transformers Embeddings, Hybrid-Scoring (60% semantisch + 40% Keywords), Persistent Cache
- [x] 🔧 **v7.5**: Per-Chat Session Management (`nexus/core/session_manager.py`) — Isolierte L1-Memory pro Chat, Timeout-basierte Session-Bereinigung, Shared L3/Soul, Conversation Persistence, Thread-safe
- [x] 🔧 **v7.6**: Circular Chain Detection im Agent-Loop (`nexus/core/agent.py`) — A→B→A→B Zyklus-Erkennung, A→B→C→A→B→C 3-Tool-Zyklen, Tool-Cycling-Erkennung (selbes Tool 3x+ mit kurzen Intervallen), Checked VOR Duplicate-Detection, 13 Unit Tests

---

## ~~🔴 KRITISCHE BUGS~~ ✅ BEHOBEN

- **~~LLM Client Retry-Logik KAPUTT~~** — ✅ BEHOBEN: Retry-Schleife korrigiert, `return` nach erstem Fehlschlag entfernt. Exponential Backoff implementiert.
- **~~Config `fallback` wird ignoriert~~** — ✅ BEHOBEN: Neue `_fallback_chain` Property liest Config und baut Chain dynamisch.
- **~~Delegation Tool ist ein Stub~~** — Korrekt: Das Tool-Registry hat einen Stub, aber der Agent routet `delegation` korrekt zu `_handle_delegation()`. Kein Fix nötig — By Design.

---

## 🟡 PRIORITÄT: LLM-VERBINDUNG STABILISIEREN

### ~~1. Retry-Logik reparieren (SOFORT)~~ ✅ ERLEDIGT
- ✅ Retry-Schleife repariert (kein premature return mehr)
- ✅ Exponential Backoff (1s, 2s, 4s, max 16s) mit Jitter
- ✅ Fehler-Kategorisierung: Timeout, Rate-Limit (429), Server Error (5xx), Connection, Model-Not-Found (404)
- ✅ Config-Fallback-Chain dynamisch aus `config.yaml` `fallback` Liste

### ~~2. Fallback-Chain verbessern~~ ✅ ERLEDIGT
- ✅ Primär → Config-Fallback[0] → Config-Fallback[1] → Error
- ✅ `_fallback_depth` verhindert infinite Fallback-Recursion
- ✅ Fallback-Statistiken (`_fallback_count`, `_error_count` in stats)

### ~~3. Timeout-Handling~~ ✅ ERLEDIGT
- ✅ Separater Connect/Read Timeout (`connect_timeout`, `read_timeout`)
- ✅ Progressiver Timeout: Retries bekommen mehr Zeit
- ✅ Async-Streaming-Timeout mit `connect_timeout`

### ~~4. Config-Hot-Reload~~ ✅ ERLEDIGT
- ✅ `nexus/core/config.py` — ConfigManager mit mtime-basiertem File-Watcher
- ✅ Thread-safe config access (RLock-protected dict)
- ✅ Background-Watcher pollt config.yaml alle 5s auf Änderungen
- ✅ Subsystem-Callbacks: LLM, Memory, Performance werden live aktualisiert
- ✅ `apply_config_to_agent()` propagiert Config-Änderungen an laufenden Agent
- ✅ SIGHUP-Signal-Handler für manuelle Reload-Trigger (Unix)
- ✅ `--reload` CLI-Flag für einmaligen Config-Reload
- ✅ 29 Unit-Tests (Loading, Reload, Callbacks, Watcher, Thread-Safety, Stats)
- Async streaming hat noch keinen Fallback (nur sync chat hat Fallback)
- Besser: Bei Stream-Fehler → Sync-Fallback auf anderen Prompt-Teil

---

## 🟡 PRIORITÄT: MEMORY-SYSTEM VERBESSERN

### ~~1. Auto-Compression~~ ✅ ERLEDIGT
- ✅ L1 Compression via `_compress_l1()` bei Token-Overflow
- ✅ **v7.1**: `_extract_session_summary()` statt roher Pipe-Joins — extrahiert Topics, Key Facts, Decisions
- ✅ L2-Einträge haben jetzt strukturierte Felder: `topics[]`, `key_facts[]`, `decisions[]`, `summary`
- ✅ `get_context()` bevorzugt strukturierte L2-Summaries (Themen, Fakten) gegenüber rohen Fragmenten

### ~~2. Kontext-Auswahl~~ ✅ ERLEDIGT
- ✅ Relevanz-basierte L3-Auswahl via `get_relevant_context()` (Keyword + Importance + Recency + Access-Frequency)
- ✅ **v7.1**: Kontext-Deduplikation — `_topic_key()` verhindert redundante Fakten im LLM-Kontext
- ✅ L2-Summaries werden per Topic-Dedup verdoppelt vermieden

### ~~3. Relevanz-Scoring~~ ✅ ERLEDIGT
- ✅ Multi-Keyword-Scoring mit Importance-Gewichtung (`_relevance_score()`)
- ✅ Access-Frequency-Bonus (log-skaliert) + Recency-Bonus (exponentieller Decay, 48h Halbwertszeit)
- ✅ **v7.1**: L3 Fuzzy-Dedup — `_topic_key()` vergleicht Topics statt exakter Strings
- ✅ Memory Decay für ungenutzte/alte Einträge (`_apply_decay()`)
- Zukunft: TF-IDF oder Embedding-basierte Ähnlichkeit

---

## 🟡 PRIORITÄT: SOUL-SYSTEM ERWEITERN

### 1. Adaptive Persönlichkeit
- Aktuell: Starre Personality-Config aus YAML
- Besser: Mood-State (fröhlich, fokussiert, müde), basierend auf Tageszeit/Nutzer/Thema
- Persönlichkeits-Skalen: Formalität 0-1, Humor 0-1, Ausführlichkeit 0-1

### 2. Beziehungsmodell
- Aktuell: Trust-Level + Notes
- Besser: Relationship-Vektor (formal/casual, technisch/einfach, direkt/höflich)
- Automatische Präferenz-Detektion aus Conversations

---

## 🟡 PRIORITÄT: AGENT-LOOP ROBUST MACHEN

### ~~1. Tool-Call Parsing robuster machen~~ ✅ ERLEDIGT
- ✅ `<tool>JSON</tool>` Format (bestehend)
- ✅ `` ```json...``` `` Code-Block-Erkennung hinzugefügt
- ✅ Inline JSON-Erkennung (Line-by-Line Scan nach `"tool"` keys)
- ✅ Fuzzy JSON Repair: Trailing Commas, Missing Braces, Single Quotes

### ~~2. Error Recovery~~ ✅ ERLEDIGT
- ✅ LLM-Fehler wird nicht mehr sofort als finaler Error zurückgegeben
- ✅ Stattdessen: Error-Kontext als System-Message → LLM kann anders formulieren
- ✅ Nach 2 konsekutiven LLM-Fehlern → Graceful Error Message

### ~~3. Infinite Loop Prevention~~ ✅ ERLEDIGT
- ✅ `max_tool_calls` existierte schon (default 15)
- ✅ NEU: Hash-basierte Duplicate Detection → gleicher Tool-Call >3x = Break
- ✅ LLM bekommt Warnung: "versuche anderen Ansatz"
- ✅ `_tool_call_hashes` wird pro `process()` Aufruf zurückgesetzt

### 4. ~~Zirkuläre Ketten-Erkennung~~ ✅ ERLEDIGT (v7.6)
- ✅ `_is_circular_chain()` — detektiert A→B→A→B Pattern (2-Tool-Zyklen)
- ✅ Detektiert A→B→C→A→B→C Pattern (3-Tool-Zyklen)
- ✅ Detektiert Tool-Cycling: selbes Tool 3x+ mit kurzen Intervallen (A→B→A→C→A)
- ✅ Keine False Positives: sequenzielle verschiedene Tools, legitime Revisits nach langen Intervallen
- ✅ Konfigurierbar via `max_chain_repeats` in config.yaml
- ✅ Integriert in Agent-Loop: Circular-Chain-Check VOR Duplicate-Check
- ✅ 13 Unit Tests (Pattern-Detection, False-Positives, Integration, Config)

---

## 🟡 PRIORITÄT: TELEGRAM-BOT PRODUCTION-READY

### 1. Markdown Escaping ✅ ERLEDIGT
- ✅ `escape_markdown_v2()`: Escapes all Telegram MarkdownV2 special chars (_ * [ ] ( ) ~ ` > # + - = | { } . !)
- ✅ `format_markdown_v2()`: Converts standard Markdown → Telegram MarkdownV2 (bold, italic, code, links)
- ✅ `split_markdown_v2()`: Splits long messages at paragraph/line/word boundaries, respects code block boundaries
- ✅ `_send_message()` now sends with `parse_mode="MarkdownV2"` and falls back to plain text on parse errors
- ✅ `_format_markdown()` now properly converts Markdown → MarkdownV2 instead of being a no-op
- ✅ 35 unit tests for all escaping and splitting functions

### 2. Rate Limiting ✅ ERLEDIGT
- ✅ Per-User Token-Bucket Rate Limiter (`nexus/core/rate_limiter.py`)
- ✅ Default: 1 Nachricht / 3s, Burst: 5 — verhindert Spam und API-Abuse
- ✅ Thread-safe via threading.Lock — keine Race Conditions
- ✅ Auto-Cleanup: Entfernt inactive User-Buckets nach 1h
- ✅ Stats-Tracking: allowed/rejected/rejection_rate/active_users
- ✅ `RateLimiter.allow(user_id)` → True/False + `wait_time(user_id)` → Sekunden bis frei
- ✅ Konfigurierbar via `config.yaml` → `telegram.rate_limiter` Sektion
- ✅ Graceful Rate-Limit-Nachricht: "Zu viele Nachrichten. Bitte warte X Sekunden."
- ✅ 27 Unit Tests (TokenBucket + RateLimiter: refill, burst, per-user, thread-safety, cleanup, stats)

### 3. Session Management ✅ ERLEDIGT (v7.5)
- ✅ Per-Chat Agent-Instanzen (`nexus/core/session_manager.py`) — jede Konversation bekommt eigenen NexusAgent
- ✅ Isolierte L1 Working Memory pro Chat — kein Memory-Bleed zwischen Nutzern
- ✅ Shared L3 Long-term Memory und Soul across Sessions — gelernte Fakten bleiben global
- ✅ Timeout-basierte Session-Bereinigung (konfigurierbar, default 1h)
- ✅ Max-Sessions-Limit mit Eviction (älteste idle Session wird entfernt)
- ✅ Auto-Save bei Cleanup und Shutdown (Conversations werden persistiert)
- ✅ Thread-safe Session-Verwaltung (Lock für alle Operationen)
- ✅ Background Cleanup Task im Telegram Bot (periodisch idle Sessions aufräumen)
- ✅ `config.yaml` Sektion: `session_manager` (timeout, max_sessions, cleanup_interval)
- ✅ 26 Unit Tests (Creation, Isolation, Timeout, Removal, Eviction, Thread Safety, Stats)

---

## 🔵 ZUKUNFT

- [ ] Soul: Adaptive Persönlichkeit — Mood-State (Tageszeit/Nutzer/Thema-basiert), Persönlichkeits-Skalen dynamisch
- [ ] Soul: Beziehungs-Vektor — automatische Präferenz-Detektion aus Conversations (formal/casual, technisch/einfach)
- [ ] Agent: Streaming Fallback — bei Stream-Fehler → Sync-Fallback auf anderen Prompt-Teil
- [ ] Multi-User Session Isolation (Web UI + Telegram)
- [ ] Voice Message Unterstützung (Whisper Integration)
- [ ] Image Understanding (Vision Model Integration)
- [ ] Plugin-System für externe Tools
- [ ] Observability Dashboard (Metrics, Tokens, Latenz)
- [ ] WebSocket Real-Time Updates im Web UI

---

## ⛔ BLOCKED

- Kein Ollama Cloud API-Key im Container → Live-LLM-Test nicht möglich
- Kein Telegram Token im Container → Live-Bot-Test nicht möglich