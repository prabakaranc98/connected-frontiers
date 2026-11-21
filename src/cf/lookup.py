"""Dynamic lookup: answer from the KG when the entity is known and fresh; otherwise fetch, extract,
verify and grade on demand. Live results land in the stage caches, so the next `cf build` includes
them. This is also the hook for an agent's request_crawl.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from cf.agent.kg import GRAPH, KG
from cf.cache import extract_verify
from cf.crawl.fetch import Fetcher, registrable
from cf.crawl.sources import homepage, same_site_candidates
from cf.extract.llm import LLMExtractor, make_verifier
from cf.graph.build import GraphBuilder
from cf.llm.client import LLM, role_chain


def _age_days(iso: str) -> int:
    return (datetime.now(UTC) - datetime.fromisoformat(iso)).days


def lookup(query: str, pages: int = 3, refresh: bool = False, max_age_days: int = 30) -> dict:
    t0, spend0 = time.time(), LLM.spent_usd
    kg = KG() if GRAPH.exists() else None
    q = query.strip()
    is_url = "." in q and " " not in q
    ent = None
    if kg and not is_url:
        m = kg.match(q, k=1)
        ent = kg.ents[m[0][1]] if m and m[0][0] >= 0.75 else None

    # 1) known and fresh → answer from the KG
    if ent and not refresh:
        edges = sorted((kg.edges[e] for e in kg.adj.get(ent["id"], [])), key=lambda e: -e["strength"])
        newest = max((v["observed_at"] for e in edges for v in e["evidence"]), default=None)
        if newest and _age_days(newest) <= max_age_days:
            return {"source": "kg (cached)", "entity": ent["name"], "type": ent["type"], "newest_evidence": newest[:10],
                    "edges": [kg._edge_view(e) | {"quote": e["evidence"][0]["quote"][:140]} for e in edges[:25]],
                    "seconds": round(time.time() - t0, 2), "cost_usd": 0.0}

    # 2) unknown or stale → live fetch → extract → verify → grade
    if is_url:
        start = q if q.startswith("http") else f"https://{q}"
    elif ent and ent.get("domain"):
        start = homepage(ent["domain"])
    else:
        return {"source": "none", "entity": ent["name"] if ent else None,
                "hint": "not in the KG and no known site; pass a URL or domain, e.g. `cf lookup example.ai`"}
    fetcher = Fetcher()
    first = fetcher.fetch(start)
    if first is None:
        return {"source": "none", "hint": f"could not fetch {start} (robots/403/non-HTML; see data/raw/index.jsonl)"}
    urls = [start] + same_site_candidates(first, k=max(0, pages - 1))
    ex, ve = LLMExtractor(role_chain("extract")[0]), make_verifier()
    gb = GraphBuilder()
    read = []
    for u in dict.fromkeys(urls):
        p = fetcher.fetch(u)
        if p is None or len(p.text) < 200:
            continue
        ext, verdicts = extract_verify(p, ex, ve)
        gb.add_page(p, ext, verdicts, ex.version, ve.version)
        read.append(u)
    gb.finalize()
    site = registrable(start)
    edges = sorted(gb.edges.values(), key=lambda e: -e.strength)
    return {"source": "live (fetched now; cached for the next build)", "site": site, "pages": read,
            "edges": [{"head": gb.entities[e.head]["name"], "relation": e.relation.value, "tail": gb.entities[e.tail]["name"],
                       "status": e.status.value, "strength": e.strength, "quote": e.evidence[0].quote[:140]} for e in edges[:40]],
            "n_edges": len(edges), "seconds": round(time.time() - t0, 1), "cost_usd": round(LLM.spent_usd - spend0, 4)}
