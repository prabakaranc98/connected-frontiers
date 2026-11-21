"""v0 rule-based source finder: same-site pages whose paths look informative."""

from __future__ import annotations

from urllib.parse import urlparse

from cf.crawl.fetch import registrable
from cf.interfaces import Page

# Ordered by how often each page type yields ecosystem edges (to be learned by the bandit later).
PATTERNS = ["case-stud", "customer", "research", "training", "platform", "product", "blog",
            "company", "about", "partners", "careers", "news"]
SKIP = ("/legal", "/privacy", "/terms", "/login", "/signup", "/cdn-cgi", ".pdf", ".png", ".jpg")


def same_site_candidates(page: Page, k: int = 6) -> list[str]:
    site = registrable(page.url)
    scored: list[tuple[int, str]] = []
    for link in page.links:
        if registrable(link) != site or link.rstrip("/") == page.url.rstrip("/"):
            continue
        path = urlparse(link).path.lower()
        if any(s in path for s in SKIP) or path in ("", "/"):
            continue
        for rank, pat in enumerate(PATTERNS):
            if pat in path:
                scored.append((rank, link))
                break
    scored.sort()
    return list(dict.fromkeys(u for _, u in scored))[:k]


def homepage(domain: str) -> str:
    return f"https://{domain}/"
