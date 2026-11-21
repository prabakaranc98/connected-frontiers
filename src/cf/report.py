"""Build report: scale · extraction · verification & trust · entity resolution · KG structure · cost.

Reads the build outputs (data/processed/graph/*), the fetch log and the LLM call log.
Writes report.json + report.md, and a dated copy under reports/.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from statistics import mean

import networkx as nx

from cf import config

G_DIR = config.DATA / "processed" / "graph"
REPORTS = config.ROOT / "reports"


def _load(name: str):
    return json.loads((G_DIR / name).read_text())


def _pct(a: float, b: float) -> float:
    return round(100 * a / b, 1) if b else 0.0


def compute() -> dict:
    graph, summary, pages = _load("graph.json"), _load("summary.json"), _load("pages.json")
    ents = {e["id"]: e for e in graph["entities"]}
    edges = graph["edges"]
    ok_pages = [p for p in pages if not p.get("failed")]

    # ---- A. crawl scale ------------------------------------------------------------------
    last: dict[str, str] = {}
    for line in (config.DATA / "raw" / "index.jsonl").read_text().splitlines():
        r = json.loads(line)
        last[r["url"]] = r["status"]
    fails = Counter(s.split(":")[0] for s in last.values() if s != "ok")
    publishers = Counter(ev["publisher"] for e in edges for ev in e["evidence"])
    crawl = {"urls_attempted": len(last), "urls_ok": sum(1 for s in last.values() if s == "ok"),
             "failures_by_reason": dict(fails), "pages_in_graph": len(ok_pages),
             "publishers": len({p for p in publishers}), "seeds": len(graph["seeds"]),
             "mean_page_chars": round(mean(p["chars"] for p in ok_pages)) if ok_pages else 0}

    # ---- B. extraction -------------------------------------------------------------------
    triples = sum(p["triples"] for p in ok_pages)
    dropped = sum(p["dropped_unquoted"] for p in ok_pages)
    extraction = {"triples_kept": triples, "per_page": round(triples / max(len(ok_pages), 1), 1),
                  "unquoted_dropped": dropped, "unquoted_drop_rate_pct": _pct(dropped, triples + dropped),
                  "relations": dict(Counter(e["relation"] for e in edges).most_common()),
                  "entity_types": dict(Counter(e["type"] for e in ents.values()).most_common())}

    # ---- C. verification & trust ---------------------------------------------------------
    ver = Counter()
    by_rel = defaultdict(Counter)
    by_pub = defaultdict(Counter)
    kinds = Counter()
    for e in edges:
        for ev in e["evidence"]:
            k = {True: "entailed", False: "rejected", None: "unchecked"}[ev["entailed"]]
            ver[k] += 1
            by_rel[e["relation"]][k] += 1
            by_pub[ev["publisher"]][k] += 1
            kinds[ev["source_kind"]] += 1
    n_ev = sum(ver.values())
    pubs_per_entity = defaultdict(set)
    for e in edges:
        for ev in e["evidence"]:
            pubs_per_entity[e["head"]].add(ev["publisher"])
            pubs_per_entity[e["tail"]].add(ev["publisher"])
    trust = {
        "citations": n_ev, "verifier_entailed_pct": _pct(ver["entailed"], n_ev),
        "verifier_rejected_pct": _pct(ver["rejected"], n_ev), "unchecked_pct": _pct(ver["unchecked"], n_ev),
        "reject_rate_by_relation_pct": {r: _pct(c["rejected"], sum(c.values()))
                                        for r, c in sorted(by_rel.items(), key=lambda x: -sum(x[1].values()))},
        "worst_publishers_by_reject_pct": sorted(
            ((p, _pct(c["rejected"], sum(c.values())), sum(c.values())) for p, c in by_pub.items()
             if sum(c.values()) >= 10), key=lambda x: -x[1])[:6],
        "source_kinds": dict(kinds),
        "edge_status": dict(Counter(e["status"] for e in edges)),
        "mean_edge_strength": round(mean(e["strength"] for e in edges), 3) if edges else 0,
        "edges_multi_publisher": sum(1 for e in edges if len({ev["publisher"] for ev in e["evidence"]}) > 1),
        "entities_multi_publisher": sum(1 for s in pubs_per_entity.values() if len(s) > 1),
        "contested_edges": sum(1 for e in edges if e.get("contested")),
    }

    # ---- D. entity resolution ------------------------------------------------------------
    er = summary.get("er") or {}
    b, a = summary["before_er"], summary["after_er"]
    resolution = {k: er.get(k) for k in ("candidates", "auto_merges", "llm_same", "llm_hierarchy",
                                         "llm_different", "merged_groups", "spend_usd")}
    resolution["entities_before"], resolution["entities_after"] = b["entities"], a["entities"]
    resolution["entity_reduction_pct"] = _pct(b["entities"] - a["entities"], b["entities"])
    resolution["hierarchy_links"] = len(graph.get("hierarchy", []))

    # ---- E. KG structure -----------------------------------------------------------------
    g = nx.Graph()
    g.add_nodes_from(ents)
    g.add_edges_from((e["head"], e["tail"]) for e in edges if e["status"] != "unsupported")
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    structure = {"nodes": g.number_of_nodes(), "edges_supported": g.number_of_edges(),
                 "components": len(comps), "largest_component_pct": _pct(len(comps[0]), g.number_of_nodes()) if comps else 0,
                 "isolated_nodes": sum(1 for c in comps if len(c) == 1),
                 "avg_degree": round(2 * g.number_of_edges() / max(g.number_of_nodes(), 1), 2),
                 "segments": len(graph.get("communities", [])),
                 "top_ppr": [(ents[i]["name"], round(ents[i].get("ppr", 0), 4))
                             for i in sorted(ents, key=lambda i: -(ents[i].get("ppr") or 0))[:10]],
                 "top_pagerank_non_seed": [(ents[i]["name"], round(ents[i].get("pagerank", 0), 4))
                                           for i in sorted((i for i in ents if i not in set(graph["seeds"])),
                                                           key=lambda i: -(ents[i].get("pagerank") or 0))[:10]]}

    # ---- F. cost & time ------------------------------------------------------------------
    calls = [json.loads(line) for line in (config.DATA / "interim" / "llm_calls.jsonl").read_text().splitlines()]
    current = {summary["extractor"].split(":", 1)[1], summary["verifier"].split(":")[1]}
    by_call = defaultdict(list)
    for c in calls:
        by_call[(c["call"], c["model"])].append(c)
    per_call = {f"{k[0]} · {k[1]}": {"n": len(v), "mean_cost_usd": round(mean(x["cost_usd"] for x in v), 5),
                                     "mean_out_tokens": round(mean((x.get("completion_tokens") or 0) for x in v))}
                for k, v in by_call.items()}
    ex_cost = mean([c["cost_usd"] for c in calls if c["call"] == "kg_extract" and c["model"] in current] or [0])
    vf_cost = mean([c["cost_usd"] for c in calls if c["call"] == "kg_verify" and c["model"] in current] or [0])
    per_page = ex_cost + vf_cost
    verified_edges = sum(1 for e in edges if any(ev["entailed"] for ev in e["evidence"]))
    cost = {"all_time_llm_spend_usd": round(sum(c["cost_usd"] for c in calls), 4),
            "this_build_spend_usd": summary["spend_this_build_usd"],
            "per_page_usd (extract+verify, current models)": round(per_page, 5),
            "per_verified_edge_usd": round(per_page * len(ok_pages) / max(verified_edges, 1), 5),
            "projection_300_orgs_x_12_pages_usd": round(per_page * 3600, 2),
            "timings_s": summary["timings"], "per_call": per_call}

    return {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "extractor": summary["extractor"], "verifier": summary["verifier"],
            "A_crawl": crawl, "B_extraction": extraction, "C_verification_trust": trust,
            "D_entity_resolution": resolution, "E_structure": structure, "F_cost_time": cost}


def to_markdown(r: dict) -> str:
    A, B, C, D, E, F = (r[k] for k in ("A_crawl", "B_extraction", "C_verification_trust",
                                       "D_entity_resolution", "E_structure", "F_cost_time"))
    rows = [
        "# Build report", "", f"Generated {r['generated_at']} · extractor `{r['extractor']}` · verifier `{r['verifier']}`", "",
        "## Headline", "", "| Area | Metric | Value |", "|---|---|---|",
        f"| Crawl | pages in graph / URLs attempted | {A['pages_in_graph']} / {A['urls_attempted']} ({A['publishers']} publishers, {A['seeds']} seeds) |",
        f"| Extraction | triples kept (per page) | {B['triples_kept']} ({B['per_page']}) |",
        f"| Extraction | unquoted (hallucinated-quote) drop rate | {B['unquoted_drop_rate_pct']}% |",
        f"| Verification | citations entailed / rejected / unchecked | {C['verifier_entailed_pct']}% / {C['verifier_rejected_pct']}% / {C['unchecked_pct']}% |",
        f"| Trust | edges with >1 publisher · entities with >1 publisher | {C['edges_multi_publisher']} · {C['entities_multi_publisher']} |",
        f"| Trust | mean edge strength | {C['mean_edge_strength']} |",
        f"| ER | entities before → after (−%) | {D['entities_before']} → {D['entities_after']} (−{D['entity_reduction_pct']}%) |",
        f"| ER | auto · LLM same · LLM hierarchy · LLM different | {D['auto_merges']} · {D['llm_same']} · {D['llm_hierarchy']} · {D['llm_different']} |",
        f"| Structure | components · largest component · isolated | {E['components']} · {E['largest_component_pct']}% · {E['isolated_nodes']} |",
        f"| Structure | avg degree · segments | {E['avg_degree']} · {E['segments']} |",
        f"| Cost | $/page · $/verified edge · this build | ${F['per_page_usd (extract+verify, current models)']} · ${F['per_verified_edge_usd']} · ${F['this_build_spend_usd']} |",
        f"| Cost | projected 300 orgs × 12 pages | ${F['projection_300_orgs_x_12_pages_usd']} |",
        f"| Time | build total (extract+verify) | {F['timings_s']['total_s']}s ({F['timings_s']['extract_verify_s']}s) |",
        "", "## Verifier reject rate by relation", "", "| Relation | Reject % |", "|---|---|",
        *[f"| {k} | {v}% |" for k, v in C["reject_rate_by_relation_pct"].items()],
        "", "## Publishers with the highest reject rate (≥10 citations)", "", "| Publisher | Reject % | Citations |", "|---|---|---|",
        *[f"| {p} | {x}% | {n} |" for p, x, n in C["worst_publishers_by_reject_pct"]],
        "", "## Edge status", "", "| Status | Edges |", "|---|---|", *[f"| {k} | {v} |" for k, v in C["edge_status"].items()],
        "", "## Top by PPR from seeds", "", *[f"{i + 1}. {n} ({v})" for i, (n, v) in enumerate(E["top_ppr"])],
        "", "## Top by global PageRank (non-seed)", "", *[f"{i + 1}. {n} ({v})" for i, (n, v) in enumerate(E["top_pagerank_non_seed"])],
        "", "## Crawl failures", "", *[f"- {k}: {v}" for k, v in A["failures_by_reason"].items()],
        "", "## LLM calls by type · model", "", "| Call · model | n | mean $ | mean out tokens |", "|---|---|---|---|",
        *[f"| {k} | {v['n']} | {v['mean_cost_usd']} | {v['mean_out_tokens']} |" for k, v in F["per_call"].items()],
    ]
    return "\n".join(rows) + "\n"


def write() -> tuple[dict, str]:
    r = compute()
    md = to_markdown(r)
    (G_DIR / "report.json").write_text(json.dumps(r, indent=1))
    (G_DIR / "report.md").write_text(md)
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    (REPORTS / f"{stamp}-build.md").write_text(md)
    return r, md
