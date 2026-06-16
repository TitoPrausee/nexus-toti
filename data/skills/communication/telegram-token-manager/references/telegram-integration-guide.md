---
name: telegram-integration-guide
description: How-to integrate Telegram Bot in any project
---
# Telegram Bot Integration Guide

## Schnellstart (3 Schritte)

### 1. Bot Token erhalten

1. Öffne **@BotFather** auf Telegram
2. Sende `/newbot`
3. Bot-Namen und Username wählen
4. **Token kopieren** (Format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Chat-ID ermitteln

1. Sende dem Bot eine Nachricht
2. Token testen:
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getMe"
   ```
3. Chat-IDs holen:
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | jq '.result[].message.chat.id' | sort -u
   ```

### 3. In Projekt integrieren

```env
# .env Datei im Projekt-Root
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
```

```python
# Python Beispiel
import os
import requests

def send_telegram(text: str):
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    return response.json()
```

## Verfügbare API Endpoints

| Endpoint | Beschreibung |
|----------|--------------|
| `GET /bot<TOKEN>/getMe` | Bot-Info holen |
| `GET /bot<TOKEN>/getUpdates` | Nachrichten abrufen |
| `POST /bot<TOKEN>/sendMessage` | Nachricht senden |
| `POST /bot<TOKEN>/sendPhoto` | Foto senden |
| `POST /bot<TOKEN>/sendDocument` | Datei senden |

## Beispiele

### Projekt: opencode-fusion
```
TELEGRAM_BOT_TOKEN=<BOT_TOKEN>
TELEGRAM_CHAT_ID=<CHAT_ID>
```

### Projekt: nexus-toti
```
TELEGRAM_BOT_TOKEN=<BOT_TOKEN>
TELEGRAM_CHAT_ID=<CHAT_ID>
```

### Projekt: titoBot
```
TELEGRAM_BOT_TOKEN=<BOT_TOKEN>
TELEGRAM_CHAT_ID=<CHAT_ID>
```

## Fehlerbehandlung

| Error Code | Bedeutung | Lösung |
|------------|-----------|--------|
| 400 | Bad Request | Falsche Chat-ID oder Token |
| 401 | Unauthorized | Token ungültig/s gesperrt |
| 403 | Forbidden | Bot ist im Chat blockiert |
| 429 | Too Many Requests | Rate limit erreicht |

## Best Practices

1. **Tokens niemals im Code** - Immer `.env` oder Secrets Management
2. **Projekt-spezifische Tokens** - Jedes Projekt eigener Bot
3. **Error Logging** - API-Fehler immer loggen
4. **Rate Limiting** - Max 30 Nachrichten/sekunde pro Bot

## Security

- `.env` in `.gitignore` aufnehmen
- Tokens niemals in Commits
- Bot Tokens als "Bot Admin" kennzeichnen
- Chat-IDs nicht öffentlich teilen
