"""Noise gates: keep the crawl and the graph from filling up with junk as it scales.

Page gates (before any LLM cost):  URL patterns · blocked domains · thin pages · near-duplicates
Entity gate (after extraction):    generic names ("Inference", "Agents", "Platform") never become
                                   graph nodes; they create fake hubs that distort PageRank.
Every gate counts what it dropped, so the report shows the effect.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict

SKIP_PATH = re.compile(
    r"(/legal|/privacy|/terms|/cookie|/login|/signin|/sign-in|/signup|/sign-up|/register|/account|/cart|/checkout"
    r"|/tag/|/tags/|/category/|/categories/|/author/|/authors/|/page/\d+|[?&]page=|/search|/feed|/rss|/wp-|/cdn-cgi"
    r"|/status|/unsubscribe|/press-kit|/brand|\.xml$|\.pdf$|\.zip$|\.png$|\.jpe?g$|\.svg$|\.mp4$)", re.IGNORECASE)
LOCALE = re.compile(r"^/(fr|de|es|it|ja|ko|zh|pt|ru|nl|sv|pl|tr|ar|he|id|vi|th|hi|uk|da|fi|no|cs|el|ro|hu)(-[a-z]{2,4})?(/|$)", re.IGNORECASE)
BLOCKED_DOMAINS = {
    "linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com", "youtube.com", "youtu.be", "tiktok.com",
    "reddit.com", "medium.com", "substack.com", "wikipedia.org", "github.com", "discord.gg", "discord.com",
    "google.com", "apple.com", "calendly.com", "typeform.com", "greenhouse.io", "lever.co", "ashbyhq.com",
    "bit.ly", "t.co", "goo.gl", "vimeo.com", "spotify.com", "podcasts.apple.com", "eventbrite.com", "lu.ma",
    # utility / footer links seen in the live feed (co-cited by many sites, never ecosystem content)
    "gmail.com", "forms.gle", "googleusercontent.com", "blogger.com", "twitch.tv", "youtubekids.com",
    "myworkdayjobs.com", "workday.com", "archive.org", "biorxiv.org", "arxiv.org", "doi.org", "europa.eu",
    "w3.org", "schema.org", "cloudflare.com", "hubspot.com", "mailchimp.com", "zendesk.com", "intercom.com",
    "gstatic.com", "googleapis.com", "googletagmanager.com", "doubleclick.net", "wordpress.com", "wix.com",
    "squarespace.com", "notion.site", "gitbook.io", "readthedocs.io", "pinterest.com", "threads.net", "bsky.app",
    "mastodon.social", "news.ycombinator.com", "producthunt.com", "crunchbase.com", "glassdoor.com", "indeed.com",
}
# general media / analysts: they cover everything, so for an ecosystem KG they add noise, not structure
MEDIA = {"theguardian.com", "nbcsports.com", "telemundo.com", "nbcuniversal.com", "nbcnews.com", "cnn.com", "nytimes.com",
         "bbc.co.uk", "bbc.com", "forbes.com", "bloomberg.com", "reuters.com", "wsj.com", "ft.com", "cnbc.com", "theverge.com",
         "wired.com", "businessinsider.com", "statista.com", "forrester.com", "gartner.com", "mckinsey.com", "economist.com",
         "washingtonpost.com", "apnews.com", "axios.com", "fortune.com", "time.com", "usatoday.com", "foxnews.com"}
BLOCKED_DOMAINS |= MEDIA
BLOCKED_SUFFIXES = (".google", ".gov", ".mil")       # seeds are exempt (e.g. deepmind.google)
GENERIC = {
    "ai", "ml", "agents", "agent", "inference", "compute", "training", "models", "model", "platform", "platforms",
    "api", "apis", "data", "gpu", "gpus", "cloud", "enterprise", "enterprises", "customers", "customer", "research",
    "products", "product", "solutions", "solution", "security", "search", "chat", "tools", "tool", "infrastructure",
    "apps", "applications", "automation", "analytics", "sandbox", "sandboxes", "library", "batch", "deployment",
    "hardware", "software", "coding", "storage", "services", "service", "partners", "startups", "developers",
    "teams", "companies", "users", "workflows", "workflow", "llm", "llms", "genai", "generative ai", "machine learning",
    "artificial intelligence",
}


def url_ok(url: str, path: str) -> bool:
    return not SKIP_PATH.search(url) and not LOCALE.search(path)


def domain_ok(domain: str) -> bool:
    return (domain not in BLOCKED_DOMAINS and not any(domain.endswith("." + d) for d in BLOCKED_DOMAINS)
            and not domain.endswith(BLOCKED_SUFFIXES))


def is_generic(name: str) -> bool:
    n = re.sub(r"[^a-z0-9 +.-]", "", (name or "").casefold()).strip()
    return len(n) <= 2 or n in GENERIC


METRIC = re.compile(
    r"^\s*(up to |over |more than |~|<|>|\$|€)?\d[\d,.]*\s*(%|x\b|×|\+|k\+?\b|m\+?\b|b\+?\b|bn\b|"
    r"-?(million|billion|thousand|ms|s|sec|seconds?|minutes?|hours?|days?|weeks?|months?|years?|tokens?|"
    r"events?|users?|customers?|requests?|gpus?|tasks?|ward|times|fold|point|percent|step)\b|\s+(per|of|in|faster|"
    r"more|less|fewer|lower|higher|reduction|improvement|increase|decrease|savings?|cost|users?|customers?|"
    r"microservices|creatives|employees|developers|companies|countries|languages|parameter|model))", re.IGNORECASE)
AWARD = re.compile(r"^\d{4}\s+.*\b(award|awards|leadership|winner)\b", re.IGNORECASE)
KEEP_NUMERIC = {"org", "paper"}           # "10x Genomics", "11x", "10 years of AlphaGo" are real names


def is_metric(name: str, etype: str | None = None) -> bool:
    """A number-led phrase extracted as a node ("1B events per month", "up to 99.6% cache hits"):
    it is a claim about something, not a thing. Orgs and paper titles are exempt."""
    if etype in KEEP_NUMERIC:
        return False
    return bool(METRIC.match(name or "") or AWARD.match(name or ""))


class DupIndex:
    """Near-duplicate pages per host via word 5-gram shingles (Jaccard ≥ threshold)."""

    def __init__(self, threshold: float = 0.92):
        self.threshold = threshold
        self.by_host: dict[str, list[set[int]]] = defaultdict(list)

    @staticmethod
    def shingles(text: str, k: int = 5, limit: int = 4000) -> set[int]:
        w = re.findall(r"\w+", text.casefold())[:limit]
        return {int(hashlib.md5(" ".join(w[i:i + k]).encode()).hexdigest()[:12], 16) for i in range(max(1, len(w) - k + 1))}

    def is_dup(self, host: str, text: str) -> bool:
        s = self.shingles(text)
        for prev in self.by_host[host]:
            inter = len(s & prev)
            if inter and inter / len(s | prev) >= self.threshold:
                return True
        self.by_host[host].append(s)
        return False


class NoiseStats(Counter):
    """Counts per gate (skipped_url, blocked_domain, thin, near_duplicate, generic_entity)."""
