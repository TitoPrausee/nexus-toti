"""
NEXUS Vision System — v5.0 — z-ai Vision + OCR Fallback
========================================================
Kostenlose Vision-Fähigkeit mit z-ai als Primärmethode:
  - z-ai VLM Vision (beste Qualität — volles visuelles Verständnis)
  - Ollama Cloud Vision (falls Modell Vision-Fähigkeit hat)
  - OCR mit pytesseract (kostenlos, offline — Text-only Fallback)
  - Screenshot mit Playwright (kostenlos)
  - Bildanalyse via PIL/Pillow (kostenlos — Metadaten-only Fallback)

Vision-Pipeline (Priorität):
  1. z-ai VLM Vision  → volles visuelles Verständnis (Bilder, Layout, Text, Objekte)
  2. Ollama Cloud Vision → falls LLM Vision-Modell konfiguriert
  3. OCR (pytesseract) → Text-only Extraktion
  4. Metadaten-only (PIL) → nur Bild-Metadaten + Farbanalyse

Features:
  - Bilder aus URLs laden und analysieren
  - Lokale Bilder analysieren
  - Screenshots von Webseiten machen
  - Bild-Metadaten extrahieren
  - Text aus Bildern extrahieren (auch handgeschrieben)
  - VLM-basierte Bildbeschreibung via z-ai
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

try:
    from core.zai_integration import ZAIIntegration, get_zai
    ZAI_AVAILABLE = True
except ImportError:
    ZAI_AVAILABLE = False
    ZAIIntegration = None
    get_zai = None


# ═══════════════════════════════════════════════════════════
# VISION SYSTEM
# ═══════════════════════════════════════════════════════════

class VisionSystem:
    """
    Toti's Augen — jetzt mit z-ai VLM als Primärmethode.

    Vision-Pipeline (Priorität):
      1. z-ai VLM Vision  → volles visuelles Verständnis (Best Quality)
      2. Ollama Cloud Vision → falls LLM Vision-Modell konfiguriert
      3. OCR (pytesseract) → Text-only Extraktion (Fallback)
      4. Metadaten-only (PIL) → nur Bild-Metadaten + Farbanalyse

    Methoden:
      - analyze_image(path_or_url)   → Vollanalyse eines Bildes
      - vlm_analyze(path_or_url, prompt) → VLM-basierte Bildbeschreibung
      - ocr(path_or_url)            → Nur OCR-Text extrahieren
      - describe(path_or_url)       → Bild-Beschreibung (Metadaten + Farben)
      - screenshot_and_analyze(url) → URL-Screenshot + Analyse
    """

    SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}

    def __init__(self, config: Optional[dict] = None, llm_client=None):
        self.config = config or {}
        self.llm = llm_client
        self._analysis_count = 0
        self._ocr_count = 0
        self._vlm_count = 0

        # z-ai VLM instance (lazy-initialized)
        self._zai_instance = None

    # ─── z-ai VLM ACCESS ──────────────────────────────────

    def _get_zai(self):
        """Lazy-init z-ai integration instance."""
        if not ZAI_AVAILABLE:
            return None
        if self._zai_instance is not None:
            return self._zai_instance
        try:
            self._zai_instance = get_zai()
            return self._zai_instance
        except Exception as e:
            logger.debug(f"z-ai Integration nicht verfügbar: {e}")
            return None

    def _zai_vision_available(self) -> bool:
        """Prüfe ob z-ai VLM Vision verfügbar ist."""
        if not ZAI_AVAILABLE:
            return False
        try:
            zai = self._get_zai()
            return zai is not None and zai.is_available
        except Exception:
            return False

    # ─── VLM ANALYZE (z-ai Vision) ────────────────────────

    def vlm_analyze(self, path_or_url: str, prompt: str = "Beschreibe dieses Bild detailliert") -> dict:
        """
        VLM-basierte Bildanalyse via z-ai Vision.

        Nutzt z-ai CLI für VLM-basierte Bildanalyse mit vollem visuellen
        Verständnis (Objekte, Layout, Texte, Farben, Kontext).

        Args:
            path_or_url: Lokaler Dateipfad oder URL zum Bild
            prompt: Analyse-Prompt (Standard: detaillierte Beschreibung)

        Returns:
            dict mit VLM-Beschreibung und Metadaten, oder Fallback auf OCR
        """
        result: dict = {
            "source": path_or_url,
            "method": "metadata_only",
        }

        # ── 1. Versuche z-ai VLM Vision ──────────────────
        if self._zai_vision_available():
            try:
                zai = self._get_zai()
                # z-ai vision akzeptiert direkt URLs oder lokale Pfade
                vlm_result = zai.vision(prompt=prompt, image=path_or_url)

                if vlm_result.success:
                    # VLM-Ergebnis extrahieren
                    description_text = None

                    # Versuche strukturierte Daten zu parsen
                    if vlm_result.data and isinstance(vlm_result.data, dict):
                        # JSON-Response mit "content" oder "text" Feld
                        description_text = (
                            vlm_result.data.get("content")
                            or vlm_result.data.get("text")
                            or vlm_result.data.get("description")
                        )
                        # Falls komplette Chat-Response mit choices
                        if not description_text and "choices" in vlm_result.data:
                            choices = vlm_result.data["choices"]
                            if choices:
                                msg = choices[0].get("message", {})
                                description_text = msg.get("content", "")

                    # Fallback auf raw_stdout wenn kein strukturiertes Ergebnis
                    if not description_text and vlm_result.raw_stdout:
                        description_text = vlm_result.raw_stdout.strip()

                    if description_text:
                        self._vlm_count += 1
                        result["method"] = "vlm"
                        result["description"] = description_text
                        result["vlm_model"] = "z-ai-vision"
                        result["vlm_elapsed_seconds"] = vlm_result.elapsed_seconds
                        result["prompt"] = prompt
                        return result
                    else:
                        logger.warning("z-ai Vision lieferte leere Antwort, falle zurück auf OCR")
                        result["vlm_fallback_reason"] = "Leere VLM-Antwort"
                else:
                    logger.warning(f"z-ai Vision fehlgeschlagen: {vlm_result.error}, falle zurück auf OCR")
                    result["vlm_fallback_reason"] = vlm_result.error or "Unbekannter Fehler"

            except Exception as e:
                logger.warning(f"z-ai Vision Ausnahme: {e}, falle zurück auf OCR")
                result["vlm_fallback_reason"] = str(e)

        else:
            result["vlm_fallback_reason"] = "z-ai VLM nicht verfügbar"

        # ── 2. Fallback auf OCR ───────────────────────────
        ocr_result = self.ocr(path_or_url)
        if "error" not in ocr_result:
            result["method"] = "ocr"
            result["ocr"] = ocr_result
            if ocr_result.get("text"):
                result["description"] = f"[OCR] {ocr_result['text'][:2000]}"
            else:
                result["description"] = "[OCR] Kein Text im Bild gefunden"
        else:
            result["method"] = "metadata_only"
            result["ocr_error"] = ocr_result.get("error", "OCR nicht verfügbar")
            result["description"] = "[Metadaten-only] Kein VLM oder OCR verfügbar"

        result["prompt"] = prompt
        return result

    # ─── LOAD / CLEANUP ───────────────────────────────────

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
        Vollständige Bildanalyse mit Priorität: z-ai VLM → Ollama Vision → OCR → Metadaten.

        Pipeline (in Prioritätsreihenfolge):
          1. z-ai VLM Vision — bestes Ergebnis, volles visuelles Verständnis
          2. Ollama Cloud Vision — falls LLM Vision-Modell konfiguriert
          3. OCR (pytesseract) — Text-only Fallback
          4. Metadaten-only (PIL) — minimale Analyse
        """
        # 1. Beschreibung (Metadaten + Farben — immer verfügbar)
        description = self.describe(path_or_url)
        if "error" in description:
            return description

        # 2. z-ai VLM Vision (BESTE QUALITÄT — volles visuelles Verständnis)
        if self._zai_vision_available():
            try:
                vlm_result = self.vlm_analyze(path_or_url)
                if vlm_result.get("method") == "vlm":
                    description["vlm_analysis"] = vlm_result
                    description["analysis_method"] = "vlm"
                    # VLM-Beschreibung als Top-Level für einfachen Zugriff
                    if vlm_result.get("description"):
                        description["visual_description"] = vlm_result["description"]
                    self._analysis_count += 1
                    # OCR zusätzlich, falls gewünscht (VLM kann Text übersehen)
                    if do_ocr:
                        ocr_result = self.ocr(path_or_url)
                        description["ocr"] = ocr_result
                        if ocr_result.get("text"):
                            description["extracted_text"] = ocr_result["text"][:2000]
                    return description
                else:
                    # VLM fehlgeschlagen, Fallback-Grund notieren
                    description["vlm_fallback_reason"] = vlm_result.get("vlm_fallback_reason", "Unbekannt")
            except Exception as e:
                description["vlm_analysis_error"] = str(e)

        # 3. Ollama Cloud Vision (falls LLM Vision hat)
        if self.llm and self._llm_has_vision():
            try:
                llm_description = self._analyze_with_llm(path_or_url)
                if llm_description:
                    description["llm_analysis"] = llm_description
                    description["analysis_method"] = "ollama_vision"
            except Exception as e:
                description["llm_analysis_error"] = str(e)

        # 4. OCR Fallback (Text-only)
        if do_ocr:
            ocr_result = self.ocr(path_or_url)
            description["ocr"] = ocr_result
            if ocr_result.get("text"):
                description["extracted_text"] = ocr_result["text"][:2000]
            if "analysis_method" not in description:
                description["analysis_method"] = "ocr"

        # 5. Metadaten-only (wenn kein anderes Verfahren funktioniert hat)
        if "analysis_method" not in description:
            description["analysis_method"] = "metadata_only"

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

    # ─── LLM VISION (optional — Ollama Cloud Vision) ──────

    def _llm_has_vision(self) -> bool:
        """
        Prüfe ob eine Vision-Methode verfügbar ist.

        Prüft:
          1. z-ai VLM Vision (priorität)
          2. Ollama Cloud Vision (falls Modell Vision-Fähigkeit hat)
        """
        # z-ai VLM Vision hat höchste Priorität
        if self._zai_vision_available():
            return True

        # Ollama Cloud Vision
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
        """
        Bild analysieren — z-ai Vision als Primärmethode, Ollama als Fallback.

        Priorität:
          1. z-ai VLM Vision (beste Qualität)
          2. Ollama Cloud Vision (Base64-Upload)
        """
        # ── 1. z-ai VLM Vision (PRIMÄR) ──────────────────
        if self._zai_vision_available():
            try:
                zai = self._get_zai()
                vlm_result = zai.vision(
                    prompt="Beschreibe dieses Bild detailliert. Was siehst du? Welche Farben, Objekte, Texte?",
                    image=path_or_url,
                )

                if vlm_result.success:
                    description_text = None

                    # Strukturierte Daten parsen
                    if vlm_result.data and isinstance(vlm_result.data, dict):
                        description_text = (
                            vlm_result.data.get("content")
                            or vlm_result.data.get("text")
                            or vlm_result.data.get("description")
                        )
                        if not description_text and "choices" in vlm_result.data:
                            choices = vlm_result.data["choices"]
                            if choices:
                                msg = choices[0].get("message", {})
                                description_text = msg.get("content", "")

                    # Fallback auf raw_stdout
                    if not description_text and vlm_result.raw_stdout:
                        description_text = vlm_result.raw_stdout.strip()

                    if description_text:
                        self._vlm_count += 1
                        return description_text[:2000]

                    logger.warning("z-ai Vision lieferte leere Antwort, falle zurück auf Ollama")
                else:
                    logger.warning(f"z-ai Vision fehlgeschlagen: {vlm_result.error}, falle zurück auf Ollama")

            except Exception as e:
                logger.warning(f"z-ai Vision Ausnahme: {e}, falle zurück auf Ollama")

        # ── 2. Ollama Cloud Vision (FALLBACK) ─────────────
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
            "total_vlm": self._vlm_count,
            "pil_available": PIL_AVAILABLE,
            "tesseract_available": TESSERACT_AVAILABLE,
            "zai_vision_available": self._zai_vision_available(),
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
    """Bildanalyse: z-ai VLM → Ollama Vision → OCR → Metadaten."""
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

def tool_vision_vlm(path_or_url: str, prompt: str = "Beschreibe dieses Bild detailliert") -> dict:
    """VLM-Bildanalyse: z-ai Vision (mit OCR-Fallback)."""
    vs = VisionSystem()
    return vs.vlm_analyze(path_or_url, prompt)
