# Telegram Token Manager Skill

Ein Skill für Mercury, der bei der Einrichtung und Verwendung von Telegram Bot Tokens in Projekten hilft.

## Struktur

```
telegram-token-manager/
├── SKILL.md                 # Haupt-Dokumentation
├── README.md                # Dieser File
├── scripts/
│   └── telegram_manager.py  # CLI Tool für Token Management
└── references/
    └── telegram-integration-guide.md  # Kurzguide für Projekte
```

## Verwendung

### Als CLI Tool

```bash
# Token testen
python telegram_manager.py test-token <TOKEN>

# Chat-IDs ermitteln
python telegram_manager.py get-chats <TOKEN>

# Bot-Info holen
python telegram_manager.py get-me <TOKEN>

# Testnachricht senden
python telegram_manager.py send-test <TOKEN> <CHAT_ID> "Nachricht"

# Setup Guide anzeigen
python telegram_manager.py setup-guide

# Projekt-Env erstellen
python telegram_manager.py create-project-env <PROJECT_PATH> <TOKEN> <CHAT_ID>

# --- Mercury Config Commands ---
# Holes die Config direkt aus Mercury
python telegram_manager.py config-get

# Testet den Mercury-config Token
python telegram_manager.py config-test

# Ermittelt Chat-IDs aus Mercury config
python telegram_manager.py config-chats
```

### In anderen Projekten

Jedes Projekt das Telegram nutzt, sollte:

1. Diesen Skill als Referenz verwenden
2. Die `.env` Datei mit `TELEGRAM_BOT_TOKEN` und `TELEGRAM_CHAT_ID` einrichten
3. Die `telegram_manager.py` für Setup/Tests verwenden

## Integration in Mercury

Der Skill ist im Mercury Skills Directory zu finden:

```
~/.mercury/home/toti-skills/communication/telegram-token-manager/
```

## Beispiel: opencode-fusion Setup

```bash
# Bot erstellen bei @BotFather
# Token erhalten: <BOT_TOKEN>

# Chat-ID ermitteln
python telegram_manager.py get-chats <BOT_TOKEN>

# Ergebnis: Chat ID <CHAT_ID>

# .env in opencode-fusion/ erstellen
cd opencode-fusion
echo "TELEGRAM_BOT_TOKEN=<BOT_TOKEN>" >> .env
echo "TELEGRAM_CHAT_ID=<CHAT_ID>" >> .env
```

## Aktualisierung

Wenn sich der Skill ändert:

1. Änderungen im Skill-Verzeichnis vornehmen
2. `git commit` und `git push` ausführen (falls Git verwendet)
3. Andere Projekte mit `git pull` aktualisieren

## Support

Bei Problemen:
1. Token testen mit `test-token`
2. Chat-IDs neu ermitteln mit `get-chats`
3. Setup Guide lesen mit `setup-guide`
