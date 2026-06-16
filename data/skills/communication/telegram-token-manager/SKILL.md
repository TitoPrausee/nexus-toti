---
name: telegram-token-manager
description: Bot Token Management Skill — Hilft bei der Einrichtung und Verwendung von Telegram Bot Tokens in Projekten
---

# Telegram Bot Token Manager

Skill der bei der Einrichtung und Verwendung von Telegram Bot Tokens in Projekten hilft.

## Was dieser Skill macht

- **Token-Validierung**: Testet ob ein Bot Token funktioniert
- **Chat-ID Ermittlung**: Ermittelt Chat-IDs fuer Nachrichten
- **Setup-Assistent**: Fuehrt durch den vollstaendigen Setup-Prozess
- **Token-Management**: Hilft bei der Erstellung und Aktualisierung von Tokens

## Voraussetzungen

- Zugriff auf @BotFather auf Telegram
- Existing Telegram Bot Token (optional, fuer Setup)

## Setup

### Schritt 1: Neuen Bot erstellen

Fuehre den User durch den Bot-Father-Prozess:

> **@BotFather** oeffnen → `/newbot` → Bot-Namen waehlen → Username waehlen (muss auf `.bot` enden) → Token erhalten

**WICHTIG**: Das Token ist GEHEIM. Es sollte in einer `.env` Datei gespeichert werden, niemals im Code.

### Schritt 2: Token testen

Sobald ein Token vorliegt, testen wir es:

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getMe"
```

Erfolgreiche Antwort:
```json
{
  "ok": true,
  "result": {
    "id": 123456789,
    "first_name": "MeinBot",
    "username": "mein_bot"
  }
}
```

### Schritt 3: Chat-ID ermitteln

Um Nachrichten senden zu koennen, brauchen wir die Chat-ID:

1. User sendet dem Bot eine Nachricht auf Telegram
2. Token-Test ausfuehren:
```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | jq '.result[].message.chat.id' | sort -u
```

### Schritt 4: Integration in ein Projekt

Fuer jedes Projekt braucht es:

1. **`.env` Datei** im Projekt-Root:
```env
TELEGRAM_BOT_TOKEN=<BOT_TOKEN>
TELEGRAM_CHAT_ID=<CHAT_ID>
```

2. **Python-Integration** (Beispiel):
```python
import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    return response.json()

# Usage
send_telegram_message("mein Projekt startet...")
```

## Verfuegbare Commands

### `telegram_test_token <token>`
Testet ob ein Bot Token funktioniert.

### `telegram_get_chat_id <token>`
Ermittelt alle Chat-IDs die mit dem Bot kommunizieren.

### `telegram_send_test <token> <chat_id> <message>`
Sendet eine Testnachricht.

### `telegram_setup_guide`
Gibt den vollstaendigen Setup-Guide aus.

## Best Practices

1. **Tokens niemals im Code**: Immer `.env` verwenden
2. **Projekt-spezifische Tokens**: Jedes Projekt sollte seinen eigenen Bot haben
3. **Chat-IDs speichern**: Nach dem Setup Chat-IDs in Config speichern
4. **Error Handling**: Immer auf API-Fehler pruefen

## Troubleshooting

| Problem | Loesung |
|---------|---------|
| Token funktioniert nicht | BotFather → `/token` → Refresh |
| Chat-ID wird nicht erkannt | User muss erst Bot eine Nachricht senden |
| API Error 400 | Falsche Chat-ID oder Token |
| API Error 401 | Token ungueltig oder gesperrt |

## Integration in andere Skills

Jeder Skill der Telegram nutzt, sollte:

1. Diese Skill als Dependency definieren
2. `telegram_test_token` beim Start ausfuehren
3. Chat-IDs in Config cachen
4. Error Handling implementieren