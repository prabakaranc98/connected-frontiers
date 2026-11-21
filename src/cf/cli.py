"""`cf` command line. Commands map one-to-one to milestones in docs/DESIGN.md §7."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from cf import config

app = typer.Typer(help="Connected Frontiers: crawl → rank → reason → visualize.", no_args_is_help=True)
console = Console()


def _todo(milestone: str, what: str) -> None:
    console.print(f"[yellow]not built yet[/] — {what} lands at milestone [bold]{milestone}[/] "
                  "(docs/DESIGN.md §7). Phase 1 gate first: see PROBLEM.md.")
    raise typer.Exit(code=2)


@app.command()
def doctor() -> None:
    """Check keys (presence only), configs and folders."""
    t = Table(title="cf doctor", show_header=True)
    t.add_column("check")
    t.add_column("status")

    for key, required in [("OPENROUTER_API_KEY", True), ("HF_TOKEN", False)]:
        ok = config.is_set(key)
        hf_cached = key == "HF_TOKEN" and (Path.home() / ".cache/huggingface/token").exists()
        status = "[green]set[/]" if ok else ("[green]cached login[/]" if hf_cached
                                             else "[red]missing[/]" if required else "[yellow]missing (optional)[/]")
        t.add_row(key, status)

    for name in ["seeds.yaml", "crawl.yaml", "eval.yaml", "evidence.yaml"]:
        try:
            config.load_yaml(name)
            t.add_row(f"configs/{name}", "[green]ok[/]")
        except Exception as e:  # noqa: BLE001
            t.add_row(f"configs/{name}", f"[red]{type(e).__name__}[/]")

    for d in [config.DATA / "raw", config.EVAL / "gold"]:
        t.add_row(str(d.relative_to(config.ROOT)), "[green]ok[/]" if d.exists() else "[red]missing[/]")

    console.print(t)


@app.command()
def scout(seed: list[str] = typer.Option(["all"], help="seed name(s) from configs/seeds.yaml, or 'all'"),
          pages: int = typer.Option(5, help="pages per seed site (hop 1)"),
          hop2_orgs: int = typer.Option(6, help="top-PPR orgs to follow to their own sites"),
          hop2_pages: int = typer.Option(1, help="extra pages per hop-2 org"),
          workers: int = typer.Option(6, help="parallel extract+verify jobs"),
          open_browser: bool = typer.Option(True, "--open/--no-open")) -> None:
    """Small real run: fetch → extract → verify → grade → rank → explorer.html (not the eval)."""
    import webbrowser

    from cf.scout import run_scout

    known = {s["name"]: s for s in config.load_yaml("seeds.yaml")["seeds"]
             if s.get("domain") and s.get("status") != "placeholder"}
    names = list(known) if seed == ["all"] else seed
    missing = [n for n in names if n not in known]
    if missing:
        raise typer.BadParameter(f"unknown seed(s) {missing}; have {list(known)}")
    rep = run_scout([known[n] for n in names], pages, hop2_orgs, hop2_pages, workers)
    ok = [p for p in rep.pages if "triples" in p]
    console.rule("[bold]Scout summary")
    console.print(f"pages read: {len(ok)} · triples kept: {sum(p['triples'] for p in ok)} · "
                  f"unquoted dropped: {sum(p['dropped_unquoted'] for p in ok)} · "
                  f"verifier rejected: {sum(p['verifier_rejected'] for p in ok)} · "
                  f"LLM spend: ${rep.spent_usd:.4f}")
    out = Path(rep.out_dir) / "explorer.html"
    console.print(f"explorer: {out}")
    if open_browser:
        webbrowser.open(out.as_uri())


@app.command()
def build(er: bool = typer.Option(True, "--er/--no-er", help="run entity resolution"),
          note: str = typer.Option("", help="note stored in the KB manifest"),
          open_browser: bool = typer.Option(False, "--open/--no-open")) -> None:
    """Rebuild the graph from cached extractions (+ entity resolution) → data/processed/graph/."""
    import json
    import webbrowser

    from cf.build import OUT
    from cf.build import build as run_build
    from cf.report import write as write_report

    seeds = [s for s in config.load_yaml("seeds.yaml")["seeds"]
             if s.get("domain") and s.get("status") != "placeholder"]
    model = config.env("CF_MODEL_VERIFY") if er else None
    summary = run_build(seeds, model)
    console.print_json(json.dumps({k: v for k, v in summary.items() if k != "er"}))
    if summary.get("er"):
        er_s = summary["er"]
        console.print(f"[bold]ER:[/] {er_s['auto_merges']} auto · {er_s['llm_same']} same · "
                      f"{er_s['llm_hierarchy']} hierarchy · {er_s['llm_different']} different")
        for canon, members in list(er_s["groups"].items())[:20]:
            console.print(f"  merged  {canon}  ←  {', '.join(m.split(':', 1)[1] for m in members)}")
        for h in er_s["hierarchy"][:20]:
            console.print(f"  linked  {h}")
    _, md = write_report()
    from cf.docs import build as build_docs
    from cf.kb import snapshot
    console.print(f"docs index: {build_docs()}")
    man = snapshot(note)
    console.print(f"[bold green]KB snapshot {man['version']}[/] (parent {man['parent']}) → data/kb/{man['version']}/ · now CURRENT")
    console.print(md.split("## Verifier reject rate")[0])
    console.print(f"explorer: {OUT / 'explorer.html'}  ·  report: {OUT / 'report.md'}")
    if open_browser:
        webbrowser.open((OUT / "explorer.html").as_uri())


@app.command()
def silver(n_verify: int = typer.Option(200, help="verification items"),
           n_er: int = typer.Option(120, help="entity-resolution pairs"),
           version: str = typer.Option("v1")) -> None:
    """Silver labels by ensemble vote (4 judge models); measure the production verifier and ER."""
    import json

    from cf.eval.silver import run as run_silver

    s = run_silver(n_verify, n_er, version)
    console.print_json(json.dumps(s))
    console.print(f"files: eval/gold/silver_*_{version}.* · owner queue: eval/gold/owner_review_{version}.md")


@app.command()
def tasks(per_use_case: int = typer.Option(5), version: str = typer.Option("v0")) -> None:
    """Build use-case tasks with answer keys computed from the KG → eval/gold/tasks_<version>.jsonl."""
    from collections import Counter

    from cf.bench.tasks import build as build_tasks

    ts = build_tasks(per_use_case, version=version)
    console.print(f"{len(ts)} tasks: {dict(Counter(t['use_case'] for t in ts))} → eval/gold/tasks_{version}.jsonl")


@app.command()
def sessions(n: int = typer.Option(12), seed: int = typer.Option(11), version: str = typer.Option("s1")) -> None:
    """Build multi-turn sessions: graph-computed keys → Inkling writes → deterministic checks → Nemotron solver gate."""
    from collections import Counter

    from cf.bench import sessions as S
    from cf.llm.client import LLM

    acc, rej = S.build(n, seed)
    S.save(acc, version)
    S.save(rej, version + "_rejected")
    console.print(f"accepted {len(acc)} {dict(Counter(s['template'] for s in acc))} · rejected {len(rej)} · "
                  f"spend ${LLM.spent_usd:.3f} → eval/gold/sessions_{version}.jsonl")
    for r in rej:
        console.print(f"  [yellow]rejected[/] {r['template']} {r['anchors']}: {r['reasons']}")


@app.command("sessions-bench")
def sessions_bench(models: list[str] = typer.Option(None), conditions: list[str] = typer.Option(None),
                   version: str = typer.Option("s1")) -> None:
    """Run models on the multi-turn sessions (closed_book | kg_tools | oracle); per-turn scores → reports/."""
    from cf.bench import sessions as S
    from cf.bench.run import MODELS

    ms = {m: MODELS.get(m, 'auto') for m in models} if models else MODELS
    _, md = S.bench(ms, conditions or ["closed_book", "kg_tools", "oracle"], version)
    console.print(md)


@app.command()
def bench(models: list[str] = typer.Option(None, help="OpenRouter model ids (default: the recent small set)"),
          conditions: list[str] = typer.Option(None, help="closed_book | kg_tools | oracle"),
          version: str = typer.Option("v0"), limit: int = typer.Option(0, help="first N tasks only (0 = all)")) -> None:
    """Run agents on the use-case tasks; write results + a leaderboard to reports/."""
    from cf.bench.run import CONDITIONS, MODELS
    from cf.bench.run import run as run_bench

    ms = {m: MODELS.get(m, 'auto') for m in models} if models else MODELS
    _, md = run_bench(ms, conditions or CONDITIONS, version, limit=limit or None)
    console.print(md)


@app.command()
def lookup(query: str, pages: int = typer.Option(3, help="pages to read if fetching live"),
           refresh: bool = typer.Option(False, help="ignore the KG and fetch live"),
           max_age: int = typer.Option(30, help="max evidence age (days) to answer from the KG")) -> None:
    """Dynamic lookup: from the KG if known and fresh, else fetch → extract → verify → grade now."""
    from cf.lookup import lookup as do_lookup

    r = do_lookup(query, pages, refresh, max_age)
    console.print(f"[bold]{r.get('entity') or r.get('site') or query}[/] · source: [cyan]{r['source']}[/]"
                  + (f" · {r['seconds']}s · ${r['cost_usd']}" if "seconds" in r else ""))
    if r.get("hint"):
        console.print(f"[yellow]{r['hint']}[/]")
        return
    t = Table(show_lines=False)
    for c in ("status", "head", "relation", "tail", "strength", "quote"):
        t.add_column(c, overflow="fold", max_width=48 if c == "quote" else None)
    colors = {"verified": "green", "corroborated": "blue", "confirmed": "yellow", "claimed": "dark_orange", "unsupported": "red"}
    for e in r["edges"]:
        st = e["status"]
        t.add_row(f"[{colors.get(st, 'white')}]{st}[/]", e["head"], e["relation"], e["tail"], f"{e['strength']:.2f}", e.get("quote", ""))
    console.print(t)


@app.command()
def cache() -> None:
    """What is cached, how fresh, what is stale for the current models/prompts, refresh cost."""
    import json

    from cf.cache import migrate_legacy, status
    from cf.extract.llm import LLMExtractor, make_verifier
    from cf.llm.client import role_chain

    ex = LLMExtractor(role_chain("extract")[0])
    migrated = migrate_legacy(ex)
    s = status(ex, make_verifier())
    if migrated:
        console.print(f"[dim]migrated {migrated} legacy extractions into the split cache[/]")
    console.print_json(json.dumps(s))


@app.command("kb")
def kb_cmd(action: str = typer.Argument("list", help="list | show | diff | use"),
           a: str = typer.Argument(None), b: str = typer.Argument(None)) -> None:
    """Versioned KBs: list, show <v>, diff <v1> <v2>, use <v> (set CURRENT)."""
    import json

    from cf import kb

    if action == "list":
        t = Table()
        for c in ("version", "created_at", "entities", "edges", "verified_edges", "segments", "docs_chunks", "current"):
            t.add_column(c)
        for r in kb.list_versions():
            t.add_row(*(str(r.get(c, "")) for c in ("version", "created_at", "entities", "edges", "verified_edges", "segments", "docs_chunks", "current")))
        console.print(t)
    elif action == "show":
        console.print_json((kb.KB_ROOT / (a or kb.current()) / "manifest.json").read_text())
    elif action == "diff":
        console.print_json(json.dumps(kb.diff(a, b)))
    elif action == "use":
        (kb.KB_ROOT / "CURRENT").write_text(a)
        console.print(f"CURRENT = {a}")


@app.command()
def serve(port: int = typer.Option(8765)) -> None:
    """Local live dashboard for the crawl: http://127.0.0.1:<port> (localhost only)."""
    from cf.serve import serve as run_server

    console.print(f"crawl monitor → http://127.0.0.1:{port}")
    run_server(port)


@app.command()
def crawl(policy: str = typer.Option("ppr", help="ppr (priority = PPR of the domain's org) | bfs (discovery order)"),
          budget: int = typer.Option(200, help="NEW pages to extract this run"),
          batch: int = typer.Option(40), workers: int = typer.Option(8),
          seed_cap: int = typer.Option(10, help="max pages per seed domain"),
          new_cap: int = typer.Option(4, help="max pages per discovered domain"),
          max_usd: float = typer.Option(6.5, help="LLM budget guard for this run"),
          resume: bool = typer.Option(False, "--resume", help="continue from the last checkpoint"),
          show_status: bool = typer.Option(False, "--status", help="show checkpoint progress and exit (no cost)")) -> None:
    """Frontier crawl: domains discovered from the graph, prioritized by PPR, with noise gates.
    Checkpoints every batch; a failed batch is logged and skipped; --resume continues after a crash."""
    import json
    import os

    from cf.crawl.frontier import crawl as run_crawl
    from cf.crawl.frontier import status as crawl_status

    if show_status:
        console.print_json(json.dumps(crawl_status()))
        return

    os.environ["CF_LLM_BUDGET_USD"] = str(max_usd)
    seeds = [s for s in config.load_yaml("seeds.yaml")["seeds"] if s.get("domain") and s.get("status") != "placeholder"]
    out = run_crawl(seeds, budget, policy, batch, workers, seed_cap, new_cap, resume=resume)
    console.print_json(json.dumps({k: v for k, v in out.items() if k != "history"}))
    console.print("next: [bold]cf build[/] (ER, adapters, layout, report) → explorer")


@app.command()
def rank(seed: list[str] = typer.Option(None, help="entity names to personalize on")) -> None:
    """Score nodes: PageRank, personalized PageRank, HITS."""
    _todo("M3", "ranking")


@app.command()
def docs() -> None:
    """GraphRAG document layer: documents → chunks → links to edges and entities."""
    import json

    from cf.docs import build as build_docs

    console.print_json(json.dumps(build_docs()))


@app.command()
def ask(question: str, mode: str = typer.Option("kg_tools", help="graph_rag | kg_tools | closed_book"),
        model: str = typer.Option(None, help="default: role 'reason' in configs/models.yaml")) -> None:
    """Ask the KG a question; the answer cites edges and source passages."""
    from cf.agent.harness import run as run_agent
    from cf.agent.kg import KG
    from cf.llm.client import role_chain

    m = model or role_chain("reason")[0]
    r = run_agent(m, {"id": "ask", "use_case": "ask", "brief": question}, mode, KG())
    out = r["output"]
    console.print(f"[bold]{m}[/] · {mode} · {r['n_tool_calls']} tool calls · ${r['cost_usd']} · {r['latency_s']}s\n")
    console.print(out.get("answer") or out)


@app.command()
def viz() -> None:
    """Export the graph to the static explorer."""
    _todo("M6", "explorer")


@app.command("eval")
def eval_(suite: str = typer.Option("all", help="crawl | extract | resolve | linkpred | reason | all")) -> None:
    """Run the evaluation harness (EVAL.md)."""
    _todo("M1", f"eval suite={suite}")


@app.command()
def release(kb_version: str = typer.Option(None, "--kb", help="KB version (default CURRENT)"),
            push: bool = typer.Option(False, "--push", help="upload to Hugging Face (asks for the repo; private)"),
            repo: str = typer.Option(None, help="HF dataset repo id, e.g. <user>/connected-frontiers")) -> None:
    """Build the Hugging Face collection locally (kb · tasks · trajectories · labels); --push uploads privately."""
    import json

    from cf.release import build as build_release

    r = build_release(kb_version)
    console.print_json(json.dumps(r))
    if push:
        if not repo:
            raise typer.BadParameter("--push needs --repo <user>/<name>")
        from huggingface_hub import HfApi
        api = HfApi()
        api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
        api.upload_folder(folder_path=r["out"], repo_id=repo, repo_type="dataset",
                          commit_message=f"Connected Frontiers {r['version']}")
        console.print(f"[green]pushed (private)[/] → https://huggingface.co/datasets/{repo}")


if __name__ == "__main__":
    app()
