"""Frontier crawler: domains discovered from the graph itself, prioritized by personalized PageRank.

Loop (batches):
  1. pick the highest-priority domains that still have budget and queued URLs
  2. fetch in parallel across hosts (polite per host), apply page noise gates
  3. extract + verify in parallel (stage caches; nothing paid twice)
  4. add to the graph, regrade, recompute PPR from the seeds
  5. discover new org domains from the graph (boundary rules), re-prioritize
  6. checkpoint (resumable)

Policies: `ppr` (priority = PPR of the domain's org) or `bfs` (discovery order). Same budget,
same gates, same extractor, so the two can be compared fairly (the M3 experiment).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from rich.console import Console

from cf import config, trace
from cf.cache import extract_verify, known_urls
from cf.crawl.fetch import Fetcher, host, registrable
from cf.crawl.noise import DupIndex, NoiseStats, domain_ok, is_generic, url_ok
from cf.crawl.progress import write as write_progress
from cf.crawl.sources import PATTERNS, homepage, same_site_candidates
from cf.extract.llm import LLMExtractor, make_verifier
from cf.graph.build import GraphBuilder
from cf.llm.client import LLM, BudgetExceeded, role_chain
from cf.rank.scores import scores, to_graph

console = Console()
STATE = config.DATA / "interim" / "frontier_state.json"
AI_KINDS = {"frontier_lab", "neolab", "startup", "infra", "academic", "investor"}
AI_LAYERS = {"compute", "cloud", "models", "platform", "tooling", "application", "research"}


def _sitemap_urls(fetcher: Fetcher, domain: str, limit: int = 40) -> list[str]:
    text = fetcher.get_text(f"https://{domain}/sitemap.xml")
    if not text:
        return []
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
    if any(loc.endswith(".xml") for loc in locs[:5]):            # sitemap index → first child sitemaps
        child = [loc for loc in locs if loc.endswith(".xml")][:3]
        locs = []
        for c in child:
            t = fetcher.get_text(c)
            locs += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", t or "")
    scored = []
    for loc in locs:
        if registrable(loc) != domain:             # sitemaps sometimes list staging / other hosts
            continue
        path = urlparse(loc).path.lower()
        for rank, pat in enumerate(PATTERNS):
            if pat in path:
                scored.append((rank, loc))
                break
    return [u for _, u in sorted(scored)][:limit]


def _resolve_domain(fetcher: Fetcher, name: str) -> str | None:
    """Guess an AI org's site from its name (name.ai / .com / .io); accept only if the homepage
    title contains the name. Conservative on purpose: a wrong site would pollute the graph."""
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    if not 4 <= len(slug) <= 30 or is_generic(name):        # DNS labels ≤ 63; real brand slugs are short
        return None
    for tld in ("ai", "com", "io"):
        d = f"{slug}.{tld}"
        if not domain_ok(d):
            continue
        try:
            p = fetcher.fetch(f"https://{d}/")
        except (UnicodeError, ValueError):                   # malformed host: never let it fail a batch
            continue
        if p is not None and (name.lower() in (p.title or "").lower() or slug in re.sub(r"[^a-z0-9]", "", (p.title or "").lower())):
            return d
    return None


class Frontier:
    def __init__(self, seeds: list[dict], policy: str = "ppr", seed_cap: int = 10, new_cap: int = 4):
        self.policy, self.seed_cap, self.new_cap = policy, seed_cap, new_cap
        self.seed_domains = {registrable(s["domain"]) for s in seeds}
        self.domains: dict[str, dict] = {}   # domain -> {org, order, pages, queue, expanded}
        self.visited: set[str] = set()
        self.cites: dict[str, set[str]] = {}       # domain -> publishers linking to it (co-citation)
        self.resolve_tried: set[str] = set()       # org ids we already tried to find a site for
        self.order = 0
        for s in seeds:
            self.add_domain(registrable(s["domain"]), None, start_urls=s.get("start_urls"), force=True)

    def add_domain(self, d: str, org: str | None, start_urls: list[str] | None = None, force: bool = False) -> bool:
        if d in self.domains or (not force and not domain_ok(d)):
            return False
        self.order += 1
        self.domains[d] = {"org": org, "order": self.order, "pages": 0, "expanded": False,
                           "queue": list(start_urls or []) + [homepage(d)]}
        return True

    def note_links(self, page) -> None:
        pub = registrable(page.url)
        for link in page.links:
            d = registrable(link)
            if d and d != pub and "." in d and domain_ok(d):
                self.cites.setdefault(d, set()).add(pub)

    def expand(self, d: str, page, fetcher: Fetcher) -> None:
        st = self.domains[d]
        if st["expanded"]:
            return
        st["expanded"] = True
        extra = same_site_candidates(page, k=2 * self.cap(d)) + _sitemap_urls(fetcher, d)
        st["queue"] += [x for x in dict.fromkeys(extra) if x not in self.visited and url_ok(x, urlparse(x).path)]

    def priority(self, d: str, ppr: dict[str, float]) -> float:
        if d in self.seed_domains:
            return 1.0
        org = self.domains[d]["org"]
        if org and org in ppr:
            return ppr[org]
        return 1e-4 * len(self.cites.get(d, ()))   # unknown org: rank by how many publishers cite it

    def cap(self, d: str) -> int:
        return self.seed_cap if d in self.seed_domains else self.new_cap

    def pick(self, ppr: dict[str, float], batch: int, per_domain: int = 2) -> list[tuple[str, str]]:
        live = [d for d, s in self.domains.items() if s["pages"] < self.cap(d) and s["queue"]]
        if self.policy == "bfs":
            live.sort(key=lambda d: self.domains[d]["order"])
        else:
            live.sort(key=lambda d: -self.priority(d, ppr))
        out: list[tuple[str, str]] = []
        # Adaptive quota: few live domains → more pages each (still one request at a time per host).
        per_domain = max(per_domain, -(-batch // max(len(live), 1)))
        for d in live:
            s = self.domains[d]
            k = 0
            while s["queue"] and k < per_domain and s["pages"] + k < self.cap(d) and len(out) < batch:
                u = s["queue"].pop(0)
                if u in self.visited or not url_ok(u, urlparse(u).path) or registrable(u) != d:
                    continue                                    # invalid URLs never use a pick slot
                self.visited.add(u)
                out.append((d, u))
                k += 1
            if len(out) >= batch:
                break
        return out

    def save(self, stats: dict) -> None:
        """Atomic checkpoint (write tmp, then rename): a crash mid-write never corrupts it."""
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"policy": self.policy, "order": self.order, "stats": stats,
                                   "visited": sorted(self.visited), "domains": self.domains,
                                   "cites": {d: sorted(p) for d, p in self.cites.items()},
                                   "resolve_tried": sorted(self.resolve_tried)}, indent=1))
        tmp.replace(STATE)

    def restore(self, state: dict) -> None:
        self.domains.update(state.get("domains", {}))
        self.visited |= set(state.get("visited", []))
        for d, pubs in state.get("cites", {}).items():
            self.cites.setdefault(d, set()).update(pubs)
        self.order = max(self.order, state.get("order", 0))
        self.resolve_tried |= set(state.get("resolve_tried", []))


def status() -> dict:
    """Read-only view of the last checkpoint (no network, no LLM)."""
    if not STATE.exists():
        return {"state": "no checkpoint yet"}
    st = json.loads(STATE.read_text())
    stats = st.get("stats", {})
    hist = stats.get("history", [])
    doms = st.get("domains", {})
    return {"policy": st.get("policy"), "last_batch": hist[-1] if hist else None, "batches": len(hist),
            "domains_known": len(doms), "domains_crawled": sum(1 for d in doms.values() if d.get("pages")),
            "queued_urls": sum(len(d.get("queue", [])) for d in doms.values()), "visited": len(st.get("visited", [])),
            "noise": stats.get("noise"), "generic_dropped": stats.get("generic"), "errors": stats.get("errors"),
            "last_error": stats.get("last_error"), "finished": stats.get("finished", False)}


def crawl(seeds: list[dict], budget: int, policy: str = "ppr", batch: int = 40, workers: int = 8,
          seed_cap: int = 10, new_cap: int = 4, resume: bool = False) -> dict:
    t0, spend0 = time.time(), LLM.spent_usd
    fetcher = Fetcher()
    ex, ve = LLMExtractor(role_chain("extract")[0]), make_verifier()
    ex.llm.fallbacks = role_chain("extract")[1:]
    gb = GraphBuilder()
    seed_ids = [gb.register_seed(s["name"], s["domain"], s.get("org_kind", "neolab"), s.get("layer")) for s in seeds]
    fr = Frontier(seeds, policy, seed_cap, new_cap)
    noise, dups = NoiseStats(), DupIndex()
    max_usd = float(config.env("CF_LLM_BUDGET_USD", "6.5"))
    ctx = {"phase": "warm start: loading cached pages", "history": [], "base": 0, "errors": 0, "last_error": None,
           "finished": False, "n": 0, "of": 0}
    stop = threading.Event()

    def render():
        try:
            live = {"ts": time.time(), "pid": os.getpid(), "policy": policy, "phase": ctx["phase"], "n": ctx["n"], "of": ctx["of"],
                    "run_pages": ctx.get("done", 0), "crawler_pages_total": ctx["base"] + ctx.get("done", 0),
                    "entities": len(gb.entities), "edges": len(gb.edges), "domains_known": len(fr.domains),
                    "queued_urls": sum(len(d["queue"]) for d in fr.domains.values()),
                    "run_spend_usd": round(LLM.spent_usd - spend0, 4), "minutes": round((time.time() - t0) / 60, 1),
                    "budget": budget, "max_usd": max_usd, "errors": ctx["errors"], "last_error": ctx["last_error"],
                    "finished": ctx["finished"], "trace_run": trace.RUN_ID, "noise": dict(noise) | dict(gb.noise)}
            (config.DATA / "interim" / "crawl_live.json").write_text(json.dumps(live))
        except (OSError, RuntimeError):
            pass
        try:
            write_progress(ctx["history"], ctx["base"] + budget, max_usd, dict(noise), dict(gb.noise), policy,
                           ctx["errors"], ctx["last_error"], ctx["finished"],
                           sum(1 for d in fr.domains.values() if d["pages"]), sum(len(d["queue"]) for d in fr.domains.values()),
                           phase=f'{ctx["phase"]}' + (f' ({ctx["n"]}/{ctx["of"]})' if ctx["of"] else ""),
                           live={"pages": ctx["base"] + ctx.get("done", 0), "entities": len(gb.entities),
                                 "edges": len(gb.edges), "domains_known": len(fr.domains),
                                 "spend": round(LLM.spent_usd - spend0, 4), "minutes": round((time.time() - t0) / 60, 1)},
                           trace_dir=trace.ROOT)
        except (OSError, RuntimeError, KeyError):
            pass

    def heartbeat():
        while not stop.wait(5):
            render()

    threading.Thread(target=heartbeat, daemon=True).start()

    def tick(fn):
        def run(x):
            try:
                return fn(x)
            finally:
                ctx["n"] += 1
        return run

    # warm start: everything already cached joins the graph (cost: only verification refresh, if stale)
    warm = [p for p in (fetcher.fetch(u) for u in known_urls()) if p is not None and len(p.text) >= 200]
    ctx.update(phase="warm start: verifying cached pages", n=0, of=len(warm))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for p, res in zip(warm, pool.map(tick(lambda p: _safe(p, ex, ve)), warm), strict=True):
            if res:
                gb.add_page(p, *res, ex.version, ve.version)
                fr.visited.add(p.url)
                fr.note_links(p)
                d = registrable(p.url)
                if d in fr.domains:
                    fr.domains[d]["pages"] += 1
                dups.is_dup(host(p.url), p.text)
    first_page: dict[str, object] = {}
    for p in warm:
        first_page.setdefault(registrable(p.url), p)
    gb.finalize()
    history: list[dict] = []
    if resume and STATE.exists():
        st = json.loads(STATE.read_text())
        fr.restore(st)
        history = st.get("stats", {}).get("history", [])
        ctx.update(history=history, base=history[-1]["pages"] if history else 0)
        orgs = {e["domain"]: e for e in gb.entities.values() if e["type"] == "org" and e.get("domain")}
        purged = 0
        for d, sd in fr.domains.items():
            if d in fr.seed_domains:
                continue
            org = orgs.get(d)
            relevant = org is not None and (org.get("org_kind") in AI_KINDS or org.get("layer") in AI_LAYERS)
            if not domain_ok(d) or (org is not None and not relevant) or (org is None and len(fr.cites.get(d, ())) < 3):
                purged += bool(sd["queue"])
                sd["queue"] = []
        console.print(f"purged queues of {purged} non-relevant domains")
        console.print(f"resumed: {len(fr.domains)} domains, {len(fr.visited)} visited, {len(history)} earlier batches")
    # expand only domains never expanded before (a resumed frontier keeps its queues): cheap restarts
    warm_doms = [d for d in first_page if d in fr.domains and not fr.domains[d]["expanded"]]
    ctx.update(phase="warm start: expanding new domains (best pages + sitemaps)", n=0, of=len(warm_doms))
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(tick(lambda d: fr.expand(d, first_page[d], fetcher)), warm_doms))
    console.print(f"warm start: {len(warm)} cached pages, {len(gb.entities)} entities")

    done, errors, consecutive, last_error, finished = 0, 0, 0, None, False
    base_pages = history[-1]["pages"] if history else 0      # resumed runs keep counting

    def checkpoint():
        fr.save({"history": history, "noise": dict(noise), "generic": dict(gb.noise), "errors": errors,
                 "last_error": last_error, "finished": finished})
        ctx.update(history=history, base=base_pages, errors=errors, last_error=last_error, finished=finished,
                   phase="finished" if finished else "between batches: ranking + discovering domains", n=0, of=0)
        render()

    while done < budget:
        try:
                s = scores(to_graph(gb.entities, list(gb.edges.values())), seed_ids)
                ppr = {k: v["ppr"] for k, v in s.items()}
                # discover new org domains from the graph (boundary: no customers/adopters, no blocked domains)
                for e in gb.entities.values():
                    dom = e.get("domain")
                    if (e["type"] == "org" and dom and dom not in fr.domains
                            and (e.get("org_kind") in AI_KINDS or e.get("layer") in AI_LAYERS)):   # positive AI relevance
                        fr.add_domain(dom, e["id"])
                # dynamic lookup: AI-relevant orgs without a known site, highest PPR first
                todo_orgs = sorted((e for e in gb.entities.values()
                                    if e["type"] == "org" and not e.get("domain") and e["id"] not in fr.resolve_tried
                                    and (e.get("org_kind") in AI_KINDS or e.get("layer") in AI_LAYERS)),
                                   key=lambda e: -ppr.get(e["id"], 0.0))[:30]
                fr.resolve_tried |= {e["id"] for e in todo_orgs}   # mark first: a failure must not retry forever
                if todo_orgs:
                    ctx.update(phase=f"batch {len(history) + 1}: resolving sites for AI orgs", n=0, of=len(todo_orgs))
                    with ThreadPoolExecutor(max_workers=12) as pool:
                        found = list(pool.map(tick(lambda e: _resolve_domain(fetcher, e["name"])), todo_orgs))
                    for e, dom in zip(todo_orgs, found, strict=True):
                        fr.resolve_tried.add(e["id"])
                        if dom:
                            gb.entities[e["id"]]["domain"] = dom
                            if fr.add_domain(dom, e["id"]):
                                noise["resolved_sites"] += 1
                org_by_domain = {e["domain"]: e["id"] for e in gb.entities.values() if e["type"] == "org" and e.get("domain")}
                for dom, pubs in fr.cites.items():
                    if len(pubs) >= 3 and dom not in fr.domains:
                        fr.add_domain(dom, org_by_domain.get(dom))
                picks = fr.pick(ppr, min(batch, budget - done))
                if not picks:
                    console.print("[yellow]frontier exhausted[/]")
                    break
                # fetch in parallel across hosts
                ctx.update(phase=f"batch {len(history) + 1}: fetching", n=0, of=len(picks))
                with ThreadPoolExecutor(max_workers=16) as pool:
                    pages = list(pool.map(lambda du: (du[0], fetcher.fetch(du[1]) if url_ok(du[1], urlparse(du[1]).path) else None), picks))
                todo = []
                for (d, u), (_, p) in zip(picks, pages, strict=True):
                    if not url_ok(u, urlparse(u).path):
                        noise["skipped_url"] += 1
                        trace.event("pages", {"url": u, "domain": d, "gate": "skipped_url"})
                        continue
                    if p is None:
                        noise["fetch_failed"] += 1
                        trace.event("pages", {"url": u, "domain": d, "gate": "fetch_failed"})
                        continue
                    fr.note_links(p)
                    fr.expand(d, p, fetcher)                   # first page of a domain → queue its best pages
                    if len(p.text) < 400:
                        noise["thin"] += 1
                        trace.event("pages", {"url": u, "domain": d, "gate": "thin", "chars": len(p.text)})
                        continue
                    if dups.is_dup(host(p.url), p.text):
                        noise["near_duplicate"] += 1
                        trace.event("pages", {"url": u, "domain": d, "gate": "near_duplicate"})
                        continue
                    todo.append((d, p))
                ctx.update(phase=f"batch {len(history) + 1}: extracting + verifying", n=0, of=len(todo))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    results = list(pool.map(tick(lambda dp: _safe(dp[1], ex, ve)), todo))
                new_edges = 0
                for (d, p), res in zip(todo, results, strict=True):
                    if res:
                        added = gb.add_page(p, *res, ex.version, ve.version)
                        new_edges += added
                        fr.domains[d]["pages"] += 1
                        done += 1
                        ctx["done"] = done
                        ext, verdicts = res
                        trace.event("pages", {"url": p.url, "domain": d, "gate": "extracted", "chars": len(p.text),
                                              "entities": len(ext.entities), "triples": len(ext.triples),
                                              "unquoted_dropped": ext.dropped_unquoted,
                                              "verified": sum(1 for v in verdicts if v is not None and v.entailed),
                                              "rejected": sum(1 for v in verdicts if v is not None and not v.entailed),
                                              "new_edges": added})
                    else:
                        trace.event("pages", {"url": p.url, "domain": d, "gate": "llm_failed"})
                gb.finalize()
                row = {"pages": base_pages + done, "entities": len(gb.entities), "edges": len(gb.edges), "new_edges": new_edges,
                       "domains_known": len(fr.domains), "spend": round(LLM.spent_usd - spend0, 3),
                       "minutes": round((time.time() - t0) / 60, 1)}
                history.append(row)
                console.print(f"  {row}  noise={dict(noise)}")
                checkpoint()
        except BudgetExceeded as e:
            console.print(f"[red]budget stop:[/] {e}")
            last_error = f"budget: {e}"
            break
        except KeyboardInterrupt:
            console.print("[yellow]interrupted: state saved; continue with --resume[/]")
            last_error = "interrupted"
            break
        except Exception as e:  # noqa: BLE001 — deliberate: isolate ANY batch failure, checkpoint, carry on
            errors += 1
            consecutive += 1
            last_error = f"{type(e).__name__}: {str(e)[:200]}"
            console.print(f"[red]batch failed ({consecutive} in a row): {last_error}[/]")
            checkpoint()
            if consecutive >= 3:
                console.print("[red]3 consecutive batch failures: stopping; fix and continue with --resume[/]")
                break
            continue
        consecutive = 0
    else:
        finished = True
    finished = finished or done >= budget
    checkpoint()
    stop.set()
    out = {"policy": policy, "pages_new": done, "entities": len(gb.entities), "edges": len(gb.edges),
           "domains_known": len(fr.domains), "domains_crawled": sum(1 for s in fr.domains.values() if s["pages"]),
           "noise": dict(noise), "generic_dropped": dict(gb.noise), "spend_usd": round(LLM.spent_usd - spend0, 3),
           "minutes": round((time.time() - t0) / 60, 1), "errors": errors, "last_error": last_error,
           "finished": finished, "history": history}
    fr.save(out)
    return out


def _safe(page, ex, ve):
    try:
        return extract_verify(page, ex, ve)
    except BudgetExceeded:
        raise                                   # stop the crawl; never mark pages as failed for a dead key
    except RuntimeError as e:
        console.print(f"[red]extract failed {page.url}: {str(e)[:90]}[/]")
        return None
