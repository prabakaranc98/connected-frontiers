"""Stage-wise evaluation of retrieval, grounding and use, per question, against question-aware gold.

The earlier "salient" reference (an anchor's strongest edges, whatever was asked) could not tell good retrieval from
bad: for Harvey it was the law firms that use it, while the question asked about systems and methods. Here each
question names the graph facts that answer it (a gold spec), and every condition is scored on the same stages:

  retrieved   gold entities that reached the model's context (tool results, or the packed RAG context)
  grounded    gold entities the model wrote into its findings with cited edges (agentic harnesses only)
  used        gold entities named in the final answer
  utilisation used / retrieved: how much of what was found survives into the advice
  precision   share of retrieved entities that are gold (how focused retrieval is)
  doubt       phrases that mark a claim as unverified / not in evidence (false doubt when the fact is well known)

Gold specs (in the question config):
  {anchor, relations: [..], direction: in|out|both}      edges at one entity
  {start, path: [...]}                                    a typed multi-hop path (graph_query semantics)
  {top: {relation, direction, type, k}}                   the k most-connected targets and their edges
"""

from __future__ import annotations

import re

from cf.agent.kg import KG
from cf.bench import guidance as G

CAP = 30
# counted as doubt: calling a claim unverified. "Not covered by the evidence" is the correct wording and is not counted.
_DOUBT = re.compile(r"\bunverified\b|\bnot (?:evidenced|verified)\b|\bno evidence (?:for|that)\b", re.IGNORECASE)


def gold(kg: KG, specs: list[dict]) -> dict:
    """{edges, entities, anchors}. For anchor and path specs the gold entities are the far ends of the gold edges;
    for a `top` spec they are the ranked targets themselves (the answer should name the bases, not every derivative)."""
    edges: list[str] = []
    ents: set[str] = set()
    anchors = {sp.get("anchor") or sp.get("start") for sp in specs if sp.get("anchor") or sp.get("start")}
    for sp in specs:
        got: list[str] = []
        if "anchor" in sp:
            a, rels, d = sp["anchor"], set(sp.get("relations") or []), sp.get("direction", "both")
            types = set(sp.get("types") or [])                  # object types the question asks for (model, paper, ...)
            for i in kg.adj.get(a, []):
                e = kg.edges[i]
                if e["status"] == "unsupported" or (rels and e["relation"] not in rels):
                    continue
                if d == "out" and e["head"] != a or d == "in" and e["tail"] != a:
                    continue
                other = e["tail"] if e["head"] == a else e["head"]
                if types and kg.ents[other]["type"] not in types:
                    continue
                got.append(i)
        elif "path" in sp:
            r = kg.graph_query(sp["start"], sp["path"], limit=200)
            got = [x for row in r.get("results", []) for x in row["via_edge_ids"]]
        elif "top" in sp:
            t = sp["top"]
            rows = kg.top(t["relation"], t.get("direction", "in"), t.get("type"), t.get("k", 5))["results"]
            ents |= {row["id"] for row in rows}
            edges += [i for row in rows for i in row["example_edge_ids"]]
            continue
        got = sorted(dict.fromkeys(x for x in got if x in kg.edges), key=lambda x: -kg.edges[x]["strength"])[:CAP]
        edges += got
        ents |= {x for i in got for x in (kg.edges[i]["head"], kg.edges[i]["tail"])} - anchors
    return {"edges": list(dict.fromkeys(edges)), "entities": ents, "anchors": anchors}


def stage_metrics(kg: KG, run: dict, g: dict) -> dict:
    gold, anchors = g["entities"], g["anchors"]
    touched = {x for s in run.get("steps") or [] for x in (s.get("touched") or {}).get("entities", [])}
    touched |= {x for s in run.get("steps") or [] for i in (s.get("touched") or {}).get("edges", []) if i in kg.edges
                for x in (kg.edges[i]["head"], kg.edges[i]["tail"])}
    touched -= anchors
    found = {x for f in run.get("notes") or [] for n in f.get("entities") or [] if (x := G._resolve(kg, n))}
    found |= {x for f in run.get("notes") or [] for i in f.get("edge_ids") or [] if i in kg.edges
              for x in (kg.edges[i]["head"], kg.edges[i]["tail"])}
    ans = set((run.get("metrics") or {}).get("kb_entities") or [])
    # an org and its same-name product/technology are one thing for this purpose (ER leaves them as twins)
    canon = lambda xs: xs | {t for x in xs for t in kg.twins(x)}
    touched, found, ans = canon(touched), canon(found), canon(ans)
    text = G._blind(run.get("answer") or {})
    n = max(len(gold), 1)
    reached, used = gold & touched, gold & ans
    by_type = {}
    for x in gold:
        t = kg.ents[x]["type"]
        b = by_type.setdefault(t, [0, 0, 0])               # gold, retrieved, used (counts per object type)
        b[0] += 1
        b[1] += x in touched
        b[2] += x in ans
    return {"by_type": by_type, "gold": len(gold), "retrieved": round(len(reached) / n, 3), "grounded": round(len(gold & found) / n, 3) if run.get("notes") is not None else None,
            "used": round(len(used) / n, 3), "utilisation": round(len(used & reached) / len(reached), 3) if reached else None,
            "precision": round(len(reached) / len(touched), 3) if touched else None, "touched": len(touched),
            "doubt": len(_DOUBT.findall(text)), "named": (run.get("metrics") or {}).get("named"),
            "in_graph": (run.get("metrics") or {}).get("in_kb"), "steps": len(run.get("steps") or []),
            "cost": run.get("cost_usd")}
