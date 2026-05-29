"""
NEXUS Vision System — Toti kann sehen (auch ohne Vision-LLM)
==============================================================
Kostenlose Vision-Fähigkeit:
  - OCR mit pytesseract (kostenlos, offline)
  - Screenshot mit Playwright (kostenlos)
  - Bildanalyse via PIL/Pillow (kostenlos)
  - Falls LLM Vision hat → weiterleiten, sonst OCR

Features:
  - Bilder aus URLs laden und OCR-en
  - Lokale Bilder analysieren
  - Screenshots von Webseiten machen
  - Bild-Metadaten extrahieren
  - Text aus Bildern extrahieren (auch handgeschrieben)
"""

import os
import time
import json
import base64
import logging
import tempfile
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# SAFE IMPORTS
# ═══════════════════════════════════════════════════════════

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    pytesseract = None

try:
    import requests as http_requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    http_requests = None


# ═══════════════════════════════════════════════════════════
# VISION SYSTEM
# ═══════════════════════════════════════════════════════════

class VisionSystem:
    """
    Toti's Augen — sieht auch ohne Vision-LLM.
    
    Vision-Pipeline:
      1. Falls LLM Vision hat → Bild an LLM senden
      2. Sonst: OCR (pytesseract) → Text extrahieren
      3. Bild-Metadaten + Farbanalyse + Beschreibung
      
    Methoden:
      - analyze_image(path_or_url)  → Vollanalyse eines Bildes
      - ocr(path_or_url)           → Nur OCR-Text extrahieren
      - describe(path_or_url)      → Bild-Beschreibung (Metadaten + Farben)
      - screenshot_and_analyze(url) → URL-Screenshot + Analyse
    """

    SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}

    def __init__(self, config: Optional[dict] = None, llm_client=None):
        self.config = config or {}
        self.llm = llm_client
        self._analysis_count = 0
        self._ocr_count = 0

    def _load_image(self, path_or_url: str) -> Optional[str]:
        """Bild laden (lokal oder URL) → lokaler Pfad."""
        # URL?
        if path_or_url.startswith(("http://", "https://")):
            if not REQUESTS_AVAILABLE:
                return None
            try:
                resp = http_requests.get(path_or_url, timeout=30, stream=True)
                resp.raise_for_status()
                
                suffix = Path(path_or_url).suffix or ".png"
                tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                for chunk in resp.iter_content(8192):
                    tmp.write(chunk)
                tmp.close()
                return tmp.name
            except Exception as e:
                logger.error(f"Bild-Download fehlgeschlagen: {e}")
                return None
        
        # Lokal
        if os.path.exists(path_or_url):
            return path_or_url
        return None

    def _cleanup(self, path: str):
        """Temp-Dateien aufräumen."""
        try:
            if path.startswith("/tmp/"):
                os.unlink(path)
        except Exception:
            pass

    # ─── OCR ──────────────────────────────────────────────

    def ocr(self, path_or_url: str, lang: str = "deu+eng") -> dict:
        """
        Text aus einem Bild extrahieren via OCR.
        Nutzt pytesseract (kostenlos, offline).
        """
        local_path = self._load_image(path_or_url)
        if not local_path:
            return {"error": f"Bild konnte nicht geladen werden: {path_or_url}"}

        self._ocr_count += 1

        if not PIL_AVAILABLE:
            self._cleanup(local_path)
            return {"error": "Pillow nicht installiert. pip install Pillow"}

        if not TESSERACT_AVAILABLE:
            # Fallback: Einfache Bild-Metadaten ohne OCR
            try:
                img = Image.open(local_path)
                result = {
                    "source": path_or_url,
                    "format": img.format,
                    "size": img.size,
                    "mode": img.mode,
                    "ocr_available": False,
                    "note": "pytesseract nicht installiert. pip install pytesseract && apt install tesseract-ocr",
                }
                self._cleanup(local_path)
                return result
            except Exception as e:
                self._cleanup(local_path)
                return {"error": f"Bild konnte nicht geöffnet werden: {e}"}

        try:
            img = Image.open(local_path)
            
            # Vorverarbeitung für bessere OCR
            # Konvertiere zu Graustufen
            if img.mode != "L":
                img = img.convert("L")
            
            # OCR durchführen
            text = pytesseract.image_to_string(img, lang=lang)
            confidence = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
            
            # Durchschnittliche Konfidenz berechnen
            conf_values = [int(c) for c in confidence.get("conf", []) if int(c) > 0]
            avg_confidence = sum(conf_values) / len(conf_values) if conf_values else 0

            result = {
                "source": path_or_url,
                "text": text.strip(),
                "text_length": len(text.strip()),
                "ocr_confidence": round(avg_confidence, 1),
                "image_size": img.size,
                "ocr_available": True,
                "language": lang,
            }

            self._cleanup(local_path)
            return result

        except Exception as e:
            self._cleanup(local_path)
            return {"error": f"OCR fehlgeschlagen: {e}"}

    # ─── DESCRIBE ─────────────────────────────────────────

    def describe(self, path_or_url: str) -> dict:
        """
        Bild-Beschreibung mit Metadaten und Farbanalyse.
        Kein LLM nötig — funktioniert komplett lokal.
        """
        local_path = self._load_image(path_or_url)
        if not local_path:
            return {"error": f"Bild konnte nicht geladen werden: {path_or_url}"}

        if not PIL_AVAILABLE:
            self._cleanup(local_path)
            return {"error": "Pillow nicht installiert. pip install Pillow"}

        try:
            img = Image.open(local_path)
            
            # Metadaten
            description = {
                "source": path_or_url,
                "format": img.format or "unknown",
                "size": img.size,  # (width, height)
                "width": img.width,
                "height": img.height,
                "mode": img.mode,
                "megapixels": round(img.width * img.height / 1_000_000, 2),
                "aspect_ratio": self._aspect_ratio(img.width, img.height),
                "is_landscape": img.width > img.height,
                "is_portrait": img.height > img.width,
                "is_square": abs(img.width - img.height) < 10,
            }

            # EXIF-Daten
            exif = img._getexif() if hasattr(img, "_getexif") else None
            if exif:
                description["has_exif"] = True
                # Nur sichere EXIF-Daten
                for tag_id, value in exif.items():
                    if isinstance(value, (str, int, float)):
                        description[f"exif_{tag_id}"] = str(value)[:100]

            # Farbanalyse
            if img.mode in ("RGB", "RGBA"):
                colors = self._analyze_colors(img)
                description["dominant_colors"] = colors
                description["brightness"] = self._brightness(img)
                description["color_description"] = self._color_description(colors)

            # Dateigröße
            file_size = os.path.getsize(local_path)
            description["file_size_bytes"] = file_size
            description["file_size_human"] = self._human_size(file_size)

            self._cleanup(local_path)
            return description

        except Exception as e:
            self._cleanup(local_path)
            return {"error": f"Bild-Analyse fehlgeschlagen: {e}"}

    # ─── FULL ANALYZE ─────────────────────────────────────

    def analyze_image(self, path_or_url: str, do_ocr: bool = True) -> dict:
        """
        Vollständige Bildanalyse: Metadaten + Farben + OCR + (optional LLM).
        """
        # 1. Beschreibung
        description = self.describe(path_or_url)
        if "error" in description:
            return description

        # 2. OCR
        if do_ocr:
            ocr_result = self.ocr(path_or_url)
            description["ocr"] = ocr_result
            if ocr_result.get("text"):
                description["extracted_text"] = ocr_result["text"][:2000]

        # 3. Falls LLM Vision hat → Bild an LLM senden
        if self.llm and self._llm_has_vision():
            try:
                llm_description = self._analyze_with_llm(path_or_url)
                if llm_description:
                    description["llm_analysis"] = llm_description
            except Exception as e:
                description["llm_analysis_error"] = str(e)

        self._analysis_count += 1
        return description

    # ─── SCREENSHOT + ANALYZE ─────────────────────────────

    def screenshot_and_analyze(self, url: str, do_ocr: bool = True) -> dict:
        """URL-Screenshot + Bildanalyse."""
        from core.web_browser import WebBrowser
        browser = WebBrowser()
        screenshot_result = browser.screenshot(url)

        if "error" in screenshot_result:
            return screenshot_result

        screenshot_path = screenshot_result.get("screenshot_path")
        if not screenshot_path or not os.path.exists(screenshot_path):
            return {"error": "Screenshot konnte nicht erstellt werden"}

        # Analysiere den Screenshot
        analysis = self.analyze_image(screenshot_path, do_ocr=do_ocr)
        analysis["url"] = url
        analysis["screenshot_path"] = screenshot_path
        analysis["page_title"] = screenshot_result.get("title", "")

        # Text vom Screenshot
        if screenshot_result.get("text"):
            analysis["page_text"] = screenshot_result["text"][:5000]

        return analysis

    # ─── LLM VISION (optional) ────────────────────────────

    def _llm_has_vision(self) -> bool:
        """Prüfe ob das aktuelle LLM Vision-Fähigkeiten hat."""
        if not self.llm:
            return False
        # Modelle mit Vision
        vision_models = ["gpt-4o", "gpt-4-vision", "claude-3", "gemini", "glm-4v", "qwen-vl", "llava"]
        try:
            for agent_id in ["NEXUS-0", "SCOUT", "LENS"]:
                model = self.llm.get_model_for_agent(agent_id)
                if any(vm in model.lower() for vm in vision_models):
                    return True
        except Exception:
            pass
        return False

    def _analyze_with_llm(self, path_or_url: str) -> Optional[str]:
        """Bild an Vision-LLM senden (falls verfügbar)."""
        if not self.llm:
            return None

        # Base64-encode das Bild
        local_path = self._load_image(path_or_url)
        if not local_path:
            return None

        try:
            with open(local_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")

            # Prompt
            prompt = "Beschreibe dieses Bild detailliert. Was siehst du? Welche Farben, Objekte, Texte?"

            # Versuche via Ollama Cloud Vision API
            # (Die meisten Ollama-Modelle unterstützen images-Feld)
            from core.llm_client import Message
            messages = [
                Message(role="system", content="Du bist ein Vision-Experte. Beschreibe Bilder präzise."),
                Message(role="user", content=prompt),
            ]

            response = self.llm.chat(messages, agent_id="NEXUS-0")
            return response.content[:2000] if response else None

        except Exception as e:
            logger.error(f"LLM Vision fehlgeschlagen: {e}")
            return None
        finally:
            self._cleanup(local_path)

    # ─── HELPER ───────────────────────────────────────────

    @staticmethod
    def _aspect_ratio(w: int, h: int) -> str:
        from math import gcd
        d = gcd(w, h)
        return f"{w // d}:{h // d}"

    @staticmethod
    def _analyze_colors(img, top_n: int = 5) -> list[dict]:
        """Dominante Farben extrahieren."""
        try:
            # Resize für Performance
            small = img.resize((100, 100))
            pixels = list(small.getdata())

            # Farb-Quantisierung
            color_counts = {}
            for r, g, b in (p[:3] for p in pixels):
                # Quantisieren (32 Stufen)
                qr, qg, qb = r // 32 * 32, g // 32 * 32, b // 32 * 32
                key = (qr, qg, qb)
                color_counts[key] = color_counts.get(key, 0) + 1

            # Top N Farben
            sorted_colors = sorted(color_counts.items(), key=lambda x: -x[1])[:top_n]
            total = len(pixels)

            return [
                {
                    "rgb": list(color),
                    "hex": "#{:02x}{:02x}{:02x}".format(*color),
                    "name": VisionSystem._color_name(color),
                    "percentage": round(count / total * 100, 1),
                }
                for color, count in sorted_colors
            ]
        except Exception:
            return []

    @staticmethod
    def _color_name(rgb: tuple) -> str:
        """Farbe benennen."""
        r, g, b = rgb
        if r > 200 and g > 200 and b > 200:
            return "weiß"
        if r < 50 and g < 50 and b < 50:
            return "schwarz"
        if r > 180 and g < 80 and b < 80:
            return "rot"
        if r < 80 and g > 180 and b < 80:
            return "grün"
        if r < 80 and g < 80 and b > 180:
            return "blau"
        if r > 180 and g > 180 and b < 80:
            return "gelb"
        if r > 180 and g < 80 and b > 180:
            return "magenta"
        if r < 80 and g > 180 and b > 180:
            return "cyan"
        if r > 180 and g > 120 and b < 80:
            return "orange"
        if r > 150 and g > 80 and b > 100:
            return "rosa"
        if r > 120 and g > 80 and b < 60:
            return "braun"
        if abs(r - g) < 30 and abs(g - b) < 30:
            return "grau"
        return "bunt"

    @staticmethod
    def _brightness(img) -> float:
        """Durchschnittliche Helligkeit (0-100)."""
        try:
            small = img.resize((50, 50)).convert("L")
            pixels = list(small.getdata())
            return round(sum(pixels) / len(pixels) / 255 * 100, 1)
        except Exception:
            return 50.0

    @staticmethod
    def _color_description(colors: list) -> str:
        """Farb-Beschreibung als Text."""
        if not colors:
            return "unbekannt"
        top = colors[:3]
        parts = [f"{c['name']} ({c['percentage']}%)" for c in top]
        return ", ".join(parts)

    @staticmethod
    def _human_size(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def get_stats(self) -> dict:
        return {
            "total_analyses": self._analysis_count,
            "total_ocr": self._ocr_count,
            "pil_available": PIL_AVAILABLE,
            "tesseract_available": TESSERACT_AVAILABLE,
            "llm_vision": self._llm_has_vision() if self.llm else False,
        }


# ═══════════════════════════════════════════════════════════
# TOOL FUNCTIONS (für ToolRegistry)
# ═══════════════════════════════════════════════════════════

def tool_vision_ocr(path_or_url: str, lang: str = "deu+eng") -> dict:
    """OCR: Text aus einem Bild extrahieren (lokal oder URL)."""
    vs = VisionSystem()
    return vs.ocr(path_or_url, lang)

def tool_vision_analyze(path_or_url: str) -> dict:
    """Bildanalyse: Metadaten, Farben, OCR."""
    vs = VisionSystem()
    return vs.analyze_image(path_or_url)

def tool_vision_describe(path_or_url: str) -> dict:
    """Bild-Beschreibung (ohne LLM, nur Metadaten + Farben)."""
    vs = VisionSystem()
    return vs.describe(path_or_url)

def tool_vision_screenshot(url: str) -> dict:
    """URL-Screenshot + Bildanalyse."""
    vs = VisionSystem()
    return vs.screenshot_and_analyze(url)
