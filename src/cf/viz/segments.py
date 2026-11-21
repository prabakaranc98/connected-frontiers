"""Short, grounded names for graph segments (Louvain communities), written by a cheap LLM from
the segment's top members only. Falls back to 'top member · top member' without a model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from cf.llm.client import LLM


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SegName(_Strict):
    id: int
    name: str


class SegNames(_Strict):
    names: list[SegName]


SYSTEM = """You name clusters of an AI-ecosystem knowledge graph. Each cluster lists its most central members with their
types. Give each cluster a 2-4 word name that describes what the members have in common, based ONLY on the list
(e.g. "Inference clouds", "Legal AI agents", "Post-training methods", "AI safety evals").
Use a company name only if the cluster is clearly about one company's products and customers (e.g. "Harvey & law firms").
Return one name per cluster id."""


def name_segments(graph: dict, model: str | None, k: int = 15) -> dict:
    ents = {e["id"]: e for e in graph["entities"]}
    comms = graph.get("communities", [])
    members: dict[int, list[dict]] = {}
    for e in graph["entities"]:
        members.setdefault(e.get("community", -1), []).append(e)
    for c in comms:
        c["name"] = " · ".join(c["top"][:2])
    if not model or not comms:
        return graph
    lines = []
    for c in comms:
        top = sorted(members.get(c["id"], []), key=lambda e: -(e.get("pagerank") or 0))[:k]
        lines.append(f"cluster {c['id']} ({c['size']} members): " + "; ".join(f"{e['name']} [{e['type']}]" for e in top))
    try:
        out = LLM(model).parse(SYSTEM, "\n".join(lines), SegNames, "segment_names",
                               max_tokens=1500, reasoning_max_tokens=0)
        by = {n.id: n.name.strip() for n in out.names}
        for c in comms:
            if by.get(c["id"]):
                c["name"] = by[c["id"]][:40]
    except RuntimeError:
        pass
    _ = ents
    return graph
