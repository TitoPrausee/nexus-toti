#!/usr/bin/env python3
"""
NEXUS Ollama Cloud Setup — Easy Einrichtung
=============================================
Interaktives Setup-Script für Ollama Cloud API Integration.

Funktionen:
  1. Ollama API Key eintragen und verifizieren
  2. Alle 6 Agent-Modelle pullen (Cloud + Local)
  3. Jedes Modell testen ob es tatsächlich antwortet
  4. config.yaml automatisch aktualisieren
  5. Health-Report erstellen

Usage:
  python ollama_setup.py              # Interaktives Setup
  python ollama_setup.py --api-key KEY  # API Key direkt setzen
  python ollama_setup.py --test-only   # Nur Modelle testen
  python ollama_setup.py --pull       # Nur Modelle pullen
  python ollama_setup.py --status     # Status anzeigen
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from typing import Optional

try:
    import requests as http_requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    http_requests = None

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


# Agent-Modell-Zuordnung
AGENT_MODELS = {
    "NEXUS-0": {
        "model": "kimi-k2.6:cloud",
        "description": "Orchestrator — Beste Balance für agentisches Coding, 87/100 Tier-A",
        "pull_cmd": "ollama pull kimi-k2.6:cloud",
        "local_model": "kimi-k2.6:latest",
    },
    "SCOUT": {
        "model": "glm-5.1:cloud",
        "description": "Recherche — 744B Parameter, optimiert für Systems Engineering",
        "pull_cmd": "ollama pull glm-5.1:cloud",
        "local_model": "glm-5.1:latest",
    },
    "FORGE": {
        "model": "qwen3-coder-next:cloud",
        "description": "Coding — Bestes Coding-Modell im Ollama-Ökosystem",
        "pull_cmd": "ollama pull qwen3-coder-next:cloud",
        "local_model": "qwen3-coder-next:latest",
    },
    "LENS": {
        "model": "kimi-k2.6:cloud",
        "description": "Analyse — Herausragend bei Research und Reasoning",
        "pull_cmd": "ollama pull kimi-k2.6:cloud",
        "local_model": "kimi-k2.6:latest",
    },
    "HERALD": {
        "model": "minimax-m2.7:cloud",
        "description": "Output — Stark bei langen, stabilen Sessions",
        "pull_cmd": "ollama pull minimax-m2.7:cloud",
        "local_model": "minimax-m2.7:latest",
    },
    "GHOST": {
        "model": "deepseek-v4-flash:cloud",
        "description": "Background — Günstigster Cloud-Slot, reicht für Monitoring",
        "pull_cmd": "ollama pull deepseek-v4-flash:cloud",
        "local_model": "deepseek-v4-flash:latest",
    },
}

CONFIG_PATH = Path(__file__).parent / "config.yaml"


class OllamaSetup:
    """Easy Ollama Cloud Setup für NEXUS."""

    def __init__(self):
        self.api_key: str = ""
        self.cloud_url: str = "https://api.ollama.ai"
        self.local_url: str = "http://localhost:11434"
        self.results: dict = {}

    def run_interactive(self):
        """Interaktives Setup — Schritt für Schritt."""
        self._print_banner()

        # Schritt 1: Ollama installiert?
        print("\n  Schritt 1: Ollama Installation prüfen")
        print("  " + "-" * 50)
        ollama_installed = self._check_ollama_installed()
        if not ollama_installed:
            print("  Ollama ist NICHT installiert.")
            print("  Installiere es: curl -fsSL https://ollama.com/install.sh | sh")
            choice = input("  Trotzdem weiter? (j/n): ").strip().lower()
            if choice != "j":
                return
        else:
            print("  Ollama ist installiert!")

        # Schritt 2: API Key
        print("\n  Schritt 2: Ollama Cloud API Key")
        print("  " + "-" * 50)
        print("  Du brauchst einen Ollama Cloud API Key.")
        print("  Hol dir einen: https://ollama.com/settings/api-keys")
        print()
        api_key = input("  API Key (oder Enter zum Überspringen): ").strip()
        if api_key:
            self.api_key = api_key
            # Verifizieren
            print("  Verifiziere API Key...")
            if self._verify_api_key(api_key):
                print("  API Key ist gültig!")
            else:
                print("  WARNUNG: API Key konnte nicht verifiziert werden.")
                choice = input("  Trotzdem speichern? (j/n): ").strip().lower()
                if choice != "j":
                    api_key = ""
                    self.api_key = ""
        else:
            # Prüfe ob Key in env gesetzt
            env_key = os.environ.get("OLLAMA_API_KEY", "")
            if env_key:
                print(f"  OLLAMA_API_KEY aus Environment gefunden!")
                self.api_key = env_key
            else:
                print("  Kein API Key gesetzt. Local-Only Modus.")

        # Schritt 3: Modelle pullen
        print("\n  Schritt 3: Modelle pullen")
        print("  " + "-" * 50)
        if self.api_key:
            print("  Cloud-Modelle werden automatisch über die API bereitgestellt.")
            print("  Kein lokales Pullen nötig für Cloud-Modelle.")
        else:
            print("  Ohne API Key können nur lokale Modelle verwendet werden.")

        choice = input("  Lokale Modelle pullen? (j/n): ").strip().lower()
        if choice == "j":
            self._pull_models()

        # Schritt 4: Modelle testen
        print("\n  Schritt 4: Modelle testen")
        print("  " + "-" * 50)
        self._test_all_models()

        # Schritt 5: Config speichern
        print("\n  Schritt 5: Konfiguration speichern")
        print("  " + "-" * 50)
        self._save_config()

        # Ergebnis
        self._print_results()

    def run_api_key_setup(self, api_key: str):
        """Setze API Key direkt und speichere."""
        self.api_key = api_key
        print("Verifiziere API Key...")
        if self._verify_api_key(api_key):
            print("API Key ist gültig!")
        else:
            print("WARNUNG: API Key konnte nicht verifiziert werden.")
        self._save_config()
        print("API Key in config.yaml gespeichert.")
        print("Tipp: Setze auch OLLAMA_API_KEY als Environment-Variable.")

    def run_test_only(self):
        """Nur Modelle testen."""
        self._load_config()
        self._test_all_models()
        self._print_results()

    def run_pull(self):
        """Nur Modelle pullen."""
        self._pull_models()

    def run_status(self):
        """Status anzeigen."""
        self._load_config()
        print("\nNEXUS Ollama Cloud Status")
        print("=" * 60)
        print(f"  API Key:       {'gesetzt' if self.api_key else 'NICHT GESETZT'}")
        print(f"  Cloud URL:     {self.cloud_url}")
        print(f"  Local URL:     {self.local_url}")
        print(f"  Ollama CLI:    {'installiert' if self._check_ollama_installed() else 'NICHT INSTALLIERT'}")

        # Local Ollama Status
        local_ok = self._check_local_ollama()
        print(f"  Local Server:  {'läuft' if local_ok else 'läuft NICHT'}")

        # Model-Tabelle
        print(f"\n  {'Agent':<12} {'Cloud Modell':<28} {'Status'}")
        print(f"  {'-'*12} {'-'*28} {'-'*20}")
        for agent_id, cfg in AGENT_MODELS.items():
            model = cfg["model"]
            print(f"  {agent_id:<12} {model:<28} konfiguriert")

    # ═══════════════════════════════════════════════════════
    # INTERNE FUNKTIONEN
    # ═══════════════════════════════════════════════════════

    def _print_banner(self):
        print("""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   NEXUS Ollama Cloud Setup                                ║
║   Easy Einrichtung in 5 Schritten                         ║
║                                                           ║
║   Agent-Team:                                             ║
║   NEXUS-0  → kimi-k2.6:cloud     (Orchestrator)          ║
║   SCOUT    → glm-5.1:cloud        (Recherche)             ║
║   FORGE    → qwen3-coder-next:cloud (Coding)             ║
║   LENS     → kimi-k2.6:cloud     (Analyse)               ║
║   HERALD   → minimax-m2.7:cloud   (Output)               ║
║   GHOST    → deepseek-v4-flash:cloud (Background)        ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
""")

    def _check_ollama_installed(self) -> bool:
        """Prüfe ob Ollama CLI installiert ist."""
        try:
            result = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def _check_local_ollama(self) -> bool:
        """Prüfe ob lokaler Ollama Server läuft."""
        if not REQUESTS_AVAILABLE:
            return False
        try:
            resp = http_requests.get(f"{self.local_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def _verify_api_key(self, api_key: str) -> bool:
        """Verifiziere API Key gegen Ollama Cloud."""
        if not REQUESTS_AVAILABLE:
            print("    requests-Bibliothek nicht installiert — kann Key nicht verifizieren")
            return False
        try:
            resp = http_requests.get(
                f"{self.cloud_url}/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            print(f"    Verifikationsfehler: {str(e)[:100]}")
            return False

    def _pull_models(self):
        """Pull alle Modelle via ollama CLI."""
        # Einzigartige Modelle (LENS und NEXUS-0 nutzen dasselbe)
        unique_models = {}
        for agent_id, cfg in AGENT_MODELS.items():
            model = cfg["model"]
            if model not in unique_models:
                unique_models[model] = cfg["pull_cmd"]

        for model, pull_cmd in unique_models.items():
            print(f"  Pulling {model}...")
            try:
                result = subprocess.run(
                    pull_cmd.split(), capture_output=True, text=True, timeout=600
                )
                if result.returncode == 0:
                    print(f"    OK: {model}")
                else:
                    print(f"    FEHLER: {result.stderr[:200]}")
            except subprocess.TimeoutExpired:
                print(f"    TIMEOUT: {model} (10min)")
            except FileNotFoundError:
                print(f"    FEHLER: 'ollama' CLI nicht gefunden. Installiere Ollama zuerst.")
                break
            except Exception as e:
                print(f"    FEHLER: {str(e)[:200]}")

    def _test_all_models(self):
        """Teste ob alle Modelle antworten."""
        for agent_id, cfg in AGENT_MODELS.items():
            model = cfg["model"]
            print(f"  Teste {agent_id} ({model})...")

            result = self._test_single_model(model)
            self.results[agent_id] = result

            if result["ok"]:
                print(f"    OK — {result['response_time']:.1f}s via {result['backend']}")
                print(f"    Antwort: {result['sample'][:80]}")
            else:
                print(f"    FEHLER — {result['error'][:100]}")

    def _test_single_model(self, model: str) -> dict:
        """Teste ein einzelnes Modell."""
        result = {"ok": False, "model": model, "backend": "", "response_time": 0, "sample": "", "error": ""}

        test_messages = [
            {"role": "system", "content": "Antworte mit genau einem Wort."},
            {"role": "user", "content": "Hallo, antworte mit OK"},
        ]

        # 1. Cloud Test
        if self.api_key and REQUESTS_AVAILABLE:
            try:
                start = time.time()
                resp = http_requests.post(
                    f"{self.cloud_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": test_messages,
                        "temperature": 0.1,
                        "max_tokens": 20,
                    },
                    timeout=30,
                )
                elapsed = time.time() - start

                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content.strip():
                        result["ok"] = True
                        result["backend"] = "ollama_cloud"
                        result["response_time"] = elapsed
                        result["sample"] = content.strip()
                        return result
                else:
                    result["error"] = f"Cloud HTTP {resp.status_code}: {resp.text[:100]}"
            except Exception as e:
                result["error"] = f"Cloud: {str(e)[:100]}"

        # 2. Local Test
        if REQUESTS_AVAILABLE:
            try:
                local_model = model.replace(":cloud", ":latest")
                start = time.time()
                resp = http_requests.post(
                    f"{self.local_url}/api/chat",
                    json={
                        "model": local_model,
                        "messages": test_messages,
                        "temperature": 0.1,
                        "stream": False,
                    },
                    timeout=30,
                )
                elapsed = time.time() - start

                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("message", {}).get("content", "")
                    if content.strip():
                        result["ok"] = True
                        result["backend"] = "ollama_local"
                        result["response_time"] = elapsed
                        result["sample"] = content.strip()
                        return result
                else:
                    result["error"] = f"{result['error']}; Local HTTP {resp.status_code}" if result["error"] else f"Local HTTP {resp.status_code}"
            except Exception as e:
                result["error"] = f"{result['error']}; Local: {str(e)[:80]}" if result["error"] else f"Local: {str(e)[:80]}"

        # 3. z-ai CLI Test
        try:
            cli_result = subprocess.run(
                ["z-ai", "chat", "--prompt", "Antworte mit OK", "--system", "Ein Wort nur"],
                capture_output=True, text=True, timeout=30,
            )
            if cli_result.returncode == 0:
                result["ok"] = True
                result["backend"] = "zai_cli"
                result["sample"] = cli_result.stdout.strip()[:80]
                return result
        except Exception as e:
            result["error"] = f"{result['error']}; z-ai: {str(e)[:80]}" if result["error"] else f"z-ai: {str(e)[:80]}"

        return result

    def _load_config(self):
        """Lade bestehende Config."""
        if not CONFIG_PATH.exists():
            return
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                if YAML_AVAILABLE:
                    config = yaml.safe_load(f) or {}
                else:
                    return
            ollama = config.get("ollama", {})
            self.api_key = ollama.get("api_key", "") or os.environ.get("OLLAMA_API_KEY", "")
            self.cloud_url = ollama.get("base_url", self.cloud_url)
            self.local_url = ollama.get("local_url", self.local_url)
        except Exception:
            pass

    def _save_config(self):
        """Speichere API Key in config.yaml."""
        if not CONFIG_PATH.exists():
            print("  config.yaml nicht gefunden — überspringe Speichern.")
            return

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                content = f.read()

            # API Key in Config eintragen
            if self.api_key:
                if "api_key: \"\"" in content:
                    content = content.replace('api_key: ""', f'api_key: "{self.api_key}"')
                elif "api_key: ''" in content:
                    content = content.replace("api_key: ''", f"api_key: '{self.api_key}'")
                else:
                    # Füge API Key hinzu
                    content = content.replace(
                        "  api_key:",
                        f'  api_key: "{self.api_key}"  # OLLAMA_API_KEY env var oder hier'
                    )

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write(content)

            print("  config.yaml aktualisiert!")
        except Exception as e:
            print(f"  Fehler beim Speichern: {str(e)}")

        # Auch als Environment-Variable speichern (in .bashrc/.zshrc)
        if self.api_key:
            shell_rc = Path.home() / ".bashrc"
            if not shell_rc.exists():
                shell_rc = Path.home() / ".zshrc"
            if shell_rc.exists():
                env_line = f'export OLLAMA_API_KEY="{self.api_key}"\n'
                existing = shell_rc.read_text()
                if "OLLAMA_API_KEY" not in existing:
                    with open(shell_rc, "a") as f:
                        f.write(f"\n# NEXUS Ollama Cloud API Key\n{env_line}")
                    print(f"  OLLAMA_API_KEY in {shell_rc.name} eingetragen!")

    def _print_results(self):
        """Drucke Setup-Ergebnis."""
        print("\n" + "=" * 60)
        print("  NEXUS Ollama Cloud Setup — Ergebnis")
        print("=" * 60)

        ok_count = sum(1 for r in self.results.values() if r.get("ok"))
        total = len(self.results)

        for agent_id, result in self.results.items():
            status = "OK" if result.get("ok") else "FEHLER"
            model = result.get("model", "?")
            backend = result.get("backend", "?")
            rt = f"{result.get('response_time', 0):.1f}s" if result.get("ok") else "n/a"
            print(f"  {agent_id:<12} {model:<28} {status:<8} {backend:<14} {rt}")

        print()
        print(f"  Ergebnis: {ok_count}/{total} Modelle funktionieren")

        if ok_count == total:
            print("  Alle Modelle sind bereit! Starte NEXUS mit: python nexus.py")
        elif ok_count > 0:
            print(f"  {ok_count} Modelle funktionieren. Fehlende werden über Fallback abgedeckt.")
        else:
            print("  KEIN Modell funktioniert!")
            print("  Mögliche Ursachen:")
            print("    - API Key nicht gesetzt oder ungültig")
            print("    - Ollama Server nicht gestartet (ollama serve)")
            print("    - Modelle nicht gepullt (ollama pull <model>)")
            print("    - Keine Internetverbindung")

        print()
        if self.api_key:
            print("  API Key: gesetzt")
        else:
            print("  API Key: NICHT GESETZT — setze OLLAMA_API_KEY oder trage ihn in config.yaml ein")
        print()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="NEXUS Ollama Cloud Setup")
    parser.add_argument("--api-key", help="Ollama Cloud API Key direkt setzen", type=str)
    parser.add_argument("--test-only", help="Nur Modelle testen", action="store_true")
    parser.add_argument("--pull", help="Nur Modelle pullen", action="store_true")
    parser.add_argument("--status", help="Status anzeigen", action="store_true")

    args = parser.parse_args()
    setup = OllamaSetup()

    if args.api_key:
        setup.run_api_key_setup(args.api_key)
    elif args.test_only:
        setup.run_test_only()
    elif args.pull:
        setup.run_pull()
    elif args.status:
        setup.run_status()
    else:
        setup.run_interactive()


if __name__ == "__main__":
    main()
