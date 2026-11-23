"""Retrieval → grounding → use, per condition, on the showcase questions with question-aware gold.

    CF_LLM_BUDGET_USD=1 uv run python scripts/eval_retrieval.py [BEFORE_RUN_DIR]

Conditions: closed_book (no retrieval) · kg_rag (one retrieval pass, context packed into the prompt) · kg_tools
(plain tool loop) · kg_agentic (harness v3) · kg_enrich (memory-first v2). BEFORE_RUN_DIR adds the earlier
harness versions' runs on the same questions (agentic v2, enrich v1) as a before/after control.
Writes eval/experiments/retrieval_eval/<stamp>/{runs.jsonl, stages.jsonl, report.md}; appends to the ledger.
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
from cf.bench import retrieval as R
from cf.llm.client import LLM

CFG = "configs/experiments/showcase_questions.yaml"
ORDER = ["closed_book", "kg_rag", "kg_tools", "kg_agentic@v2", "kg_agentic@v3", "kg_agentic", "kg_enrich@v1", "kg_enrich@v2",
         "kg_enrich"]
LABEL = {"closed_book": "memory (no retrieval)", "kg_rag": "typical RAG (one pass, packed context)",
         "kg_tools": "plain tool loop", "kg_agentic@v2": "agentic v2 (start)", "kg_agentic@v3": "agentic v3 (+top, link, facts)",
         "kg_agentic": "agentic v4 (+broader, twins)", "kg_enrich@v1": "memory-first v1 (start)",
         "kg_enrich@v2": "memory-first v2 (+explore, facts)", "kg_enrich": "memory-first v3 (+broader, twins)"}


def main(*before: str) -> None:
    """before: earlier run folders as DIR=AGENTIC_TAG,ENRICH_TAG (e.g. .../20261122-0559=v2,v1)."""
    cfg = yaml.safe_load(Path(CFG).read_text())
    kg = KG()
    m = cfg["model"]
    tasks = [{"id": q["id"], "persona": q["persona"], "anchor": q["anchor"], "question": q["question"], "kb_version": kg.kb_version,
              "salient": G.salient(kg, q["anchor"]), "stratum": "hand-written", "split": "showcase"} for q in cfg["questions"]]
    golds = {q["id"]: R.gold(kg, q["gold"]) for q in cfg["questions"]}
    spend0 = LLM.spent_usd
    conds = [c for c in cfg["conditions"] if c != "closed_book"]
    with ThreadPoolExecutor(6) as pool:
        runs = list(pool.map(lambda t: {**A.answer(t, m, "closed_book", kg), "task_id": t["id"]}, tasks))
        runs += list(pool.map(lambda tc: {**A.answer(tc[0], m, tc[1], kg), "task_id": tc[0]["id"]},
                              [(t, c) for t in tasks for c in conds]))
    for spec in before:
        d, _, tags = spec.partition("=")
        ta, te = (tags.split(",") + ["", ""])[:2]
        for line in Path(d, "runs.jsonl").read_text().split("\n"):
            if line.strip() and (r := json.loads(line))["condition"] in ("kg_agentic", "kg_enrich"):
                tag = ta if r["condition"] == "kg_agentic" else te
                runs.append({**r, "condition": f"{r['condition']}@{tag}"})
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = config.EVAL / "experiments" / "retrieval_eval" / stamp
    out.mkdir(parents=True, exist_ok=True)
    (out / "runs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in runs))
    rows = [{"task_id": r["task_id"], "condition": r["condition"], **R.stage_metrics(kg, r, golds[r["task_id"]])}
            for r in runs if r.get("answer")]
    (out / "stages.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))
    spend = round(LLM.spent_usd - spend0, 4)

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return f"{sum(xs) / len(xs):.2f}" if xs else "–"
    by = defaultdict(list)
    for x in rows:
        by[x["condition"]].append(x)
    L = [f"# Retrieval → grounding → use · {stamp} · KB `{kg.kb_version}` · {m.split('/')[-1]} · spend ${spend}", "",
         ("Gold = the graph facts that answer each question (question-aware; see `cf/bench/retrieval.py`). Means over "
         f"{len(tasks)} questions."), "",
         "| Condition | retrieved | grounded (findings) | used (answer) | utilisation | precision | doubt phrases | tool calls | $ |",
         "|---|---|---|---|---|---|---|---|---|"]
    for c in ORDER:
        xs = by.get(c)
        if xs:
            L.append(f"| {LABEL[c]} | {mean([x['retrieved'] for x in xs])} | {mean([x['grounded'] for x in xs])} | "
                     f"{mean([x['used'] for x in xs])} | {mean([x['utilisation'] for x in xs])} | {mean([x['precision'] for x in xs])} | "
                     f"{mean([x['doubt'] for x in xs])} | {mean([x['steps'] for x in xs])} | {mean([x['cost'] for x in xs])} |")
    L += ["", "## Per question (retrieved / used)", "", "| Question | " + " | ".join(LABEL[c] for c in ORDER if c in by) + " |",
          "|---|" + "---|" * len([c for c in ORDER if c in by])]
    for t in tasks:
        cells = []
        for c in ORDER:
            if c not in by:
                continue
            x = next((x for x in by[c] if x["task_id"] == t["id"]), None)
            cells.append(f"{x['retrieved']:.2f} / {x['used']:.2f}" if x else "–")
        L.append(f"| {t['id']} (gold {len(golds[t['id']]['entities'])}) | " + " | ".join(cells) + " |")
    rep = "\n".join(L) + "\n"
    (out / "report.md").write_text(rep)
    with (config.EVAL / "experiments.jsonl").open("a") as f:
        f.write(json.dumps({"ts": stamp, "level": "retrieval-eval", "dir": str(out), "model": m, "spend_usd": spend,
                            "before": list(before), "conditions": sorted(by)}) + "\n")
    print(rep)
    print(f"→ {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
