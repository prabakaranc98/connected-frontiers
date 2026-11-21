"""Use-case tasks with answer keys computed from the KG (docs/BENCHMARK.md §2).

v0 covers four use cases (all answer keys computed, no hand-writing):
  U1 landscape   – map a named segment: main players and what they do
  U2 shortlist   – shortlist organisations that use/offer a method, with evidence
  U5 claim audit – label claims by how well the evidence supports them
  U6 targeting   – most likely buyers/partners for a problem (ranked)
"""

from __future__ import annotations

import json
import random
from collections import defaultdict

from cf import config
from cf.agent.kg import KG

OUT = config.EVAL / "gold"


def _edge_line(kg: KG, e: dict) -> str:
    return f"[{e['id']}] {kg.name(e['head'])} —{e['relation']}→ {kg.name(e['tail'])} (status: {e['status']})"


def u1_landscape(kg: KG, rnd: random.Random, n: int) -> list[dict]:
    segs = [c for c in kg.comms.values() if 12 <= c["size"] <= 150]
    rnd.shuffle(segs)
    tasks = []
    for c in segs[:n]:
        members = [e for e in kg.ents.values() if e.get("community") == c["id"]]
        players = sorted((e for e in members if e["type"] in ("org", "model", "technology")),
                         key=lambda e: -(e.get("pagerank") or 0))[:10]
        if len(players) < 5:
            continue
        ids = {e["id"] for e in members}
        oracle = [_edge_line(kg, e) for e in kg.g["edges"] if e["head"] in ids and e["tail"] in ids][:80]
        tasks.append({"use_case": "U1_landscape", "brief":
            f"Map the landscape of this part of the AI ecosystem: \"{c['name']}\". Who are the main players "
            f"(organisations, models, products), what do they offer or work on, and who do they serve? "
            f"List the 8 most important players as items. Flag statements that are only self-claimed.",
            "key": {"players": [e["id"] for e in players], "segment_ids": sorted(ids)},
            "oracle_edges": oracle})
    return tasks


def u2_shortlist(kg: KG, rnd: random.Random, n: int) -> list[dict]:
    users: dict[str, dict[str, float]] = defaultdict(dict)
    for e in kg.g["edges"]:
        if e["relation"] in ("uses_method", "offers") and kg.ents[e["head"]]["type"] == "org" \
                and kg.ents[e["tail"]]["type"] == "method" and e["status"] != "unsupported":
            score = e["strength"] * (1 + 50 * (kg.ents[e["head"]].get("pagerank") or 0))
            users[e["tail"]][e["head"]] = max(users[e["tail"]].get(e["head"], 0), score)
    methods = [m for m, orgs in users.items() if len(orgs) >= 3]
    rnd.shuffle(methods)
    tasks = []
    for m in methods[:n]:
        ranked = sorted(users[m], key=lambda o: -users[m][o])
        oracle = [_edge_line(kg, e) for e in kg.g["edges"] if e["tail"] == m or e["head"] == m][:60]
        tasks.append({"use_case": "U2_shortlist", "brief":
            f"We are building a product and need deep expertise in \"{kg.name(m)}\". Shortlist the 3 organisations "
            f"best placed to help (they use or offer it), each with the evidence, and say how well-supported each claim is.",
            "key": {"method": m, "orgs": ranked}, "oracle_edges": oracle})
    return tasks


def u5_claim_audit(kg: KG, rnd: random.Random, n: int, per_task: int = 6) -> list[dict]:
    by_status: dict[str, list[dict]] = defaultdict(list)
    for e in kg.g["edges"]:
        if e["relation"] in ("publishes", "subtype_of", "part_of"):
            continue
        by_status[e["status"]].append(e)
    for v in by_status.values():
        rnd.shuffle(v)
    tasks = []
    for _ in range(n):
        picks = []
        for st, k in (("verified", 2), ("claimed", 2), ("confirmed", 1), ("unsupported", 1)):
            picks += [by_status[st].pop() for _ in range(min(k, len(by_status[st])))]
        while len(picks) < per_task and by_status["claimed"]:
            picks.append(by_status["claimed"].pop())
        rnd.shuffle(picks)
        claims = "\n".join(f"{i + 1}. {kg.name(e['head'])} {e['relation'].replace('_', ' ')} {kg.name(e['tail'])}"
                           for i, e in enumerate(picks))
        tasks.append({"use_case": "U5_claim_audit", "brief":
            "Audit these claims about the AI ecosystem. For each, find the evidence and label it as one of: "
            "verified (primary record), corroborated (several independent sources), confirmed (the other party agrees), "
            "self-claimed (only the subject says so), unsupported (the source does not actually state it). "
            "Say what would verify it. Return one item per claim with name 'claim N' and the label.\n" + claims,
            "key": {"labels": [e["status"] for e in picks], "edge_ids": [e["id"] for e in picks]},
            "oracle_edges": [_edge_line(kg, e) for e in picks]})
    return tasks


def u6_targeting(kg: KG, rnd: random.Random, n: int) -> list[dict]:
    probs = [p for p in kg.ents.values() if p["type"] == "problem"
             and sum(1 for x in kg.adj.get(p["id"], []) if kg.ents[kg.edges[x]["head"]]["type"] == "org") >= 3]
    rnd.shuffle(probs)
    tasks = []
    for p in probs[:n]:
        ranked = [r["id"] for r in kg.ppr([p["id"]], k=15, type="org") if "id" in r]
        if len(ranked) < 5:
            continue
        near = set(ranked) | {p["id"]}
        oracle = [_edge_line(kg, e) for e in kg.g["edges"] if e["head"] in near or e["tail"] in near][:80]
        tasks.append({"use_case": "U6_targeting", "brief":
            f"We are launching a product that helps with \"{p['name']}\". Which 5 organisations are the most likely "
            f"buyers or partners, and why? Rank them, most likely first, with evidence.",
            "key": {"problem": p["id"], "ranked_orgs": ranked}, "oracle_edges": oracle})
    return tasks


def build(per_use_case: int = 5, seed: int = 7, version: str = "v0") -> list[dict]:
    kg = KG()
    rnd = random.Random(seed)
    tasks = (u1_landscape(kg, rnd, per_use_case) + u2_shortlist(kg, rnd, per_use_case)
             + u5_claim_audit(kg, rnd, per_use_case) + u6_targeting(kg, rnd, per_use_case))
    for i, t in enumerate(tasks):
        t["id"] = f"{t['use_case'].split('_')[0]}-{i:03d}"
        t["kg_snapshot"] = kg.g.get("generated_at", "graph.json")
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"tasks_{version}.jsonl").open("w") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return tasks
