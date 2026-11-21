"""Build stage: every known page → (cached) extract+verify → graph → ER → grade → rank → export.

Idempotent: extraction is cached by page hash + models + prompts, so changing a prompt
re-extracts exactly the pages it affects, and nothing else is paid twice.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from rich.console import Console

from cf import config
from cf.crawl.fetch import Fetcher
from cf.extract.llm import LLMExtractor, make_verifier
from cf.graph.build import GraphBuilder
from cf.llm.client import LLM
from cf.rank.scores import scores, to_graph
from cf.resolve.er import resolve
from cf.scout import CACHE, _extract_verify_cached
from cf.viz.explorer import write_explorer

OUT = config.DATA / "processed" / "graph"
console = Console()


def known_urls() -> list[str]:
    """Every page that has ever been extracted (any version)."""
    urls = []
    for f in sorted(CACHE.glob("*.json")):
        urls.append(json.loads(f.read_text())["url"])
    return list(dict.fromkeys(urls))


def stats(gb: GraphBuilder) -> dict:
    edges = list(gb.edges.values())
    return {"entities": len(gb.entities), "edges": len(edges),
            "edges_multi_publisher": sum(1 for e in edges if len({x.publisher for x in e.evidence}) > 1),
            "status": {s: sum(1 for e in edges if e.status.value == s)
                       for s in ["unsupported", "claimed", "confirmed", "corroborated", "verified"]}}


def build(seeds: list[dict], er_model: str | None, workers: int = 6) -> dict:
    t0 = time.time()
    timings: dict[str, float] = {}
    spend0 = LLM.spent_usd
    fetcher = Fetcher()
    ex = LLMExtractor(config.env("CF_MODEL_EXTRACT"))
    ve = make_verifier()
    urls = known_urls()
    pages = [p for p in (fetcher.fetch(u) for u in urls) if p is not None and len(p.text) >= 200]
    timings["load_pages_s"] = round(time.time() - t0, 1)

    t = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda p: _safe(p, ex, ve), pages))
    timings["extract_verify_s"] = round(time.time() - t, 1)
    extract_spend = LLM.spent_usd - spend0

    t = time.time()
    gb = GraphBuilder()
    for s in seeds:
        gb.register_seed(s["name"], s["domain"], s.get("org_kind", "neolab"), s.get("layer"))
    page_stats = []
    for p, res in zip(pages, results, strict=True):
        if res is None:
            page_stats.append({"url": p.url, "failed": True})
            continue
        ext, verdicts = res
        gb.add_page(p, ext, verdicts, ex.version, ve.version)
        page_stats.append({"url": p.url, "chars": len(p.text), "triples": len(ext.triples),
                           "dropped_unquoted": ext.dropped_unquoted,
                           "verified": sum(1 for v in verdicts if v is not None and v.entailed),
                           "rejected": sum(1 for v in verdicts if v is not None and not v.entailed),
                           "unchecked": sum(1 for v in verdicts if v is None)})
    from cf.adapters.hf import all_rows as hf_rows
    hf = hf_rows()
    hf_added = gb.add_structured(hf, publisher="huggingface.co", adapter="hf-hub-v0") if hf else 0
    timings["adapters_rows"] = len(hf)
    timings["adapters_new_edges"] = hf_added
    gb.finalize()
    before = stats(gb)
    timings["graph_s"] = round(time.time() - t, 1)

    t = time.time()
    er_out, hierarchy = None, []
    if er_model is not None:
        spend_er0 = LLM.spent_usd
        pre_ents, pre_quotes = dict(gb.entities), gb.quotes_by_entity()
        mapping, rep = resolve(gb.entities, pre_quotes, er_model, gb.degrees())
        gb.apply_mapping(mapping)
        gb.finalize()
        hierarchy = [{**h, "child": mapping.get(h["child"], h["child"]), "parent": mapping.get(h["parent"], h["parent"])}
                     for h in rep.hierarchy]
        hierarchy = [h for h in hierarchy if h["child"] != h["parent"]]
        names = {k: v["name"] for k, v in gb.entities.items()}
        er_out = {"candidates": len(rep.auto) + len(rep.llm_accepted) + len(rep.llm_rejected) + len(rep.hierarchy),
                  "auto_merges": len(rep.auto), "llm_same": len(rep.llm_accepted),
                  "llm_hierarchy": len(rep.hierarchy), "llm_different": len(rep.llm_rejected),
                  "merged_groups": len(rep.groups), "spend_usd": round(LLM.spent_usd - spend_er0, 5),
                  "groups": {names.get(c, c): members for c, members in rep.groups.items()},
                  "hierarchy": [f'{names.get(h["child"], h["child"])} —{h["kind"]}→ {names.get(h["parent"], h["parent"])}'
                                for h in hierarchy]}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "er_report.json").write_text(json.dumps(
            {**er_out, "accepted": [asdict(c) for c in rep.auto + rep.llm_accepted],
             "rejected": [asdict(c) for c in rep.llm_rejected],
             "decisions": [{**d, **{f"{k}_{side}": pre_ents[d[side]][k] for side in ("a", "b") for k in ("name", "type")},
                            "quotes_a": pre_quotes.get(d["a"], [])[:2], "quotes_b": pre_quotes.get(d["b"], [])[:2]}
                           for d in rep.decisions]}, indent=1))
    after = stats(gb)
    timings["er_s"] = round(time.time() - t, 1)

    t = time.time()
    g = to_graph(gb.entities, list(gb.edges.values()))
    s = scores(g, gb.seeds)
    graph = gb.to_dict(s)
    graph["hierarchy"] = hierarchy
    from cf.viz.explorer import compute_layout
    from cf.viz.segments import name_segments
    compute_layout(graph)
    name_segments(graph, er_model)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "graph.json").write_text(json.dumps(graph, indent=1, ensure_ascii=False))
    (OUT / "pages.json").write_text(json.dumps(page_stats, indent=1))
    write_explorer(graph, OUT / "explorer.html",
                   subtitle=f"{len(pages)} pages · {len(seeds)} seeds · ER {'on' if er_out else 'off'}")
    (OUT / "graph.json").write_text(json.dumps(graph, indent=1, ensure_ascii=False))   # with layout
    timings["rank_layout_export_s"] = round(time.time() - t, 1)
    timings["total_s"] = round(time.time() - t0, 1)

    summary = {"pages": len(pages), "extractor": ex.version, "verifier": ve.version,
               "before_er": before, "after_er": after, "er": er_out, "timings": timings,
               "spend_this_build_usd": round(LLM.spent_usd - spend0, 5),
               "spend_extract_verify_usd": round(extract_spend, 5)}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def _safe(page, ex, ve):
    try:
        return _extract_verify_cached(page, ex, ve)
    except RuntimeError as e:
        console.print(f"[red]extract failed {page.url}: {str(e)[:100]}[/]")
        return None
