"""Polite fetcher: robots.txt, per-host rate limit, immutable raw cache, text + link cleaning."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
import trafilatura
from lxml import html as lxml_html
from protego import Protego

from cf import config
from cf.interfaces import Page

RAW = config.DATA / "raw"
INDEX = RAW / "index.jsonl"


def host(url: str) -> str:
    return urlparse(url).netloc.lower()


def registrable(url_or_host: str) -> str:
    """Crude registrable domain: last two labels (good enough for .com/.ai/.io company sites)."""
    h = host(url_or_host) if "//" in url_or_host else url_or_host.lower()
    h = h.split(":")[0]
    parts = [p for p in h.split(".") if p]
    if parts and parts[0] == "www":
        parts = parts[1:]
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


class Fetcher:
    def __init__(self, user_agent: str | None = None, min_interval: float | None = None):
        self.ua = user_agent or config.env("CF_USER_AGENT", "connected-frontiers-research-crawler/0.1")
        self.min_interval = float(min_interval or config.env("CF_RATE_LIMIT_SECONDS", "2"))
        self.http = httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": self.ua})
        self._robots: dict[str, Protego | None] = {}
        self._last: dict[str, float] = {}
        self._cache = self._load_index()
        self._failed: dict[str, str] = {}     # url -> reason, remembered for this run
        RAW.mkdir(parents=True, exist_ok=True)

    # ---- public -------------------------------------------------------------------------
    def fetch(self, url: str) -> Page | None:
        url = urldefrag(url)[0]
        if url in self._cache:
            sha = self._cache[url]
            path = RAW / f"{sha}.html"
            if path.exists():
                return self._page(url, path.read_bytes(), sha)
        if url in self._failed:               # don't re-hit a 403 / robots block in the same run
            return None
        if not self.allowed(url):
            return self._fail(url, "robots_disallow")
        self._wait(host(url))
        try:
            r = self.http.get(url)
        except httpx.HTTPError as e:
            return self._fail(url, f"error:{type(e).__name__}")
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or "html" not in ctype:
            return self._fail(url, f"http_{r.status_code}:{ctype[:30]}")
        sha = hashlib.sha256(r.content).hexdigest()
        (RAW / f"{sha}.html").write_bytes(r.content)
        self._cache[url] = sha
        self._log(url, sha, "ok", final_url=str(r.url))
        return self._page(url, r.content, sha)

    def allowed(self, url: str) -> bool:
        h = host(url)
        if h not in self._robots:
            try:
                r = self.http.get(f"{urlparse(url).scheme}://{h}/robots.txt")
                self._robots[h] = Protego.parse(r.text) if r.status_code == 200 else None
            except httpx.HTTPError:
                self._robots[h] = None
        rp = self._robots[h]
        return True if rp is None else rp.can_fetch(url, self.ua)

    # ---- internals ----------------------------------------------------------------------
    def _fail(self, url: str, reason: str) -> None:
        self._failed[url] = reason
        self._log(url, None, reason)

    def _wait(self, h: str) -> None:
        dt = time.monotonic() - self._last.get(h, 0)
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last[h] = time.monotonic()

    def _page(self, url: str, content: bytes, sha: str) -> Page:
        text = trafilatura.extract(content, url=url, include_tables=True, favor_recall=True) or ""
        links: list[str] = []
        title = ""
        try:
            doc = lxml_html.fromstring(content)
            title = (doc.findtext(".//title") or "").strip()
            # Marketing pages keep customers/benchmarks in "cards" that main-content extractors
            # treat as boilerplate. If visible body text is much longer, use it instead.
            body = doc.find(".//body")
            if body is not None:
                for bad in body.xpath(".//script|.//style|.//noscript|.//svg"):
                    bad.drop_tree()
                visible = " ".join(body.text_content().split())
                alts = [a.strip() for a in doc.xpath("//img/@alt") if len(a.strip()) > 3]
                if len(text) < 0.8 * len(visible):   # main-content extractor dropped the cards
                    text = visible
                if alts:                             # logos often name customers only in alt text
                    text += "\n\n[image alt texts]\n" + "\n".join(dict.fromkeys(alts))
            for a in doc.xpath("//a[@href]"):
                href = urldefrag(urljoin(url, a.get("href")))[0]
                if href.startswith("http"):
                    links.append(href)
        except (ValueError, lxml_html.etree.ParserError):
            pass
        return Page(url=url, raw_sha256=sha, text=text, links=list(dict.fromkeys(links)), title=title)

    def _load_index(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if INDEX.exists():
            for line in INDEX.read_text().splitlines():
                rec = json.loads(line)
                if rec.get("sha"):
                    out[rec["url"]] = rec["sha"]
        return out

    def _log(self, url: str, sha: str | None, status: str, **extra) -> None:
        RAW.mkdir(parents=True, exist_ok=True)
        with INDEX.open("a") as f:
            f.write(json.dumps({"url": url, "sha": sha, "status": status,
                                "fetched_at": datetime.now(UTC).isoformat(), **extra}) + "\n")
