"""KG tools for agents, over a built graph snapshot (data/processed/graph/graph.json).

Each tool returns compact JSON (ids, names, edge ids, evidence status), so agents can cite edge ids
and graders can check them.
"""

from __future__ import annotations

import heapq
import itertools
import json
from difflib import SequenceMatcher
from pathlib import Path

import networkx as nx

from cf import config
from cf.resolve.er import normalize

GRAPH = config.DATA / "processed" / "graph" / "graph.json"
ST = ["unsupported", "claimed", "confirmed", "corroborated", "verified"]


class KG:
    def __init__(self, path: Path = GRAPH):
        g = json.loads(Path(path).read_text())
        self.g = g
        self.ents = {e["id"]: e for e in g["entities"]}
        self.edges = {e["id"]: e for e in g["edges"]}
        self.adj: dict[str, list[str]] = {}
        for e in g["edges"]:
            self.adj.setdefault(e["head"], []).append(e["id"])
            self.adj.setdefault(e["tail"], []).append(e["id"])
        self.comms = {c["id"]: c for c in g.get("communities", [])}
        self._names = [(normalize(a, e["type"]), e["id"]) for e in g["entities"] for a in {e["name"], *e.get("aliases", [])}]
        self._nx = None

    # ---- helpers --------------------------------------------------------------------------
    def name(self, eid: str) -> str:
        return self.ents[eid]["name"] if eid in self.ents else eid

    def match(self, text: str, k: int = 5, etype: str | None = None) -> list[tuple[float, str]]:
        """Fuzzy name → entity. The query is normalized the same way as each candidate's type;
        exact > substring (weighted by length overlap) > fuzzy; ties broken by type and PageRank."""
        raw = (text or "").casefold().strip()
        if not raw:
            return []
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
                s = SequenceMatcher(None, q, n).ratio() * 0.75
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
                  min_status: str = "claimed", limit: int = 25) -> list[dict]:
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
        return sorted(out, key=lambda x: -x["strength"])[:limit]

    def evidence(self, edge_id: str) -> dict:
        e = self.edges.get(edge_id)
        if not e:
            return {"error": f"unknown edge {edge_id}"}
        return {**self._edge_view(e), "why": e.get("grade_reasons", []),
                "citations": [{"quote": v["quote"][:240], "url": v["source_url"], "publisher": v["publisher"],
                               "source_kind": v["source_kind"], "verifier": v["entailed"]} for v in e["evidence"][:3]]}

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

    def segment(self, id: str, k: int = 12) -> dict:
        e = self.ents.get(id)
        if not e:
            return {"error": f"unknown id {id}"}
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
    {"type": "function", "function": {"name": "ppr", "description": "Personalized PageRank: entities most strongly connected to the given seed ids, optionally of one type.",
     "parameters": {"type": "object", "properties": {"seed_ids": {"type": "array", "items": {"type": "string"}}, "k": {"type": "integer"}, "type": {"type": "string"}}, "required": ["seed_ids"]}}},
    {"type": "function", "function": {"name": "paths", "description": "Strongest evidence paths between two entity ids.",
     "parameters": {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]}}},
    {"type": "function", "function": {"name": "segment", "description": "The named segment (cluster) an entity belongs to, with its top members.",
     "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
]
