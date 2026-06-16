#!/usr/bin/env python3
"""
Telegram Bot Token Manager für Mercury

Hilft bei der Einrichtung und Verwendung von Telegram Bot Tokens in Projekten.
"""

import os
import sys
import json
import argparse
import requests
import yaml
from pathlib import Path
from typing import Optional


def load_mercury_config() -> dict:
    """Lädt die Mercury config.yaml und gibt die Telegram-Settings zurück."""
    config_path = Path.home() / '.mercury' / 'config.yaml'
    if not config_path.exists():
        return {}
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return config.get('telegram', {})
    except Exception:
        return {}


def load_env_file(env_path: str) -> dict:
    """Lädt eine .env Datei und gibt die Werte als Dict zurück."""
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars


def save_env_file(env_path: str, env_vars: dict) -> None:
    """Speichert eine .env Datei."""
    with open(env_path, 'w') as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")


def test_token(token: str) -> tuple[bool, Optional[dict]]:
    """Testet ob ein Bot Token funktioniert."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('ok'):
            return True, data.get('result')
        return False, None
    except Exception as e:
        return False, {'error': str(e)}


def get_updates(token: str) -> Optional[dict]:
    """Holt alle Updates vom Bot."""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        return response.json()
    except Exception as e:
        return {'error': str(e)}


def get_chat_ids(token: str) -> list:
    """Ermittelt alle Chat-IDs die mit dem Bot kommunizieren."""
    updates = get_updates(token)
    if not updates or not updates.get('ok'):
        return []

    chat_ids = set()
    for update in updates.get('result', []):
        message = update.get('message')
        if message and message.get('chat'):
            chat_ids.add(message['chat']['id'])
    return sorted(list(chat_ids))


def send_message(token: str, chat_id: int, text: str) -> Optional[dict]:
    """Sendet eine Nachricht an einen Chat."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown'
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        return {'error': str(e)}


def create_project_env(project_path: str, bot_token: str, chat_id: int) -> str:
    """Erstellt eine .env Datei für ein Projekt."""
    env_path = os.path.join(project_path, '.env')
    env_vars = load_env_file(env_path)

    env_vars['TELEGRAM_BOT_TOKEN'] = bot_token
    env_vars['TELEGRAM_CHAT_ID'] = str(chat_id)

    save_env_file(env_path, env_vars)
    return env_path


def main():
    parser = argparse.ArgumentParser(
        description='Telegram Bot Token Manager für Mercury'
    )
    subparsers = parser.add_subparsers(dest='command', help='Befehl')

    # Test Token
    test_parser = subparsers.add_parser('test-token', help='Testet einen Bot Token')
    test_parser.add_argument('token', help='Der zu testende Bot Token')

    # Get Chat IDs
    chats_parser = subparsers.add_parser('get-chats', help='Ermittelt Chat-IDs')
    chats_parser.add_argument('token', help='Der Bot Token')

    # Send Test Message
    send_parser = subparsers.add_parser('send-test', help='Sendet eine Testnachricht')
    send_parser.add_argument('token', help='Der Bot Token')
    send_parser.add_argument('chat_id', type=int, help='Die Chat-ID')
    send_parser.add_argument('message', help='Die Nachricht')

    # Setup Guide
    subparsers.add_parser('setup-guide', help='Zeigt den Setup-Guide')

    # Create Project Env
    env_parser = subparsers.add_parser('create-project-env', help='Erstellt .env für Projekt')
    env_parser.add_argument('project_path', help='Pfad zum Projekt')
    env_parser.add_argument('bot_token', help='Bot Token')
    env_parser.add_argument('chat_id', type=int, help='Chat ID')

    # Get Me
    me_parser = subparsers.add_parser('get-me', help='Holt Bot-Info')
    me_parser.add_argument('token', help='Der Bot Token')

    # Commands that use Mercury config
    subparsers.add_parser('config-get', help='Holt Telegram Config aus Mercury')
    subparsers.add_parser('config-test', help='Testet den Mercury-config Token')
    subparsers.add_parser('config-chats', help='Ermittelt Chat-IDs aus Mercury config')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == 'test-token':
        success, result = test_token(args.token)
        output = {
            'success': success,
            'bot': result if success else None
        }
        if not success:
            output['error'] = result.get('error') if result else 'Unbekannter Fehler'
        print(json.dumps(output, indent=2, ensure_ascii=False))
        sys.exit(0 if success else 1)

    elif args.command == 'get-me':
        success, result = test_token(args.token)
        if success:
            print(json.dumps({
                'id': result.get('id'),
                'first_name': result.get('first_name'),
                'username': result.get('username'),
                'can_join_groups': result.get('can_join_groups'),
                'has_main_web_app': result.get('has_main_web_app')
            }, indent=2))
        else:
            print(f"Token ungültig: {result}")
            sys.exit(1)

    elif args.command == 'get-chats':
        chat_ids = get_chat_ids(args.token)
        if chat_ids:
            print(json.dumps({
                'success': True,
                'chat_count': len(chat_ids),
                'chat_ids': chat_ids
            }, indent=2))
        else:
            print(json.dumps({
                'success': False,
                'message': 'Keine Chat-IDs gefunden. Sende dem Bot erst eine Nachricht.'
            }, indent=2))

    elif args.command == 'send-test':
        result = send_message(args.token, args.chat_id, args.message)
        if result and result.get('ok'):
            print(json.dumps({
                'success': True,
                'message_id': result.get('result', {}).get('message_id')
            }, indent=2))
        else:
            print(json.dumps({
                'success': False,
                'error': result.get('error') if result else 'Unbekannter Fehler'
            }, indent=2))

    elif args.command == 'setup-guide':
        guide = """
## Telegram Bot Setup Guide

### Schritt 1: Neuen Bot erstellen

1. Starte @BotFather auf Telegram
2. Sende `/newbot`
3. Wähle einen Bot-Namen (z.B. "Tito Helper Bot")
4. Wähle einen Username (muss auf `.bot` enden, z.B. "tito_helper_bot")
5. Kopiere das erhaltene Token (startet mit `XXXXXXXXX:xxxxxxxxxxxxxxx`)

### Schritt 2: Token speichern

Erstelle in deinem Projekt eine `.env` Datei:

```env
TELEGRAM_BOT_TOKEN=XXXXXXXXX:xxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=123456789
```

### Schritt 3: Chat-ID ermitteln

1. Sende dem Bot eine Nachricht auf Telegram
2. Führe aus: `python telegram_manager.py get-chats <TOKEN>`
3. Kopiere die Chat-ID aus der Ausgabe

### Schritt 4: Integration in dein Projekt

```python
import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    requests.post(url, json=payload)
```

### Schritt 5: Testen

```bash
python telegram_manager.py send-test <TOKEN> <CHAT_ID> "Test erfolgreich!"
```
"""
        print(guide)

    elif args.command == 'create-project-env':
        env_path = create_project_env(args.project_path, args.bot_token, args.chat_id)
        print(json.dumps({
            'success': True,
            'env_path': env_path,
            'bot_token_set': True,
            'chat_id_set': True
        }, indent=2))

    elif args.command == 'config-get':
        """Holt die Telegram Config direkt aus der Mercury config.yaml"""
        config = load_mercury_config()
        output = {
            'success': True,
            'config': {
                'bot_token': config.get('bot_token', 'Nicht konfiguriert'),
                'chat_id': config.get('chat_id', 'Nicht konfiguriert'),
                'channel_prompts': config.get('channel_prompts', {})
            }
        }
        # Token nur anzeigen, wenn er gesetzt ist
        if config.get('bot_token') and len(config.get('bot_token', '')) > 20:
            output['config']['bot_token'] = config['bot_token'][:10] + '...' + config['bot_token'][-10:]
        print(json.dumps(output, indent=2))

    elif args.command == 'config-test':
        """Testet den Token aus der Mercury config.yaml"""
        config = load_mercury_config()
        token = config.get('bot_token')
        if not token:
            print(json.dumps({
                'success': False,
                'error': 'Kein Telegram Bot Token in Mercury config.yaml gefunden'
            }, indent=2))
            sys.exit(1)
        success, result = test_token(token)
        output = {
            'success': success,
            'source': 'mercury_config'
        }
        if success:
            output['bot'] = {
                'id': result.get('id'),
                'username': result.get('username'),
                'first_name': result.get('first_name')
            }
        else:
            output['error'] = result.get('error') if result else 'Unbekannter Fehler'
        print(json.dumps(output, indent=2))
        sys.exit(0 if success else 1)

    elif args.command == 'config-chats':
        """Ermittelt Chat-IDs mit dem Token aus Mercury config.yaml"""
        config = load_mercury_config()
        token = config.get('bot_token')
        if not token:
            print(json.dumps({
                'success': False,
                'error': 'Kein Telegram Bot Token in Mercury config.yaml gefunden'
            }, indent=2))
            sys.exit(1)
        chat_ids = get_chat_ids(token)
        if chat_ids:
            print(json.dumps({
                'success': True,
                'source': 'mercury_config',
                'chat_count': len(chat_ids),
                'chat_ids': chat_ids
            }, indent=2))
        else:
            print(json.dumps({
                'success': False,
                'source': 'mercury_config',
                'message': 'Keine Chat-IDs gefunden. Sende dem Bot erst eine Nachricht.'
            }, indent=2))


if __name__ == '__main__':
    main()
