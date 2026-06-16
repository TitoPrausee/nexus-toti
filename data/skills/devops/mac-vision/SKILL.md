---
name: mac-vision
description: Mac-Screenshot-basierte Vision — macht Screenshots vom Mac und analysiert sie mit AI Vision. Ermöglicht Mercury den Mac-Bildschirm zu "sehen".
version: 1.0
---

# Mac Vision — Augen für Mercury

Macht Screenshots vom Mac und analysiert sie mit AI Vision, damit Mercury den Bildschirm sehen kann.

## Voraussetzungen

1. **Bildschirmaufnahme-Berechtigung**: Systemeinstellungen → Datenschutz & Sicherheit → Bildschirmaufnahme → Terminal/Python anhaken
2. Mercury Remote Verbindung zum Mac muss stehen
3. `vision_analyze` Tool verfügbar

## Screenshot machen

### Methode 1: screencapture (empfohlen, built-in)
```bash
# Ganzer Bildschirm
python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> 'screencapture -x /tmp/mercury_screen.png'

# Bestimmter Bereich (x,y,width,height)
python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> 'screencapture -x -R 0,0,1920,1080 /tmp/mercury_screen.png'

# Bestimmtes Fenster
python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> 'screencapture -x -w /tmp/mercury_window.png'

# Timed Screenshot (5 Sekunden Delay)
python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> 'screencapture -x -T 5 /tmp/mercury_delayed.png'
```

### Methode 2: Python mss (falls installiert)
```bash
python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> 'python3 -c "import mss; mss.mss().grab(mss.mss().monitors[0]).save(\"/tmp/mercury_mss.png\"); print(\"done\")"
```

## Screenshot vom Mac holen und analysieren

### Schritt 1: Screenshot auf dem Mac machen
```bash
python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> 'screencapture -x /tmp/mercury_screen.png'
```

### Schritt 2: Screenshot auf Dev-Server kopieren
```bash
python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> 'cat /tmp/mercury_screen.png' | base64 > /tmp/mercury_screen_b64.txt
# ODER über mercury get:
python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> 'cat /tmp/mercury_screen.png' > /tmp/mercury_screen.png
```

### Schritt 3: Mit Vision AI analysieren
Nutze das `vision_analyze` Tool:
```
vision_analyze(image_url="/tmp/mercury_screen.png", question="Was siehst du auf dem Bildschirm?")
```

## Kompletter Workflow als Einzeiler

```bash
# 1. Screenshot + Transfer + Analyse
python3 /opt/data/home/mercury-remote/mercury.py exec <HOSTNAME> 'screencapture -x /tmp/ms.png' && \
python3 /opt/data/home/mercury-remote/mercury.py get <HOSTNAME> /tmp/ms.png /tmp/mac_screen.png && \
echo "Screenshot bereit für vision_analyze"
```

Dann: `vision_analyze(image_url="/tmp/mac_screen.png", question="...")`

## Monitor-Auswahl bei 3 Monitoren

```bash
# Monitor 1 (links)
screencapture -x -R 0,0,1920,1080 /tmp/mon1.png

# Monitor 2 (mitte)  
screencapture -x -R 1920,0,1920,1080 /tmp/mon2.png

# Monitor 3 (rechts)
screencapture -x -R 3840,0,1920,1080 /tmp/mon3.png

# Portrait Monitor (1200x1920)
screencapture -x -R 5760,0,1200,1920 /tmp/mon4.png
```

## Praktische Anwendungsfälle

- "Siehst du einen Fehler-Dialog?" → Screenshot + Vision-Analyse
- "Was ist im Safari-Fenster offen?" → Screenshot statt AppleScript
- "Ist der Code im Editor kompiliert?" → Screenshot von VS Code
- "Lies den Text auf dem Bildschirm" → OCR via Vision
- "Finde den Button X" → Vision + Maus-Position berechnen + cliclick

## Kombination: Sehen + Handeln

1. Screenshot → sehen was passiert
2. Vision-Analyse → verstehen was auf dem Bildschirm ist
3. Maus/Tastatur → agieren basierend auf dem Gesehenen
4. Screenshot → Ergebnis verifizieren

## Pitfalls

- **Bildschirmaufnahme-Berechtigung**: Ohne diese geht kein Screenshot. Systemeinstellungen → Datenschutz → Bildschirmaufnahme → Terminal anhaken. Mac neustarten danach!
- **screencapture Fehler "could not create image from display"**: Berechtigung fehlt
- **File Transfer**: Screenshot liegt auf dem MAC unter /tmp/ — muss via `mercury get` oder `cat` auf den Dev-Server geholt werden
- **Auflösung**: Bei Retina ist der Screenshot 2x so groß — -R Koordinaten gelten in logischen Pixeln
- **Timeout**: Screenshot + Transfer + Vision-Analyse dauert ~10-15s insgesamt