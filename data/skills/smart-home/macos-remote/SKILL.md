---
name: macos-remote
description: Connect to and manage remote Mac machines in Tito's network via Tailscale VPN and SSH. Homebridge, Home Assistant, Calendar, and general remote control.
version: 1.0
---

# macOS Remote Management via SSH + Tailscale

Connect to and manage remote Mac machines in Tito's network via Tailscale VPN and SSH.

## Connection Details

- Mac Mini 2018 (Intel i5-8500B, 8GB, macOS 15.7.1): Tailscale `<PRIVATE_IP>`, user `titoprause`
- SSH key: `/opt/data/.ssh/id_ed25519`
- Second Mac (FSU): `<PRIVATE_IP>` — SSH key NOT deployed, access denied

## Critical Pitfalls

### ⚠️ NEVER use `sudo shutdown` without safeguards
`sudo shutdown -h +N` immediately activates "NO LOGINS" system banner that **blocks ALL new SSH connections**, including the cancel command. The shutdown cannot be cancelled remotely once this banner is active.

**Safe pattern:**
```bash
# WRONG — will lock you out:
echo 'password' | sudo -S shutdown -h +5

# Use osascript as alternative (may need user confirmation):
osascript -e 'tell application "Finder" to shut down'

# SAFEST — tell the user to shut down manually
```

After a shutdown is scheduled, all SSH attempts get `NO LOGINS: System going down at ...` and the connection closes with exit code 255.

### ⚠️ Container hat KEINEN Tailscale-Zugriff
Hermes läuft in einem Container ohne `tailscaled`. Der `100.x`-Mesh ist NICHT direkt erreichbar. **Immer SSH auf den Mac Mini verwenden** als Gateway ins LAN.

```bash
# Hermes-Container → Mac Mini SSH → LAN-Scan
ssh -i /opt/data/.ssh/id_ed25519 titoprause@<PRIVATE_IP> "arp -a | grep fritz"
```

### ⚠️ `node` not in default SSH PATH
Homebridge uses Node.js at `/usr/local/bin/node` (not in default SSH PATH). Always set:
```bash
export PATH=/usr/local/bin:$PATH
```
before running `homebridge` or `hb-service`.

### ⚠️ Starte Homebridge NUR via `screen` (kein nohup/nohup/disown)
Der Hermes-System-Guard blockiert Shell-Background-Wrapper. Nutze `screen`:
```bash
screen -dmS homebridge bash -c 'export PATH=/usr/local/bin:$PATH; cd ~/.homebridge; homebridge -U ~/.homebridge 2>&1 | tee -a ~/.homebridge/homebridge.log'
```
Warten, dann prüfen:
```bash
screen -ls                    # zeigt laufende Sessions
lsof -i -P -n | grep 51826  # HAP Bridge Port
ps aux | grep homebridge    # Prozess check
```

## Homebridge ("Henry Home")

- Config: `~/.homebridge/config.json`
- Bridge: "Henry Home", Pin: `031-45-154`
- Ports: 51826 (bridge), 8581 (config UI)
- Integrated with Home Assistant at `localhost:8123` (currently offline)
- Supported types: light, switch, media_player, sensor, binary_sensor, climate
- Start via `screen` (see Pitfalls above), NOT `nohup`

**Status prüfen:**
```bash
screen -ls
lsof -i -P -n | grep -E '(51826|8581)'
tail -20 ~/.homebridge/homebridge.log
```

**Starten (wenn es ausgefallen ist):**
```bash
screen -dmS homebridge bash -c 'export PATH=/usr/local/bin:$PATH; cd ~/.homebridge; homebridge -U ~/.homebridge 2>&1 | tee -a ~/.homebridge/homebridge.log'
```

### Hue Bridges im LAN (via Mac Mini SSH)
Die Hue Bridges haben Signify-MACs (`f4:34:f0:xx:xx:xx`) und sind per `arp -a` sichtbar (Fritz!Box-Netz 192.168.178.x):

```bash
ssh -i /opt/data/.ssh/id_ed25519 titoprause@<PRIVATE_IP> "arp -a | grep f4:34:f0"
```

**Bekannte Bridges (Stand Mai 2026):**
| Name | IP | MAC |
|---|---|---|
| Wohnzimmer | 192.168.178.43 | f4:34:f0:62:c1:62 |
| Schlafzimmer | 192.168.178.93 | f4:34:f0:42:8c:db |

**Direkte HTTP-API:** Funktioniert nur mit Pairing. Ohne Auth schweigen die Bridges.

### Netzwerk auf dem Mac Mini
Das Fritz!Box LAN ist 192.168.178.0/24 (nicht 192.168.1.x):
```bash
arp -a                        # Alle LAN-Geräte
lsof -i -P -n | grep node     # Homebridge-Verbindungen
```

## Home Assistant

- Configured at `localhost:8123` but NOT running
- Integrated with Homebridge via `homebridge-homeassistant` plugin
- Needs investigation: uninstalled or just not started?

## Useful Commands

```bash
# System info
ssh -i /opt/data/.ssh/id_ed25519 titoprause@<PRIVATE_IP> "sw_vers; sysctl -n machdep.cpu.brand_string"

# Running apps
ps aux | grep -v grep | awk '{print $11}' | sort -u

# Listening ports
lsof -i -P -n | grep LISTEN | awk '{print $1, $9}' | sort -u

# Tailscale check
tailscale status | grep macmini

# Start Homebridge
export PATH=/usr/local/bin:$PATH && homebridge -U ~/.homebridge
```

## iSH on iPhone (Alpine Linux)

- iPhone 15 Pro: Tailscale `<PRIVATE_IP>`
- iSH app provides Alpine Linux container with SSH server
- SSH access via `root@<PRIVATE_IP>` (password: configured by user)

**Setup iSH SSH server:**
```bash
# In iSH terminal (one line at a time!):
apk add openssh
ssh-keygen -A
passwd root          # set password
printf 'PermitRootLogin yes\nPasswordAuthentication yes\n' | tee -a /etc/ssh/sshd_config
echo "ListenAddress 0.0.0.0" >> /etc/ssh/sshd_config  # CRITICAL: default binds to 127.0.0.1 only
kill $(cat /var/run/sshd.pid 2>/dev/null) 2>/dev/null; /usr/sbin/sshd
```

**PITFALL: iSH sshd binds to localhost (127.0.0.1) by default.** Without `ListenAddress 0.0.0.0`, the SSH server is NOT reachable from Tailscale. Must add this line to `/etc/ssh/sshd_config` before starting sshd.

**PITFALL: iOS line breaks in iSH terminal.** Commands must be entered as single lines. Copy-pasting multi-line commands often breaks because iOS auto-wraps long lines, creating syntax errors like `-ash: can't create /etc/: Is a directory`. Use `printf` instead of `echo` for multi-value appends.

**PITFALL: `sshd` in iSH requires absolute path.** Running `sshd` gives "re-exec requires execution with an absolute path". Always use `/usr/sbin/sshd`.

## Apple TV Steuerung via pyatv

Der Apple TV kann direkt über SSH auf dem Mac Mini gesteuert werden (kein Homebridge-Plugin nötig, HomeKit geht nativ).

**Apple TV Details (Wohnzimmer):**
- IP: `192.168.178.31`
- MAC: `2E:E3:80:3D:67:20`
- Device ID: `2EE3803D6720`
- Modell: Apple TV 4K, tvOS 26.4

**pyatv Installation & Einrichtung (einmalig):**
```bash
# Installation
pip3 install --user pyatv

# PATH setzen (pyatv installiert nach ~/Library/Python/3.9/bin)
export PATH="/Users/titoprause/Library/Python/3.9/bin:$PATH"

# Apple TV im LAN finden
atvremote scan --scan-hosts 192.168.178.31
```

**Pairing (einmalig erforderlich):**
```bash
# Code erscheint auf dem Apple TV-Bildschirm, mit OK bestätigen
atvremote --id 2EE3803D6720 --protocol companion pair
# Credentials werden automatisch gespeichert
```

**Steuerung (nach Pairing):**
```bash
export PATH="/Users/titoprause/Library/Python/3.9/bin:$PATH"
atvremote --id 2EE3803D6720 turn_on     # Einschalten
atvremote --id 2EE3803D6720 turn_off    # Ausschalten
atvremote --id 2EE3803D6720 menu        # Menu-Button
atvremote --id 2EE3803D6720 select      # Select/OK
atvremote --id 2EE3803D6720 down        # Navigation
```

**PITFALL:** Ohne vorheriges Pairing funktioniert keine Steuerung — der Apple TV zeigt einen Code an, der bestätigt werden muss. Dieser Schritt kann nicht automatisiert werden.

**PITFALL:** macOS hat kein `timeout`-Kommando. Bei Pairing-Versuchen crasht `atvremote` mit KeyboardInterrupt, wenn der Benutzer nicht rechtzeitig bestätigt.

**PITFALL:** Der Befehl heißt `turn_on`, nicht `power_on`. `power_on` ist ungültig.

**PITFALL:** Der Mac Mini PATH enthält `/usr/local/bin` nicht per Default in SSH-Sessions. pyatv-Binarys liegen zusätzlich in `~/Library/Python/3.9/bin`. Beides exportieren:
```bash
export PATH="/usr/local/bin:/Users/titoprause/Library/Python/3.9/bin:$PATH"
```

## iOS Device Detection (Recovery Mode, USB-connected)

When an iPad/iPhone is connected via USB to the Mac Mini and in Recovery Mode, detect it via `system_profiler`:

```bash
# USB-verbose scan — zeigt iOS-Geräte incl. Recovery Mode
system_profiler SPUSBDataType 2>/dev/null | grep -A20 -iE '(ipad|iphone|apple.*mobile|recovery)'
```

**Key indicators:**
- Product ID: `0x1281` = Recovery Mode
- Serial Number field shows: `SDOM:01 CPID:8112 ... SRNM:[JKM6MK4QXD]`
- `SRNM` = Geräte-Seriennummer, `CPID` = Chip-ID

**iOS Tools (`libimobiledevice`)** sind typischerweise **NICHT** standardmässig auf macOS installiert:
```bash
which idevicebackup2 ideviceinfo idevicerestore  # meist NICHT vorhanden
brew install libimobiledevice  # falls Homebrew verfügbar
```

**WICHTIG: Recovery Mode ≠ Normaler Modus**
- Recovery Mode: nur Firmware-Restore möglich, **KEIN vollständiges User-Daten-Backup**
- Für echte Backups (Fotos, Apps): Gerät muss normal booten, dann `idevicebackup2 backup /pfad`

## Android TV

- Device: `65oled85512` (Android), Tailscale `<PRIVATE_IP>`
- Needs ADB debugging enabled on TV + Tailscale app running
- Can use scrcpy for screen mirroring when online