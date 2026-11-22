"""KG tools for agents, over a built graph snapshot (data/processed/graph/graph.json).

Each tool returns compact JSON (ids, names, edge ids, evidence status), so agents can cite edge ids
and graders can check them.
"""

from __future__ import annotations

import heapq
import itertools
import json
from pathlib import Path

import networkx as nx
from rapidfuzz import fuzz

from cf import config
from cf.resolve.er import normalize

GRAPH = config.DATA / "processed" / "graph" / "graph.json"   # fallback when no KB version exists
ST = ["unsupported", "claimed", "confirmed", "corroborated", "verified"]


class KG:
    def __init__(self, path: Path | None = None, version: str | None = None):
        from cf import kb
        self.kb_version = version or kb.current()
        g = json.loads(Path(path or kb.graph_path(version)).read_text())
        self.g = g
        self.ents = {e["id"]: e for e in g["entities"]}
        self.edges = {e["id"]: e for e in g["edges"]}
        self.adj: dict[str, list[str]] = {}
        for e in g["edges"]:
            self.adj.setdefault(e["head"], []).append(e["id"])
            self.adj.setdefault(e["tail"], []).append(e["id"])
        self.comms = {c["id"]: c for c in g.get("communities", [])}
        self._names = [(normalize(a, e["type"]), e["id"]) for e in g["entities"] for a in {e["name"], *e.get("aliases", [])}]
        self._exact: dict[tuple[str, str], set[str]] = {}         # (type, normalized name) → ids: O(1) exact hits
        for n, eid in self._names:
            self._exact.setdefault((self.ents[eid]["type"], n), set()).add(eid)
        self._types = sorted({e["type"] for e in g["entities"]})
        self.empty_hints = False              # harness switch: say what DOES exist when a query finds nothing
        self.truncation_notice = False        # harness switch: say how many edges a list left out
        self.neighbor_limit = 25
        self._nx = None

    # ---- helpers --------------------------------------------------------------------------
    def name(self, eid: str) -> str:
        return self.ents[eid]["name"] if eid in self.ents else eid

    def exact(self, text: str, etype: str | None = None) -> str | None:
        """O(1) exact (normalized) name lookup, no fuzzy fallback; best-ranked hit or None."""
        hits = {eid for t in ([etype] if etype else self._types) for eid in self._exact.get((t, normalize(text, t)), ())}
        if not hits:
            return None
        pref = {"org": 3, "model": 2, "method": 2, "benchmark": 2, "technology": 1}
        return max(hits, key=lambda h: (pref.get(self.ents[h]["type"], 0), self.ents[h].get("pagerank") or 0))

    def match(self, text: str, k: int = 5, etype: str | None = None, exact_first: bool = False) -> list[tuple[float, str]]:
        """Fuzzy name → entity. The query is normalized the same way as each candidate's type;
        exact > substring (weighted by length overlap) > fuzzy; ties broken by type and PageRank.
        exact_first: return exact hits without the fuzzy scan (seed linking, answer scoring)."""
        raw = (text or "").casefold().strip()
        if not raw:
            return []
        if exact_first:
            hits = {eid for t in ([etype] if etype else self._types) for eid in self._exact.get((t, normalize(text, t)), ())}
            if hits:
                pref = {"org": 3, "model": 2, "method": 2, "benchmark": 2, "technology": 1}
                return sorted(((1.0, h) for h in hits), key=lambda x: (-pref.get(self.ents[x[1]]["type"], 0),
                                                                     -(self.ents[x[1]].get("pagerank") or 0)))[:k]
        qn_by_type: dict[str, str] = {}
        best: dict[str, float] = {}
        for n, eid in self._names:
            t = self.ents[eid]["type"]
            if etype and t != etype:
                continue
            q = qn_by_type.setdefault(t, normalize(text, t))
            if not q:
                continue
            if n == q or self.ents[eid]["name"].casefold() == raw:
                s = 1.0
            elif len(q) >= 4 and (f" {q} " in f" {n} " or f" {n} " in f" {q} "):
                s = 0.55 + 0.35 * min(len(q), len(n)) / max(len(q), len(n))
            else:
                s = fuzz.ratio(q, n) / 100 * 0.75             # rapidfuzz (C): same Indel ratio as difflib
            if s > best.get(eid, 0):
                best[eid] = s
        pref = {"org": 3, "model": 2, "method": 2, "benchmark": 2, "technology": 1}
        ranked = sorted(((s, eid) for eid, s in best.items() if s >= 0.5),
                        key=lambda x: (-round(x[0], 2), -pref.get(self.ents[x[1]]["type"], 0),
                                       -(self.ents[x[1]].get("pagerank") or 0)))
        return ranked[:k]

    def _graph(self) -> nx.Graph:
        if self._nx is None:
            g = nx.Graph()
            for e in self.g["edges"]:
                if e["status"] == "unsupported":
                    continue
                w = max(0.05, e["strength"])
                prev = g.get_edge_data(e["head"], e["tail"], {}).get("weight", 0)
                g.add_edge(e["head"], e["tail"], weight=prev + w)
            self._nx = g
        return self._nx

    def _edge_view(self, e: dict, focus: str | None = None) -> dict:
        d = {"edge_id": e["id"], "head": self.name(e["head"]), "relation": e["relation"], "tail": self.name(e["tail"]),
             "status": e["status"], "strength": e["strength"]}
        if e.get("attrs"):
            d["attrs"] = e["attrs"]
        if focus:
            d["other_id"] = e["tail"] if e["head"] == focus else e["head"]
        return d

    # ---- tools ------------------------------------------------------------------------------
    def find_entity(self, name: str, type: str | None = None, k: int = 5) -> list[dict]:
        return [{"id": eid, "name": self.name(eid), "type": self.ents[eid]["type"], "match": round(s, 2),
                 "ppr": round(self.ents[eid].get("ppr") or 0, 4)} for s, eid in self.match(name, k, type)]

    def neighbors(self, id: str, relation: str | None = None, direction: str = "both",
                  min_status: str = "claimed", limit: int | None = None) -> list[dict]:
        if id not in self.ents:
            return [{"error": f"unknown id {id}; use find_entity first"}]
        lo = ST.index(min_status) if min_status in ST else 1
        out = []
        for eid in self.adj.get(id, []):
            e = self.edges[eid]
            if ST.index(e["status"]) < lo or (relation and e["relation"] != relation):
                continue
            if direction == "out" and e["head"] != id or direction == "in" and e["tail"] != id:
                continue
            out.append(self._edge_view(e, focus=id))
        limit = limit or self.neighbor_limit
        res = sorted(out, key=lambda x: -x["strength"])[:limit]
        if self.truncation_notice and len(out) > limit:
            res.append({"note": f"{len(out) - limit} more edges not shown; raise limit or filter by relation",
                        "relations_here": self.relations_at(id)})
        if self.empty_hints and not out:
            res.append({"note": "no edges match", "relations_here": self.relations_at(id)})
        return res

    def relations_at(self, id: str) -> list[str]:
        """What exists at a node: 'direction relation → other type (count)', for recovering from empty queries."""
        c: dict[str, int] = {}
        for eid in self.adj.get(id, []):
            e = self.edges[eid]
            if e["status"] == "unsupported":
                continue
            d, other = ("out", e["tail"]) if e["head"] == id else ("in", e["head"])
            k = f"{d} {e['relation']} → {self.ents[other]['type']}"
            c[k] = c.get(k, 0) + 1
        return [f"{k} ({n})" for k, n in sorted(c.items(), key=lambda x: -x[1])][:15]

    def schema_card(self) -> str:
        """The KB's relation vocabulary: which relation connects which entity types (for the system prompt)."""
        c: dict[str, int] = {}
        for e in self.edges.values():
            if e["status"] != "unsupported":
                k = f"{self.ents[e['head']]['type']} —{e['relation']}→ {self.ents[e['tail']]['type']}"
                c[k] = c.get(k, 0) + 1
        top = sorted(c.items(), key=lambda x: -x[1])[:30]
        return "Relations in this knowledge graph (count):\n" + "\n".join(f"- {k} ({n})" for k, n in top)

    def evidence(self, edge_id: str) -> dict:
        e = self.edges.get(edge_id)
        if not e:
            return {"error": f"unknown edge {edge_id}"}
        return {**self._edge_view(e), "why": e.get("grade_reasons", []),
                "citations": [{"quote": v["quote"][:240], "url": v["source_url"], "publisher": v["publisher"],
                               "source_kind": v["source_kind"], "verifier": v["entailed"]} for v in e["evidence"][:3]]}

    def graph_query(self, start: str, path: list[dict], min_status: str = "claimed", limit: int = 40) -> dict:
        """Execute a typed path pattern from one entity: each step is {relation?, direction?, type?}.
        Returns the entities reached at the last step, with the edge ids on the way (for citations), how
        many previous-step entities reach each one (n_sources) and its in-degree for that relation over
        the whole KB (global_in), so rarity questions ("used by no other org") need no extra calls."""
        sid = start if start in self.ents else None
        if not sid:
            m = self.match(start, k=1)
            if not m or m[0][0] < 0.75:
                return {"error": f"unknown start {start!r}; use find_entity"}
            sid = m[0][1]
        if not isinstance(path, list) or not path or len(path) > 4:
            return {"error": "path must be a list of 1-4 steps like {'relation': 'uses_method', 'direction': 'out'}"}
        lo = ST.index(min_status) if min_status in ST else 1
        frontier: dict[str, list[str]] = {sid: []}
        counts = []
        last_rel = None
        reach: dict[str, set[str]] = {}
        for step in path:
            rel, d, typ = step.get("relation"), step.get("direction", "both"), step.get("type")
            nxt: dict[str, list[str]] = {}
            reach = {}
            for node, via in itertools.islice(frontier.items(), 300):
                for eid in self.adj.get(node, []):
                    e = self.edges[eid]
                    if ST.index(e["status"]) < lo or (rel and e["relation"] != rel):
                        continue
                    if e["head"] == node and d in ("out", "both"):
                        other = e["tail"]
                    elif e["tail"] == node and d in ("in", "both"):
                        other = e["head"]
                    else:
                        continue
                    if other == sid or (typ and self.ents[other]["type"] != typ):
                        continue
                    nxt.setdefault(other, via + [eid])
                    reach.setdefault(other, set()).add(node)
            if not nxt and self.empty_hints:                 # say what exists, so the model can repair the path
                return {"start": {"id": sid, "name": self.name(sid)}, "per_step_counts": counts + [0], "results": [],
                        "note": f"step {len(counts) + 1} {step} matched nothing",
                        "relations_at_previous_step": {self.name(n): self.relations_at(n) for n in list(frontier)[:3]}}
            frontier, last_rel = nxt, rel
            counts.append(len(frontier))
            if not frontier:
                break
        res = []
        for other, via in frontier.items():
            g_in = sum(1 for x in self.adj.get(other, []) if self.edges[x]["tail"] == other
                       and (not last_rel or self.edges[x]["relation"] == last_rel) and ST.index(self.edges[x]["status"]) >= lo)
            res.append({"id": other, "name": self.name(other), "type": self.ents[other]["type"], "via_edge_ids": via,
                        "n_sources": len(reach.get(other, ())), "global_in": g_in})
        res.sort(key=lambda r: (-r["n_sources"], -(self.ents[r["id"]].get("pagerank") or 0)))
        return {"start": {"id": sid, "name": self.name(sid)}, "per_step_counts": counts,
                "results": res[:limit], "truncated": len(res) > limit}

    def ppr(self, seed_ids: list[str], k: int = 15, type: str | None = None) -> list[dict]:
        g = self._graph()
        seeds = [s for s in seed_ids if s in g]
        if not seeds:
            return [{"error": "no valid seed ids"}]
        pr = nx.pagerank(g, alpha=0.85, weight="weight", personalization={s: 1.0 for s in seeds})
        ranked = [(v, n) for n, v in pr.items() if n not in seeds and (not type or self.ents[n]["type"] == type)]
        return [{"id": n, "name": self.name(n), "type": self.ents[n]["type"], "score": round(v, 5)}
                for v, n in heapq.nlargest(k, ranked)]

    def paths(self, a: str, b: str, max_paths: int = 3) -> list[dict]:
        g = self._graph()
        if a not in g or b not in g:
            return [{"error": "unknown id(s)"}]
        cost = nx.Graph()
        for u, v, d in g.edges(data=True):
            cost.add_edge(u, v, c=1 + 2 * (1 - min(1.0, d["weight"])))
        out = []
        try:
            for p in nx.shortest_simple_paths(cost, a, b, weight="c"):
                steps = []
                for u, v in itertools.pairwise(p):
                    cands = [self.edges[x] for x in self.adj.get(u, []) if {self.edges[x]["head"], self.edges[x]["tail"]} == {u, v}]
                    best = max(cands, key=lambda e: e["strength"]) if cands else None
                    steps.append(self._edge_view(best) if best else {"head": self.name(u), "tail": self.name(v)})
                out.append({"hops": len(p) - 1, "steps": steps})
                if len(out) >= max_paths or len(p) > 6:
                    break
        except nx.NetworkXNoPath:
            return [{"error": "no path"}]
        return out

    # ---- document tools (GraphRAG) ---------------------------------------------------------
    @property
    def rag(self):
        if getattr(self, "_rag", None) is None:
            from cf.agent.graphrag import GraphRAG
            self._rag = GraphRAG(self)
        return self._rag

    def search_text(self, query: str, k: int = 6) -> dict:
        """Graph-aware passage retrieval: PPR over entities in the query + BM25."""
        r = self.rag.retrieve(query, k=k)
        return {"seed_entities": r["seeds"],
                "passages": [{"chunk_id": p["chunk_id"], "title": p.get("title"), "url": p["url"], "score": p["score"],
                              "text": p["text"][:600]} for p in r["passages"]],
                "supporting_edges": r["edges"][:10]}

    def documents(self, id: str, k: int = 8) -> list[dict]:
        return self.rag.documents(id, k) if id in self.ents else [{"error": f"unknown id {id}"}]

    def passage(self, chunk_id: str) -> dict:
        return self.rag.idx.passage(chunk_id)

    def segment(self, id: str, k: int = 12) -> dict:
        e = self.ents.get(id)
        if not e:                                      # also accept a segment name
            from rapidfuzz import fuzz
            best = max(self.comms.values(), key=lambda c: fuzz.token_set_ratio(id.lower(), (c.get("name") or "").lower()),
                       default=None)
            if not best or fuzz.token_set_ratio(id.lower(), (best.get("name") or "").lower()) < 70:
                return {"error": f"unknown entity id or segment name {id}"}
            e = {"community": best["id"]}
        c = self.comms.get(e.get("community"))
        members = sorted((x for x in self.ents.values() if x.get("community") == e.get("community")),
                         key=lambda x: -(x.get("pagerank") or 0))[:k]
        return {"segment": c["name"] if c else None, "size": c["size"] if c else None,
                "top_members": [{"id": m["id"], "name": m["name"], "type": m["type"]} for m in members]}


TOOL_SPECS = [
    {"type": "function", "function": {"name": "find_entity", "description": "Find entities by name (fuzzy). Returns ids to use with other tools.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string", "description": "optional: org, model, method, benchmark, technology, problem, paper, dataset, role, skill"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "neighbors", "description": "Edges around an entity, strongest first. Each has edge_id, relation, other entity, evidence status.",
     "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "relation": {"type": "string"}, "direction": {"type": "string", "enum": ["both", "out", "in"]},
                    "min_status": {"type": "string", "enum": ST}, "limit": {"type": "integer"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "evidence", "description": "Quotes, source URLs and grading reasons behind one edge.",
     "parameters": {"type": "object", "properties": {"edge_id": {"type": "string"}}, "required": ["edge_id"]}}},
    {"type": "function", "function": {"name": "graph_query", "description": "Run a multi-hop typed path query in one call. "
     "Example: orgs working on a problem and the methods they use: start='problem:x', path=[{'relation':'works_on','direction':'in','type':'org'},"
     "{'relation':'uses_method','direction':'out'}]. Results carry via_edge_ids (cite them), n_sources (how many previous-step entities reach it) "
     "and global_in (its in-degree for that relation in the whole KB).",
     "parameters": {"type": "object", "properties": {"start": {"type": "string", "description": "entity id (or exact name)"},
                    "path": {"type": "array", "items": {"type": "object", "properties": {"relation": {"type": "string"},
                             "direction": {"type": "string", "enum": ["out", "in", "both"]}, "type": {"type": "string"}}}},
                    "min_status": {"type": "string", "enum": ST}, "limit": {"type": "integer"}}, "required": ["start", "path"]}}},
    {"type": "function", "function": {"name": "ppr", "description": "Personalized PageRank: entities most strongly connected to the given seed ids, optionally of one type.",
     "parameters": {"type": "object", "properties": {"seed_ids": {"type": "array", "items": {"type": "string"}}, "k": {"type": "integer"}, "type": {"type": "string"}}, "required": ["seed_ids"]}}},
    {"type": "function", "function": {"name": "paths", "description": "Strongest evidence paths between two entity ids.",
     "parameters": {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]}}},
    {"type": "function", "function": {"name": "segment", "description": "A named segment (cluster) with its top members by PageRank. Pass an entity id (its segment) or a segment name.",
     "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "search_text", "description": "Graph-aware search over source documents: returns passages (with URLs) ranked by entity PageRank + text match, and the edges they support.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "documents", "description": "Source documents (title, URL, snippet, chunk_id) that mention an entity id.",
     "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "k": {"type": "integer"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "passage", "description": "Full text of one passage by chunk_id.",
     "parameters": {"type": "object", "properties": {"chunk_id": {"type": "string"}}, "required": ["chunk_id"]}}},
]

# graph_query is its own condition: kept out of kg_tools so the two retrieval modes stay comparable
_ALL_SPECS = TOOL_SPECS
TOOL_SPECS = [t for t in _ALL_SPECS if t["function"]["name"] != "graph_query"]
QUERY_SPECS = [t for t in _ALL_SPECS if t["function"]["name"] in ("find_entity", "graph_query", "evidence", "segment")]
