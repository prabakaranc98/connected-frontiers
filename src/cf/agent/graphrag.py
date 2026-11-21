"""Graph-aware retrieval (HippoRAG-style): query → seed entities → personalized PageRank over the KG
→ rank passages by the PPR mass of the entities they mention, blended with BM25 → passages + the
edges they support. Every passage keeps its URL, so answers cite documents and edges together.
"""

from __future__ import annotations

import re

from cf.agent.kg import KG
from cf.crawl.noise import is_generic
from cf.docs import DocIndex


class GraphRAG:
    def __init__(self, kg: KG | None = None, idx: DocIndex | None = None):
        self.kg = kg or KG()
        self.idx = idx or DocIndex()

    def seeds(self, query: str, k: int = 6) -> list[str]:
        words = re.findall(r"[\w.+-]+", query)
        found: dict[str, float] = {}
        for n in (4, 3, 2, 1):                       # longest n-grams first
            for i in range(len(words) - n + 1):
                gram = " ".join(words[i:i + n])
                if len(gram) < 3:
                    continue
                m = self.kg.match(gram, k=1)
                if m and m[0][0] >= 0.95 and m[0][1] not in found and not is_generic(self.kg.name(m[0][1])):
                    found[m[0][1]] = m[0][0] * n
        return [e for e, _ in sorted(found.items(), key=lambda x: -x[1])][:k]

    def retrieve(self, query: str, k: int = 8, alpha: float = 0.6) -> dict:
        seeds = self.seeds(query)
        bm = self.idx.bm25(query, k=60)
        if not seeds:                                # fall back: entities in the best text matches
            seeds = sorted({e for _, c in bm[:5] for e in self.idx.chunk_entities.get(c, ())})[:6]
        ppr = {r["id"]: r["score"] for r in self.kg.ppr(seeds, k=300)} if seeds else {}
        for s in seeds:
            ppr[s] = max(ppr.values(), default=1.0)
        cands = {c for e in list(ppr)[:150] for c in self.idx.entity_chunks.get(e, [])} | {c for _, c in bm}
        bm_s = {c: s for s, c in bm}
        bmax = max(bm_s.values(), default=1.0) or 1.0
        g = {c: sum(ppr.get(e, 0.0) for e in self.idx.chunk_entities.get(c, ())) for c in cands}
        gmax = max(g.values(), default=1.0) or 1.0
        scored = sorted(((alpha * g[c] / gmax + (1 - alpha) * bm_s.get(c, 0.0) / bmax, c) for c in cands), reverse=True)[:k]
        passages = [{**self.idx.passage(c, 900), "score": round(s, 3)} for s, c in scored]
        chosen = {c for _, c in scored}
        rank = {c: i for i, (_, c) in enumerate(scored)}            # edges from better passages first
        cand = [(min(rank[c] for c in chosen & set(cs)), e) for e, cs in self.idx.edge_chunks.items()
                if e in self.kg.edges and chosen & set(cs) and self.kg.edges[e]["status"] != "unsupported"]
        seed_set = set(seeds)
        cand.sort(key=lambda x: (x[0], -(self.kg.edges[x[1]]["head"] in seed_set or self.kg.edges[x[1]]["tail"] in seed_set),
                                 -self.kg.edges[x[1]]["strength"]))
        edges = [self.kg._edge_view(self.kg.edges[e]) for _, e in cand[:25]]
        return {"seeds": [self.kg.name(s) for s in seeds], "passages": passages, "edges": edges}

    def documents(self, entity_id: str, k: int = 8) -> list[dict]:
        cs = self.idx.entity_chunks.get(entity_id, [])
        seen, out = set(), []
        for c in cs:
            ch = self.idx.chunks.get(c)
            if ch and ch["doc_id"] not in seen:
                seen.add(ch["doc_id"])
                d = self.idx.docs.get(ch["doc_id"], {})
                out.append({"doc_id": ch["doc_id"], "title": d.get("title"), "url": ch["url"], "chunk_id": c,
                            "snippet": ch["text"][:240]})
            if len(out) >= k:
                break
        return out
