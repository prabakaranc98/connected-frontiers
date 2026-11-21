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
def crawl(policy: str = typer.Option("bfs", help="bfs | degree | pagerank | ppr_push | ppr_push_typed | ppr_push_bandit"),
          budget: int = typer.Option(200, help="max fetches")) -> None:
    """Constructor: crawl from configs/seeds.yaml with a frontier policy."""
    _todo("M1 (bfs) / M3 (ppr_push)", f"crawl policy={policy} budget={budget}")


@app.command()
def rank(seed: list[str] = typer.Option(None, help="entity names to personalize on")) -> None:
    """Score nodes: PageRank, personalized PageRank, HITS."""
    _todo("M3", "ranking")


@app.command()
def ask(question: str, system: str = typer.Option("R3", help="R0 no-graph | R1 page RAG | R2 PPR subgraph | R3 agent+tools")) -> None:
    """Reasoner: answer a question with cited evidence."""
    _todo("M5", f"reasoner {system}")


@app.command()
def viz() -> None:
    """Export the graph to the static explorer."""
    _todo("M6", "explorer")


@app.command("eval")
def eval_(suite: str = typer.Option("all", help="crawl | extract | resolve | linkpred | reason | all")) -> None:
    """Run the evaluation harness (EVAL.md)."""
    _todo("M1", f"eval suite={suite}")


@app.command()
def release(dry_run: bool = typer.Option(True, help="build locally, do not push")) -> None:
    """Build the Hugging Face dataset + benchmark (docs/DATASET.md)."""
    _todo("M6", "HF release")


if __name__ == "__main__":
    app()
