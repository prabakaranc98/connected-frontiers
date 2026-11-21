"""Run the use-case benchmark: models × conditions × tasks → results JSONL + leaderboard markdown."""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from statistics import mean

from rich.console import Console

from cf import config
from cf.agent.harness import run as run_agent
from cf.agent.kg import KG
from cf.bench.score import score
from cf.llm.client import AUTO, LLM

console = Console()
# Recent, small open-weight models (owner preference). Reasoning: tokens cap, 0 = off (Nemotron ignores caps).
MODELS = {"qwen/qwen3.5-35b-a3b": AUTO, "thinkingmachines/inkling-2-mini": AUTO,
          "nvidia/nemotron-3.5-lightning": AUTO, "mistralai/mistral-small-2603": AUTO}   # AUTO = configs/models.yaml profile
CONDITIONS = ["closed_book", "kg_tools", "oracle"]


def load_tasks(version: str = "v0") -> list[dict]:
    path = config.EVAL / "gold" / f"tasks_{version}.jsonl"
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


def run(models: dict[str, int | None], conditions: list[str], version: str = "v0", workers: int = 8,
        limit: int | None = None) -> tuple[list[dict], str]:
    kg = KG()
    tasks = load_tasks(version)[: limit or None]
    jobs = [(m, r, c, t) for m, r in models.items() for c in conditions for t in tasks]
    spend0 = LLM.spent_usd
    console.print(f"{len(tasks)} tasks × {len(models)} models × {len(conditions)} conditions = {len(jobs)} runs")

    def one(job):
        m, r, c, t = job
        res = run_agent(m, t, c, kg, reasoning=r)
        res["score"] = score(kg, t, res)
        return res

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, jobs))
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    out = config.EVAL / "results"
    out.mkdir(parents=True, exist_ok=True)
    with (out / f"bench_{version}_{stamp}.jsonl").open("w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    md = leaderboard(results, version, round(LLM.spent_usd - spend0, 4))
    (config.ROOT / "reports").mkdir(exist_ok=True)
    (config.ROOT / "reports" / f"{stamp}-bench-{version}.md").write_text(md)
    return results, md


def leaderboard(results: list[dict], version: str, spend: float) -> str:
    agg: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        agg[(r["model"], r["condition"])].append(r)
    ucs = sorted({r["use_case"] for r in results})
    rows = [f"# Benchmark {version}: use-case tasks over the KG", "",
            (f"{len({r['task_id'] for r in results})} tasks · spend ${spend} · rule-based scoring (no LLM judge). "
            "key_score per use case: U1 recall of key players · U2 precision@3 · U5 claim-label accuracy (3 buckets) · U6 nDCG@5."), "",
            "| model | condition | " + " | ".join(ucs) + " | mean | citation valid | tool calls | $/task | s/task |",
            "|---|---|" + "---|" * len(ucs) + "---|---|---|---|---|"]
    for (m, c), rs in sorted(agg.items(), key=lambda kv: (kv[0][1], -mean(x["score"]["key_score"] for x in kv[1]))):
        per = []
        for uc in ucs:
            xs = [x["score"]["key_score"] for x in rs if x["use_case"] == uc]
            per.append(f"{mean(xs):.2f}" if xs else "–")
        cv = [x["score"]["citation_valid"] for x in rs if x["score"].get("citation_valid") is not None]
        rows.append(f"| {m.split('/')[1]} | {c} | " + " | ".join(per) +
                    f" | **{mean(x['score']['key_score'] for x in rs):.2f}** | {(mean(cv) if cv else float('nan')):.2f} | "
                    f"{mean(x['n_tool_calls'] for x in rs):.1f} | {mean(x['cost_usd'] for x in rs):.4f} | {mean(x['latency_s'] for x in rs):.0f} |")
    return "\n".join(rows) + "\n"
