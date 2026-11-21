"""Scout run: a small, real end-to-end pass (fetch → extract → verify → grade → rank → explore).

It is NOT the evaluated crawler (no frozen gold, no policy comparison). It exists to pull a real
data sample, find failure modes early, and look at the graph. Hop 2 follows the top-PPR orgs from
hop 1 to their own sites. This is the recursion, and it lets counterparty evidence raise edge status.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from rich.console import Console

from cf import config
from cf.crawl.fetch import Fetcher, registrable
from cf.crawl.sources import homepage, same_site_candidates
from cf.extract.llm import (
    EXTRACT_SYSTEM,
    VERIFY_SYSTEM,
    Extraction,
    LLMExtractor,
    Verdict,
    Verifier,
    XEntity,
    XTriple,
    make_verifier,
)
from cf.graph.build import GraphBuilder
from cf.llm.client import LLM, BudgetExceeded
from cf.rank.scores import scores, to_graph
from cf.viz.explorer import write_explorer

OUT = config.DATA / "processed" / "scout"
console = Console()


CACHE = config.DATA / "interim" / "extractions"


def _extract_verify_cached(page, ex: LLMExtractor, ve: Verifier):
    """Idempotent stage: key = page content hash + models + prompts. A re-run or crash never pays
    twice for the same page; changing a model or prompt invalidates the cache automatically."""
    key_src = f"{page.raw_sha256}|{ex.version}|{ve.version}|{EXTRACT_SYSTEM}|{VERIFY_SYSTEM}"
    key = hashlib.sha256(key_src.encode()).hexdigest()[:24]
    path = CACHE / f"{key}.json"
    if path.exists():
        d = json.loads(path.read_text())
        ext = Extraction([XEntity(**e) for e in d["entities"]], [XTriple(**t) for t in d["triples"]],
                         d["dropped_unquoted"])
        return ext, [Verdict(**v) if v else None for v in d["verdicts"]]
    ext = ex.extract(page)
    verdicts = ve.verify(ext.triples, page)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "url": page.url, "sha": page.raw_sha256, "extractor": ex.version, "verifier": ve.version,
        "entities": [e.model_dump() for e in ext.entities],
        "triples": [t.model_dump() for t in ext.triples],
        "dropped_unquoted": ext.dropped_unquoted,
        "verdicts": [v.model_dump() if v else None for v in verdicts],
    }, indent=1))
    return ext, verdicts


@dataclass
class ScoutReport:
    pages: list[dict] = field(default_factory=list)
    spent_usd: float = 0.0
    out_dir: str = str(OUT)


def run_scout(seeds: list[dict], pages_per_seed: int = 5, hop2_orgs: int = 6, hop2_pages: int = 1,
              workers: int = 6) -> ScoutReport:
    fetcher = Fetcher()
    ex = LLMExtractor(config.env("CF_MODEL_EXTRACT"))
    ve = make_verifier()
    gb = GraphBuilder()
    seed_ids = {gb.register_seed(s["name"], s["domain"], s.get("org_kind", "neolab"), s.get("layer"))
                for s in seeds}
    seed_sites = {registrable(s["domain"]) for s in seeds}
    report = ScoutReport()
    done: set[str] = set()

    def process(url: str, hop: int):
        if url in done:
            return None
        done.add(url)
        page = fetcher.fetch(url)
        if page is None or len(page.text) < 200:
            report.pages.append({"url": url, "hop": hop, "status": "skipped (no page / too little text)"})
            return None
        try:
            ext, verdicts = _extract_verify_cached(page, ex, ve)
        except RuntimeError as e:  # one bad page must not sink the run
            report.pages.append({"url": url, "hop": hop, "status": f"llm_failed: {str(e)[:160]}"})
            console.print(f"  [red]hop {hop} {url}: {str(e)[:120]}[/]")
            return None
        new = gb.add_page(page, ext, verdicts, ex.version, ve.version)
        n_bad = sum(1 for v in verdicts if v is not None and not v.entailed)
        report.pages.append({"url": url, "hop": hop, "chars": len(page.text), "entities": len(ext.entities),
                             "triples": len(ext.triples), "new_edges": new,
                             "dropped_unquoted": ext.dropped_unquoted, "verifier_rejected": n_bad})
        console.print(f"  [dim]hop {hop}[/] {url}  →  {len(ext.triples)} triples, {new} new edges, "
                      f"{ext.dropped_unquoted} unquoted dropped, {n_bad} rejected by verifier "
                      f"[dim](${LLM.spent_usd:.4f})[/]")
        return page

    def warm(urls: list[str]) -> None:
        """Fetch serially (politeness), then extract+verify pages in parallel into the cache."""
        pages = [p for p in (fetcher.fetch(u) for u in dict.fromkeys(urls)) if p and len(p.text) >= 200]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_extract_verify_cached, p, ex, ve) for p in pages]
            for f in futs:
                try:
                    f.result()
                except RuntimeError as e:
                    console.print(f"  [red]warm-up failed: {str(e)[:120]}[/]")

    try:
        console.rule(f"[bold]Hop 1 · {len(seeds)} seeds: {', '.join(s['name'] for s in seeds)}")
        hop1: list[str] = []
        for sd in seeds:
            start = list(sd.get("start_urls") or [homepage(sd["domain"])])
            first_page = fetcher.fetch(start[0])
            cands = same_site_candidates(first_page, k=pages_per_seed) if first_page else []
            hop1 += list(dict.fromkeys(start + cands))[:pages_per_seed]
        warm(hop1)
        for url in hop1:
            process(url, 1)

        gb.finalize()
        s = scores(to_graph(gb.entities, list(gb.edges.values())), gb.seeds)
        # Boundary rule: follow AI-ecosystem orgs, not adopters/customers outside the AI core.
        targets = sorted(
            (e for e in gb.entities.values()
             if e["type"] == "org" and e["id"] not in seed_ids and e.get("domain")
             and e["domain"] not in seed_sites
             and e.get("org_kind") != "customer" and e.get("layer") != "adopter"),
            key=lambda e: -s.get(e["id"], {}).get("ppr", 0))[:hop2_orgs]
        console.rule(f"[bold]Hop 2 · following top-PPR orgs: {', '.join(t['name'] for t in targets) or 'none with a known domain'}")
        hop2_urls = []
        for t in targets:
            hp = fetcher.fetch(homepage(t["domain"]))
            hop2_urls += [homepage(t["domain"])] + (same_site_candidates(hp, k=hop2_pages) if hp else [])
        warm(hop2_urls)
        for t in targets:
            p = process(homepage(t["domain"]), 2)
            for u in (same_site_candidates(p, k=hop2_pages) if p else []):
                process(u, 2)
    except BudgetExceeded as e:
        console.print(f"[red]budget stop:[/] {e}")

    gb.finalize()
    s = scores(to_graph(gb.entities, list(gb.edges.values())), gb.seeds)
    graph = gb.to_dict(s)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "graph.json").write_text(json.dumps(graph, indent=1, ensure_ascii=False))
    (OUT / "pages.json").write_text(json.dumps(report.pages, indent=1))
    n_pages = sum(1 for p in report.pages if "triples" in p)
    write_explorer(graph, OUT / "explorer.html",
                   subtitle=f"Scout from {len(seeds)} seeds · {n_pages} pages · extract {ex.llm.model} · verify {ve.llm.model}")
    report.spent_usd = LLM.spent_usd
    return report
