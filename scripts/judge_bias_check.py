"""Re-judge a use-case run's cached answers to test the headline preferences against two biases.

    CF_LLM_BUDGET_USD=1 uv run python scripts/judge_bias_check.py eval/experiments/usecases_v1/<stamp>

1. second judge family: the same comparisons judged by Nemotron (the run used GLM)
2. length-matched: both answers cut to the same structure and size before GLM judges them (memory-first answers were
   46% longer than memory answers): same number of learning items, projects, experiments and stack items, and each
   text field cut to the shorter answer's length at a word boundary.
Writes bias_check.jsonl and bias_check.md into the run folder and appends to the ledger.
"""

import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml

from cf import config
from cf.agent.kg import KG
from cf.bench import agency as A
from cf.bench import guidance as G
from cf.eval.stats import bootstrap
from cf.llm.client import LLM

COMPS = ["memory-first vs memory", "agentic vs memory", "small memory-first vs large memory"]


def _cut(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0] + "…"


def length_match(a: dict, b: dict) -> tuple[dict, dict]:
    a, b = json.loads(json.dumps(a)), json.loads(json.dumps(b))
    for k in ("learn", "stack", "projects", "experiments"):
        n = min(len(a.get(k) or []), len(b.get(k) or []))
        a[k], b[k] = (a.get(k) or [])[:n], (b.get(k) or [])[:n]
    a["summary"], b["summary"] = (_cut(a.get("summary", ""), m := min(len(a.get("summary", "")), len(b.get("summary", "")))),
                                  _cut(b.get("summary", ""), m))
    for i in range(len(a["learn"])):
        m = min(len(a["learn"][i]), len(b["learn"][i]))
        a["learn"][i], b["learn"][i] = _cut(a["learn"][i], m), _cut(b["learn"][i], m)
    for k, fields in (("projects", ("what", "first_step")), ("experiments", ("question", "baseline", "change", "measure"))):
        for i in range(len(a[k])):
            for f in fields:
                m = min(len(a[k][i].get(f, "")), len(b[k][i].get(f, "")))
                a[k][i][f], b[k][i][f] = _cut(a[k][i].get(f, ""), m), _cut(b[k][i].get(f, ""), m)
            n = min(len(a[k][i].get("stack") or []), len(b[k][i].get("stack") or [])) if k == "projects" else 0
            if k == "projects":
                a[k][i]["stack"], b[k][i]["stack"] = (a[k][i].get("stack") or [])[:n], (b[k][i].get("stack") or [])[:n]
    return a, b


def main(run_dir: str) -> None:
    d = Path(run_dir)
    tasks = [json.loads(x) for x in (d / "tasks.jsonl").read_text().split("\n") if x.strip()]
    runs = [json.loads(x) for x in (d / "runs.jsonl").read_text().split("\n") if x.strip()]
    cfg = yaml.safe_load((config.ROOT / "configs" / "experiments" / f"{d.parent.name}.yaml").read_text())
    kg = KG(version=tasks[0]["kb_version"])
    by = {(r["task_id"], r["model"], r["condition"]): r for r in runs if r.get("answer") and r.get("trial", 0) == 0}
    comps = [c for c in cfg["comparisons"] if c["name"] in COMPS]
    jobs = []
    for c in comps:
        for t in tasks:
            x, y = by.get((t["id"], c["x"]["model"], c["x"]["condition"])), by.get((t["id"], c["y"]["model"], c["y"]["condition"]))
            if x and y:
                jobs.append(("nemotron", c["name"], t, x["answer"], y["answer"], ["nvidia/nemotron-3.5-super-vl"]))
                lx, ly = length_match(x["answer"], y["answer"])
                jobs.append(("length-matched (GLM)", c["name"], t, lx, ly, ["z-ai/glm-5.3"]))
    spend0 = LLM.spent_usd

    def go(j):
        check, name, t, a, b, judges = j
        return {"check": check, "comparison": name, "task_id": t["id"], "usecase": t["usecase"],
                "chars": [len(G._blind(a)), len(G._blind(b))],
                **A.pairwise(judges, ["persona", "expert"], t, a, b, G.fact_sheet(kg, a, b))}
    with ThreadPoolExecutor(6) as pool:
        rows = list(pool.map(go, jobs))
    orig = defaultdict(list)
    for x in (d / "pairwise.jsonl").read_text().split("\n"):
        if x.strip() and (p := json.loads(x))["comparison"] in COMPS:
            orig[p["comparison"]].append(p["p_x"])
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    (d / "bias_check.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    spend = round(LLM.spent_usd - spend0, 4)
    L = [f"# Judge bias check · {d.parent.name}/{d.name} · {stamp} · spend ${spend}", "",
         "P(first answer preferred), both orders × persona and expert roles; 95% task-bootstrap interval.", "",
         "| Comparison | GLM (original) | Nemotron (second family) | GLM, length-matched | chars after matching (x / y) |",
         "|---|---|---|---|---|"]
    fmt = lambda v: f"{(b := bootstrap(v))[0]:.2f} [{b[1]:.2f}–{b[2]:.2f}]" if v else "–"
    for c in COMPS:
        nm = [r["p_x"] for r in rows if r["comparison"] == c and r["check"] == "nemotron"]
        lm = [r for r in rows if r["comparison"] == c and r["check"].startswith("length")]
        ch = (f"{sum(r['chars'][0] for r in lm) // max(len(lm), 1)} / {sum(r['chars'][1] for r in lm) // max(len(lm), 1)}" if lm else "–")
        L.append(f"| {c} | {fmt(orig[c])} | {fmt(nm)} | {fmt([r['p_x'] for r in lm])} | {ch} |")
    rep = "\n".join(L) + "\n"
    (d / "bias_check.md").write_text(rep)
    with (config.EVAL / "experiments.jsonl").open("a") as f:
        f.write(json.dumps({"ts": stamp, "level": "judge-bias-check", "of": str(d), "spend_usd": spend}) + "\n")
    print(rep)


if __name__ == "__main__":
    main(sys.argv[1])
