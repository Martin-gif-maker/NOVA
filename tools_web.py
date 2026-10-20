# tools_web.py — tools that fetch from the internet: read a web page, search the web, the weather.
# Whatever they return is outside content: tools.py marks the request as "tainted" after they ran.
import re, socket, ipaddress, logging
import ledger
import toolbase
from toolbase import UNTRUSTED_NOTE, fail

log = logging.getLogger("nova")

def _is_public_url(url: str):
    """Refuse localhost / private-network targets (stops the model probing your LAN)."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname
    if not host: return False, "Invalid URL."
    try:
        for _fam, _, _, _, addr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(addr[0].split("%")[0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                    or ip.is_multicast or ip.is_unspecified):
                return False, f"Refusing to open a private/local address ({host})."
    except Exception as e:
        return False, f"Could not resolve {host}: {e}"
    return True, ""

def read_webpage(url: str) -> str:
    try:
        import requests, re
        from html.parser import HTMLParser
        class _Strip(HTMLParser):
            SKIP = ("script", "style", "nav", "footer", "head", "noscript", "svg")
            def __init__(self):
                super().__init__(); self._t=[]; self._depth=0; self.links=[]
            def handle_starttag(self, tag, attrs):
                if tag in self.SKIP: self._depth += 1
                if tag == "a":
                    href = dict(attrs).get("href")
                    if href: self.links.append(href)
            def handle_endtag(self, tag):
                if tag in self.SKIP and self._depth: self._depth -= 1
            def handle_data(self, d):
                if not self._depth and d.strip(): self._t.append(d.strip())
            def text(self): return " ".join(self._t)
        if not url.startswith(("http://","https://")): url = "https://" + url
        ok, why = _is_public_url(url)
        if not ok: return why
        ledger.record(url, "read web page")
        r = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        p = _Strip(); p.feed(r.text)
        from urllib.parse import urljoin
        toolbase.note_urls(urljoin(r.url or url, h) for h in p.links[:500])     # its links may be followed later
        text = re.sub(r"\s{3,}", "  ", p.text())
        return UNTRUSTED_NOTE + text[:4000] if text else "Page is empty."
    except Exception as e: return fail(f"Error reading: {e}")

# ── TOOL: search_web_and_read ────────────────────────────────────
def _note_search_requests() -> None:
    """ddgs asks a shuffled list of search engines (Wikipedia, DuckDuckGo, Yahoo, Google, Brave, Startpage …) until it
    has enough results. Every request it makes goes through its HttpClient, so each is written to "What NOVA sent"
    with its real address - not one "duckduckgo.com" line for a query that went to five places. Set up once."""
    from ddgs.http_client import HttpClient
    if getattr(HttpClient.request, "noted", False): return
    real = HttpClient.request
    def request(self, method, url, *a, **kw):
        sent = {k: kw[k] for k in ("params", "data", "json") if kw.get(k)}
        ledger.record(str(url), "web search", ledger.size_of(sent) if sent else 0, "search query")
        return real(self, method, url, *a, **kw)
    request.noted = True                                        # type: ignore[attr-defined]
    HttpClient.request = request                                # type: ignore[method-assign]


def _search_ddg(query: str, n: int) -> list:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException
    _note_search_requests()
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=n))
    except DDGSException as e:                     # "No results found", a timeout, every engine refused
        log.info("search found nothing: %s", e)
        return []

def _search_brave(query: str, n: int, key: str) -> list:
    """Brave Search API - an official, documented API (needs the user's own key)."""
    import requests
    ledger.record("api.search.brave.com", "web search", len(query.encode("utf-8")), "search query")
    r = requests.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": n},
                     headers={"X-Subscription-Token": key, "Accept": "application/json"}, timeout=10)
    r.raise_for_status()
    hits = (r.json().get("web") or {}).get("results") or []
    return [{"title": re.sub(r"<[^>]+>", "", h.get("title", "")), "href": h.get("url", ""),
             "body": re.sub(r"<[^>]+>", "", h.get("description", ""))} for h in hits[:n]]

def search_web_and_read(query: str, num_results: int = 3) -> str:
    """Search the web (several search engines through ddgs, or the Brave Search API if chosen in Settings)."""
    n = max(1, min(int(num_results or 3), 8))
    try:
        results = None
        import tools
        if tools.SETTINGS.get("search_engine", "ddg") == "brave":
            import keystore
            key = keystore._get_api_key("brave")
            if key:
                try: results = _search_brave(query, n, key)
                except Exception as e: log.warning("Brave search failed (%s) - asking the other search engines", e)
        if results is None:
            results = _search_ddg(query, n)
        if not results:
            return f"No results found for: '{query}'"
        lines = [UNTRUSTED_NOTE + f"Search results for: '{query}'\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.get('title','')}**\n   {r.get('href','')}\n   {(r.get('body') or '')[:300]}\n")
        return "\n".join(lines)[:3200]
    except ImportError:
        from tools_apps import search_web
        search_web(query)
        return fail(f"ddgs is not installed (pip install ddgs) - opened the browser for '{query}'.")
    except Exception as e:
        return fail(f"Search error: {e}")

_WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
        51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
        61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
        71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers", 81: "rain showers",
        82: "violent rain showers", 85: "snow showers", 86: "heavy snow showers",
        95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail"}

def get_weather(location: str = "") -> str:
    """Current weather from Open-Meteo (an official open API, no key). Empty location = the home city from Settings."""
    try:
        import requests as _req
        import tools
        loc = (location or "").strip() or str(tools.SETTINGS.get("home_city", "") or "").strip()
        if not loc:
            return fail("No city given and no home city is set. Ask the user which city they mean "
                        "(they can set a home city in Settings → General).")
        ledger.record("geocoding-api.open-meteo.com", "weather", len(loc.encode("utf-8")), "city name")
        g = _req.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": loc, "count": 1, "language": "en", "format": "json"}, timeout=8)
        g.raise_for_status()
        hits = g.json().get("results") or []
        if not hits: return fail(f"I could not find a place called '{loc}'.")
        h = hits[0]
        ledger.record("api.open-meteo.com", "weather", 0, "the city's coordinates")
        w = _req.get("https://api.open-meteo.com/v1/forecast", timeout=8, params={
            "latitude": h["latitude"], "longitude": h["longitude"], "timezone": "auto", "forecast_days": 1,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
        w.raise_for_status()
        d = w.json(); c = d.get("current") or {}; day = d.get("daily") or {}
        first = lambda k: (day.get(k) or [None])[0]
        place = ", ".join(x for x in (h.get("name"), h.get("country")) if x)
        text = (f"{place}: {_WMO.get(c.get('weather_code'), 'unknown conditions')}, {round(c.get('temperature_2m', 0))}°C "
                f"(feels like {round(c.get('apparent_temperature', 0))}°C), humidity {c.get('relative_humidity_2m', '?')}%, "
                f"wind {round(c.get('wind_speed_10m', 0))} km/h.")
        if first("temperature_2m_min") is not None:
            text += f" Today {round(first('temperature_2m_min'))}–{round(first('temperature_2m_max'))}°C"
            if first("precipitation_probability_max") is not None:
                text += f", chance of rain {round(first('precipitation_probability_max'))}%"
            text += "."
        return text
    except Exception as e:
        return fail(f"Error: {e}")
