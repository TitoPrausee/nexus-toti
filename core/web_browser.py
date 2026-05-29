"""
NEXUS Web Browser — Freier Internet-Zugriff für Toti
=====================================================
Surfen, Suchen, Scrapen — Toti darf frei aufs Internet.

Features:
  - DuckDuckGo Search (kein API-Key nötig)
  - BeautifulSoup4 Web-Scraping
  - URL-Content-Extraction
  - Screenshot via Playwright (falls verfügbar)
  - Rate-Limiting & Safety
"""

import json
import time
import re
import os
import logging
from typing import Optional
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# SAFE IMPORTS
# ═══════════════════════════════════════════════════════════

try:
    import requests as http_requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    http_requests = None

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    BeautifulSoup = None

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False
    DDGS = None


# ═══════════════════════════════════════════════════════════
# WEB BROWSER
# ═══════════════════════════════════════════════════════════

class WebBrowser:
    """
    Toti's Web-Browser — freier Internet-Zugriff.
    
    Methoden:
      - search(query)        → DuckDuckGo Suche
      - fetch(url)           → URL-Content laden
      - extract_text(url)    → Lesbaren Text extrahieren
      - extract_links(url)   → Links von einer Seite
      - download(url, path)  → Datei herunterladen
      - screenshot(url)      → Screenshot einer URL (via Playwright)
    """

    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 "
        "NEXUS-Toti/4.0"
    )

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._last_request_time = 0
        self._min_interval = self.config.get("min_request_interval", 0.5)
        self._max_content_size = self.config.get("max_content_size", 2_000_000)
        self._timeout = self.config.get("timeout", 30)
        self._request_count = 0
        self._error_count = 0

    def _rate_limit(self):
        """Simple Rate-Limiter."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _get_session(self):
        """HTTP Session mit Headers."""
        if not REQUESTS_AVAILABLE:
            return None
        session = http_requests.Session()
        session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
        })
        return session

    # ─── SEARCH ───────────────────────────────────────────

    def search(self, query: str, num_results: int = 8, region: str = "de-de") -> dict:
        """
        DuckDuckGo Web-Suche — kein API-Key nötig.
        Fallback: z-ai web_search Funktion.
        """
        self._rate_limit()
        self._request_count += 1

        # 1. Versuch: duckduckgo_search Library
        if DDGS_AVAILABLE:
            try:
                results = []
                with DDGS() as ddgs:
                    for r in ddgs.text(query, region=region, max_results=num_results):
                        results.append({
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                            "source": "duckduckgo",
                        })
                return {
                    "query": query,
                    "results": results,
                    "count": len(results),
                    "source": "duckduckgo",
                }
            except Exception as e:
                logger.warning(f"DDGS Search fehlgeschlagen: {e}")
                self._error_count += 1

        # 2. Versuch: z-ai CLI
        try:
            import subprocess
            cmd = [
                "z-ai", "function", "--name", "web_search",
                "--args", json.dumps({"query": query, "num": num_results}),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                results = []
                if isinstance(data, list):
                    for item in data:
                        results.append({
                            "title": item.get("name", ""),
                            "url": item.get("url", ""),
                            "snippet": item.get("snippet", ""),
                            "source": "z-ai",
                        })
                return {
                    "query": query,
                    "results": results,
                    "count": len(results),
                    "source": "z-ai",
                }
        except Exception as e:
            logger.warning(f"z-ai Search fehlgeschlagen: {e}")
            self._error_count += 1

        # 3. Versuch: Direkte HTTP-Suche (scraping)
        if REQUESTS_AVAILABLE:
            try:
                return self._search_http(query, num_results)
            except Exception as e:
                self._error_count += 1
                return {"query": query, "results": [], "error": f"Alle Suchmethoden fehlgeschlagen: {e}"}

        return {"query": query, "results": [], "error": "Keine Suchmethode verfügbar. Installiere: pip install duckduckgo-search"}

    def _search_http(self, query: str, num_results: int) -> dict:
        """Fallback: HTML-Suche via Requests."""
        session = self._get_session()
        if not session:
            return {"query": query, "results": [], "error": "requests nicht installiert"}

        url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
        resp = session.get(url, timeout=self._timeout)
        
        results = []
        if BS4_AVAILABLE:
            soup = BeautifulSoup(resp.text, "html.parser")
            for r in soup.select(".result"):
                title_el = r.select_one(".result__title a")
                snippet_el = r.select_one(".result__snippet")
                if title_el:
                    results.append({
                        "title": title_el.get_text(strip=True),
                        "url": title_el.get("href", ""),
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                        "source": "ddg_html",
                    })
                    if len(results) >= num_results:
                        break
        else:
            # Regex-Fallback ohne BS4
            title_pattern = re.compile(r'class="result__title"[^>]*>.*?<a[^>]*>(.*?)</a>', re.DOTALL)
            url_pattern = re.compile(r'<a[^>]*class="result__url"[^>]*href="([^"]*)"')
            snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</[at]', re.DOTALL)
            
            titles = title_pattern.findall(resp.text)
            urls = url_pattern.findall(resp.text)
            snippets = snippet_pattern.findall(resp.text)
            
            for i in range(min(len(titles), num_results)):
                results.append({
                    "title": re.sub(r'<[^>]+>', '', titles[i]).strip(),
                    "url": urls[i] if i < len(urls) else "",
                    "snippet": re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else "",
                    "source": "ddg_regex",
                })

        return {"query": query, "results": results, "count": len(results), "source": "ddg_html"}

    # ─── FETCH ────────────────────────────────────────────

    def fetch(self, url: str, timeout: Optional[int] = None) -> dict:
        """URL-Content laden (HTML oder JSON)."""
        self._rate_limit()
        self._request_count += 1

        if not REQUESTS_AVAILABLE:
            return {"error": "requests-Bibliothek nicht installiert. pip install requests"}

        session = self._get_session()
        if not session:
            return {"error": "Session konnte nicht erstellt werden"}

        try:
            resp = session.get(url, timeout=timeout or self._timeout)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            size = len(resp.content)

            if size > self._max_content_size:
                return {
                    "url": url,
                    "status_code": resp.status_code,
                    "content_type": content_type,
                    "size": size,
                    "error": f"Content zu groß: {size} bytes (max: {self._max_content_size})",
                }

            # JSON?
            if "json" in content_type:
                try:
                    return {
                        "url": url,
                        "status_code": resp.status_code,
                        "content_type": content_type,
                        "size": size,
                        "data": resp.json(),
                        "format": "json",
                    }
                except json.JSONDecodeError:
                    pass

            # HTML → Text extrahieren
            text = resp.text
            if "html" in content_type and BS4_AVAILABLE:
                soup = BeautifulSoup(text, "html.parser")
                # Entferne Script/Style
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)

            return {
                "url": url,
                "status_code": resp.status_code,
                "content_type": content_type,
                "size": size,
                "content": text[:50000],
                "format": "html_to_text" if "html" in content_type else "raw",
            }

        except Exception as e:
            self._error_count += 1
            return {"url": url, "error": str(e)}

    # ─── EXTRACT TEXT ─────────────────────────────────────

    def extract_text(self, url: str) -> dict:
        """Nur den lesbaren Text von einer URL extrahieren."""
        result = self.fetch(url)
        if "error" in result:
            return result

        content = result.get("content", "")
        if BS4_AVAILABLE and "html" in result.get("content_type", ""):
            # Bereits konvertiert in fetch()
            pass
        else:
            # Manuell bereinigen
            content = re.sub(r'<[^>]+>', ' ', content)
            content = re.sub(r'\s+', ' ', content).strip()

        # Metadaten
        title = ""
        if BS4_AVAILABLE and "html" in result.get("content_type", ""):
            try:
                session = self._get_session()
                resp = session.get(url, timeout=self._timeout)
                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("title")
                title = title_tag.get_text(strip=True) if title_tag else ""
            except Exception:
                pass

        return {
            "url": url,
            "title": title,
            "text": content[:30000],
            "size": len(content),
        }

    # ─── EXTRACT LINKS ───────────────────────────────────

    def extract_links(self, url: str, filter_domain: bool = True) -> dict:
        """Links von einer Seite extrahieren."""
        if not REQUESTS_AVAILABLE:
            return {"error": "requests nicht installiert"}

        self._rate_limit()
        self._request_count += 1

        session = self._get_session()
        try:
            resp = session.get(url, timeout=self._timeout)
            parsed_base = urlparse(url)
            base_domain = parsed_base.netloc

            links = []
            if BS4_AVAILABLE:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    full_url = urljoin(url, href)
                    link_domain = urlparse(full_url).netloc
                    
                    if filter_domain and link_domain != base_domain:
                        continue
                    
                    links.append({
                        "url": full_url,
                        "text": a.get_text(strip=True)[:100],
                        "domain": link_domain,
                    })
            else:
                link_pattern = re.compile(r'href=["\']([^"\']+)["\']')
                for match in link_pattern.findall(resp.text):
                    full_url = urljoin(url, match)
                    links.append({"url": full_url, "text": "", "domain": urlparse(full_url).netloc})

            return {"url": url, "links": links[:100], "count": len(links)}

        except Exception as e:
            self._error_count += 1
            return {"url": url, "error": str(e)}

    # ─── DOWNLOAD ─────────────────────────────────────────

    def download(self, url: str, path: str = "") -> dict:
        """Datei herunterladen."""
        if not REQUESTS_AVAILABLE:
            return {"error": "requests nicht installiert"}

        self._rate_limit()
        self._request_count += 1

        if not path:
            filename = os.path.basename(urlparse(url).path) or "download"
            path = os.path.join("/tmp", filename)

        try:
            session = self._get_session()
            resp = session.get(url, timeout=self._timeout, stream=True)
            resp.raise_for_status()

            size = 0
            with open(path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    size += len(chunk)
                    if size > self._max_content_size:
                        f.close()
                        os.unlink(path)
                        return {"error": f"Datei zu groß: {size} bytes"}

            return {
                "url": url,
                "path": path,
                "size": size,
                "content_type": resp.headers.get("Content-Type", ""),
                "status": "downloaded",
            }

        except Exception as e:
            self._error_count += 1
            return {"url": url, "error": str(e)}

    # ─── SCREENSHOT ───────────────────────────────────────

    def screenshot(self, url: str, width: int = 1280, height: int = 720,
                   full_page: bool = False) -> dict:
        """
        Screenshot einer URL via Playwright.
        Falls Playwright nicht verfügbar → Text-Extraction als Fallback.
        """
        try:
            from playwright.sync_api import sync_playwright
            
            self._rate_limit()
            self._request_count += 1

            output_path = os.path.join("/tmp", f"screenshot_{int(time.time())}.png")

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(url, wait_until="domcontentloaded", timeout=self._timeout * 1000)
                
                if full_page:
                    page.screenshot(path=output_path, full_page=True)
                else:
                    page.screenshot(path=output_path)
                
                # Auch den Text extrahieren
                text = page.inner_text("body")[:10000]
                title = page.title()
                browser.close()

            return {
                "url": url,
                "title": title,
                "screenshot_path": output_path,
                "text": text[:5000],
                "width": width,
                "height": height,
                "format": "png",
                "status": "success",
            }

        except ImportError:
            # Playwright nicht verfügbar → Text-Fallback
            logger.info("Playwright nicht verfügbar, nutze Text-Extraction als Fallback")
            result = self.extract_text(url)
            result["note"] = "Playwright nicht installiert. Nur Text-Extraction verfügbar. pip install playwright && playwright install chromium"
            return result
        except Exception as e:
            self._error_count += 1
            return {"url": url, "error": str(e)}

    # ─── STATS ────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "total_requests": self._request_count,
            "total_errors": self._error_count,
            "ddgs_available": DDGS_AVAILABLE,
            "bs4_available": BS4_AVAILABLE,
            "requests_available": REQUESTS_AVAILABLE,
            "playwright_available": self._check_playwright(),
        }

    @staticmethod
    def _check_playwright() -> bool:
        try:
            from playwright.sync_api import sync_playwright
            return True
        except ImportError:
            return False


# ═══════════════════════════════════════════════════════════
# TOOL FUNCTIONS (für ToolRegistry)
# ═══════════════════════════════════════════════════════════

def tool_web_search(query: str, num: int = 8) -> dict:
    """Web-Suche (DuckDuckGo, kein API-Key nötig)."""
    browser = WebBrowser()
    return browser.search(query, num)

def tool_web_fetch(url: str) -> dict:
    """URL-Content laden und als Text zurückgeben."""
    browser = WebBrowser()
    return browser.fetch(url)

def tool_web_extract(url: str) -> dict:
    """Lesbaren Text von einer URL extrahieren."""
    browser = WebBrowser()
    return browser.extract_text(url)

def tool_web_links(url: str) -> dict:
    """Links von einer Webseite extrahieren."""
    browser = WebBrowser()
    return browser.extract_links(url)

def tool_web_download(url: str, path: str = "") -> dict:
    """Datei aus dem Internet herunterladen."""
    browser = WebBrowser()
    return browser.download(url, path)

def tool_web_screenshot(url: str, width: int = 1280, height: int = 720) -> dict:
    """Screenshot einer URL machen (via Playwright)."""
    browser = WebBrowser()
    return browser.screenshot(url, width, height)
