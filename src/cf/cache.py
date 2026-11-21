"""Stage caches (content-addressed) and cache status.

  fetch    url → raw page sha256                      (data/raw, see cf.crawl.fetch)
  extract  sha + extractor version + prompt hash      (data/interim/extract)
  verify   extract key + verifier version + prompt    (data/interim/verify)

Changing the verifier re-runs verification only; changing the extractor re-runs both; an unchanged
page is never paid for twice. Each record carries created_at, so freshness is visible.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import Counter, defaultdict
from datetime import UTC, datetime
from urllib.parse import urlparse

from cf import config
from cf.extract.llm import (
    EXTRACT_SYSTEM,
    VERIFY_SYSTEM,
    Extraction,
    Verdict,
    XEntity,
    XTriple,
)

EXTRACT = config.DATA / "interim" / "extract"
VERIFY = config.DATA / "interim" / "verify"
LEGACY = config.DATA / "interim" / "extractions"      # combined cache used before the split


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:24]


def extract_key(sha: str, ex) -> str:
    return _h(f"{sha}|{ex.version}|{_h(EXTRACT_SYSTEM)}")


def verify_key(ekey: str, ve) -> str:
    return _h(f"{ekey}|{ve.version}|{_h(VERIFY_SYSTEM)}")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def get_extraction(page, ex) -> tuple[Extraction, str, bool]:
    key = extract_key(page.raw_sha256, ex)
    f = EXTRACT / f"{key}.json"
    if f.exists():
        d = json.loads(f.read_text())
        return (Extraction([XEntity(**e) for e in d["entities"]], [XTriple(**t) for t in d["triples"]],
                           d["dropped_unquoted"]), key, True)
    ext = ex.extract(page)
    EXTRACT.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"url": page.url, "sha": page.raw_sha256, "extractor": ex.version,
                             "prompt": _h(EXTRACT_SYSTEM), "created_at": _now(),
                             "entities": [e.model_dump() for e in ext.entities],
                             "triples": [t.model_dump() for t in ext.triples],
                             "dropped_unquoted": ext.dropped_unquoted}, indent=1))
    return ext, key, False


def _triples_sha(ext: Extraction) -> str:
    return _h(json.dumps([t.model_dump() for t in ext.triples], sort_keys=True))


def get_verdicts(page, ext: Extraction, ekey: str, ve) -> tuple[list[Verdict | None], bool]:
    key = verify_key(ekey, ve)
    f = VERIFY / f"{key}.json"
    if f.exists():
        d = json.loads(f.read_text())
        verdicts = [Verdict(**v) if v else None for v in d["verdicts"]]
        # self-validating: verdicts must belong to exactly these triples, else re-verify
        if len(verdicts) == len(ext.triples) and d.get("triples_sha", _triples_sha(ext)) == _triples_sha(ext):
            return verdicts, True
    verdicts = ve.verify(ext.triples, page)
    VERIFY.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"url": page.url, "extract_key": ekey, "verifier": ve.version,
                             "prompt": _h(VERIFY_SYSTEM), "created_at": _now(), "triples_sha": _triples_sha(ext),
                             "verdicts": [v.model_dump() if v else None for v in verdicts]}, indent=1))
    return verdicts, False


_KEY_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)
_KEY_LOCKS_GUARD = threading.Lock()


def extract_verify(page, ex, ve):
    """Per-content-key lock: identical pages under different URLs are never processed concurrently."""
    key = extract_key(page.raw_sha256, ex)
    with _KEY_LOCKS_GUARD:
        lock = _KEY_LOCKS[key]
    with lock:
        ext, ekey, _ = get_extraction(page, ex)
        verdicts, _ = get_verdicts(page, ext, ekey, ve)
    return ext, verdicts


def known_urls() -> list[str]:
    urls = [json.loads(f.read_text())["url"] for f in sorted(EXTRACT.glob("*.json"))]
    if LEGACY.exists():
        urls += [json.loads(f.read_text())["url"] for f in sorted(LEGACY.glob("*.json"))]
    return list(dict.fromkeys(urls))


def migrate_legacy(ex) -> int:
    """Copy the newest legacy extraction per URL into the extract cache under the current key.
    Valid because the extract prompt and extractor have not changed since those were written
    (checked: same extractor version; the prompt has been unchanged since round 1)."""
    if not LEGACY.exists():
        return 0
    newest: dict[str, tuple[float, dict]] = {}
    for f in LEGACY.glob("*.json"):
        d = json.loads(f.read_text())
        if d.get("extractor") != ex.version:
            continue
        if d["url"] not in newest or f.stat().st_mtime > newest[d["url"]][0]:
            newest[d["url"]] = (f.stat().st_mtime, d)
    n = 0
    EXTRACT.mkdir(parents=True, exist_ok=True)
    for _, d in newest.values():
        key = extract_key(d["sha"], ex)
        target = EXTRACT / f"{key}.json"
        if target.exists():
            continue
        target.write_text(json.dumps({"url": d["url"], "sha": d["sha"], "extractor": d["extractor"],
                                      "prompt": _h(EXTRACT_SYSTEM), "created_at": _now(), "migrated": True,
                                      "entities": d["entities"], "triples": d["triples"],
                                      "dropped_unquoted": d["dropped_unquoted"]}, indent=1))
        n += 1
    return n


def status(ex, ve, cost_per_page: float = 0.0025) -> dict:
    """What is cached, how fresh, and what is stale for the CURRENT extractor/verifier/prompts."""
    raw_index = config.DATA / "raw" / "index.jsonl"
    fetched: dict[str, str] = {}
    if raw_index.exists():
        for line in raw_index.read_text().split("\n"):
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("sha"):
                fetched[r["url"]] = r["fetched_at"]
    ex_recs = [json.loads(f.read_text()) for f in EXTRACT.glob("*.json")] if EXTRACT.exists() else []
    vf_recs = [json.loads(f.read_text()) for f in VERIFY.glob("*.json")] if VERIFY.exists() else []
    cur_ex = {r["url"] for r in ex_recs if r["extractor"] == ex.version and r["prompt"] == _h(EXTRACT_SYSTEM)}
    cur_vf = {r["url"] for r in vf_recs if r["verifier"] == ve.version and r["prompt"] == _h(VERIFY_SYSTEM)}
    urls = set(known_urls())
    ages = sorted(fetched[u] for u in urls if u in fetched)
    now = datetime.now(UTC)
    age_days = [(now - datetime.fromisoformat(a)).days for a in ages]
    return {
        "pages_known": len(urls), "raw_pages_fetched": len(fetched),
        "publishers_top": Counter(urlparse(u).netloc.removeprefix("www.") for u in urls).most_common(12),
        "extract_current": len(cur_ex & urls), "extract_stale_or_missing": len(urls - cur_ex),
        "verify_current": len(cur_vf & urls), "verify_stale_or_missing": len(urls - cur_vf),
        "oldest_fetch": ages[0] if ages else None, "newest_fetch": ages[-1] if ages else None,
        "pages_older_than_30d": sum(1 for a in age_days if a > 30),
        "refresh_cost_estimate_usd": round((len(urls - cur_ex) * cost_per_page)
                                           + (len((urls & cur_ex) - cur_vf) * cost_per_page * 0.2), 3),
    }
