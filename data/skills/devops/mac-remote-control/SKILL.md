---
name: mac-remote-control
description: Vollständige Mac-Fernsteuerung via Mercury Remote — Maus, Tastatur, Apps, Safari, Dateien, Clipboard, System
version: 1.0
---

# Mac Remote Control

Vollständige Fernsteuerung des Mac (M2 Pro, macOS 26) via Mercury Remote über Tailscale.

## Verbindung

- **Peer-Name:** `<HOSTNAME>`
- **Mac IP:** `<PRIVATE_IP>:9443`
- **Mac launchd:** `com.mercury.peer` — startet automatisch bei Login, auto-restart bei Crash
- **Befehl:** `python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> "<cmd>"`

## Shell-Befehle

```bash
python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> '<shell-befehl>'
```

Jeder Shell-Befehl funktioniert: `ls`, `cat`, `mkdir`, `rm`, `brew`, `git`, `curl`, etc.

## App-Steuerung (AppleScript)

### Apps starten/beenden
```bash
# Starten
mercury exec <HOSTNAME> 'open -a "Safari"'
mercury exec <HOSTNAME> 'open -a "Notes"'

# Beenden
mercury exec <HOSTNAME> 'osascript -e "tell application \"Notes\" to quit"'
```

### Fenster positionieren
```bash
mercury exec <HOSTNAME> 'osascript -e "tell application \"Safari\" to set bounds of front window to {0, 25, 1920, 1080}"'
```

### Apps minimieren
```bash
mercury exec <HOSTNAME> 'osascript -e "tell application \"System Events\" to try" -e "tell process \"Google Chrome\" to set miniaturized of every window to true" -e "end try"'
```

## Safari-Kontrolle

### Tabs lesen
```bash
mercury exec <HOSTNAME> 'osascript -e "tell application \"Safari\" to get {URL, name} of every tab of front window"'
```

### URL ändern
```bash
mercury exec <HOSTNAME> 'osascript -e "tell application \"Safari\" to set URL of current tab of front window to \"https://example.com\""'
```

### Neuen Tab öffnen
```bash
mercury exec <HOSTNAME> 'osascript -e "tell application \"Safari\" to activate" -e "tell application \"System Events\" to keystroke \"t\" using command down"'
```

### Tab schließen
```bash
mercury exec <HOSTNAME> 'osascript -e "tell application \"Safari\" to close current tab of front window"'
```

## Maus-Steuerung (cliclick)

`cliclick` ist unter `/opt/homebrew/bin/cliclick` installiert.

| Aktion | Befehl |
|---|---|
| Bewegen | `cliclick m:X,Y` |
| Klick | `cliclick c:X,Y` |
| Doppelklick | `cliclick dc:X,Y` |
| Rechtsklick | `cliclick rc:X,Y` |
| Drag Start | `cliclick dd:X,Y` |
| Drag Ende | `cliclick du:X,Y` |

```bash
mercury exec <HOSTNAME> '/opt/homebrew/bin/cliclick m:500,500'    # Maus bewegen
mercury exec <HOSTNAME> '/opt/homebrew/bin/cliclick c:500,500'    # Klick
mercury exec <HOSTNAME> '/opt/homebrew/bin/cliclick rc:500,500'   # Rechtsklick
mercury exec <HOSTNAME> '/opt/homebrew/bin/cliclick dc:500,500'   # Doppelklick
mercury exec <HOSTNAME> '/opt/homebrew/bin/cliclick dd:200,500 du:800,500'  # Drag & Drop
```

## Tastatur-Steuerung

```bash
# Tastenkombinationen
mercury exec <HOSTNAME> 'osascript -e "tell application \"System Events\" to keystroke \"f\" using command down"'  # ⌘F
mercury exec <HOSTNAME> 'osascript -e "tell application \"System Events\" to keystroke \"w\" using command down"'  # ⌘W
mercury exec <HOSTNAME> 'osascript -e "tell application \"System Events\" to keystroke \"q\" using command down"'  # ⌘Q

# Text eingeben
mercury exec <HOSTNAME> 'osascript -e "tell application \"System Events\" to keystroke \"hello world\""'

# Modifier: command, option, control, shift
mercury exec <HOSTNAME> 'osascript -e "tell application \"System Events\" to keystroke \" \" using {command down, option down}"'  # ⌘⌥Space
```

## System-Steuerung

### System-Info
```bash
mercury exec <HOSTNAME> 'sw_vers'                    # macOS Version
mercury exec <HOSTNAME> 'sysctl -n machdep.cpu.brand_string'  # CPU
mercury exec <HOSTNAME> 'df -h /'                   # Festplatte
mercury exec <HOSTNAME> 'uptime'                     # Uptime
```

### Lautstärke
```bash
mercury exec <HOSTNAME> 'osascript -e "set volume output volume 50"'   # 50%
mercury exec <HOSTNAME> 'osascript -e "output volume of (get volume settings)"'  # Lesen
```

### Hintergrundbild
```bash
mercury exec <HOSTNAME> 'osascript -e "tell application \"System Events\" to get picture of desktop 1"'  # Lesen
mercury exec <HOSTNAME> 'osascript -e "tell application \"System Events\" to set picture of every desktop to \"Pfad/zum/Bild.jpg\""'  # Setzen
```

### Desktops
```bash
mercury exec <HOSTNAME> 'osascript -e "tell application \"System Events\" to get count of desktops"'  # Anzahl
```

### Akku/Strom
```bash
mercury exec <HOSTNAME> 'pmset -g batt'
```

## Clipboard
```bash
mercury exec <HOSTNAME> 'pbpaste'              # Lesen
mercury exec <HOSTNAME> 'echo "text" | pbcopy' # Schreiben
```

## Mail
```bash
mercury exec <HOSTNAME> 'osascript -e "tell application \"Mail\" to get count of messages of inbox"'
```

## Dateisystem
```bash
mercury exec <HOSTNAME> 'ls ~/Desktop/'
mercury exec <HOSTNAME> 'mkdir -p ~/Desktop/NeuerOrdner'
mercury exec <HOSTNAME> 'mv ~/Desktop/file ~/Dokumente/'
mercury exec <HOSTNAME> 'rm /tmp/testfile'
```

## Komplexe AppleScripts (als File)

Bei komplexen Scripts auf dem Mac speichern und ausführen:
```bash
mercury exec <HOSTNAME> 'cat > /tmp/script.sh << SCRIPT
#!/bin/bash
osascript <<EOF
tell application "System Events"
  -- komplexer Code hier
end tell
EOF
SCRIPT
bash /tmp/script.sh'
```

## Pitfalls

- **Shell-Escaping**: Komplexe AppleScripts immer als `.sh` File auf dem Mac speichern statt inline
- **Hilfszugriff**: Manche AppleScript-Befehle brauchen "Hilfszugriff" in macOS Systemeinstellungen → Datenschutz
- **Kein Screenshot-View**: Ich kann den Bildschirm steuern aber nicht sehen — für visuelle Checks muss der User bestätigen
- **cliclick Pfad**: `/opt/homebrew/bin/cliclick` (nicht im Standard-PATH bei mercury exec)
- **Mercury-Verbindung**: Wenn `exec` fehlschlägt → Peer auf Dev-Server prüfen: `python3 mercury.py peer` im Hintergrund
- **Timeout**: Längere Befehle brauchen `timeout=30` oder mehr