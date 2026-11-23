"""One change at a time: cumulative harness steps on FIXED tasks, each scored at every stage; judges on the last step.

    CF_LLM_BUDGET_USD=5 uv run python scripts/ablate_steps.py RUN_DIR [RUN_DIR ...]

Steps (switches in the condition name; answers cached, so step 0 reuses the earlier runs):
  S0  baseline                      closed_book · kg_rag · kg_agentic · kg_enrich
  S1  +reading  (reading-list slot) the same four, all with the new format so the comparison stays fair
  S2  +select   (importance + type spread, KEY facts)        kg_agentic · kg_enrich
  S3  +justify  (justified names, "also in the graph" list)  kg_agentic · kg_enrich
Per step: retrieved → grounded → used, utilisation, precision, outcome pass, per-object-type use, answer length.
Judges (GLM, persona + expert, both orders): S3 vs memory and S3 vs S0 per harness, raw; and length-matched for the
memory-first comparisons. Writes eval/experiments/ablate_steps/<stamp>/ and a ledger record.
"""

import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from judge_bias_check import length_match

from cf import config
from cf.agent.kg import KG
from cf.bench import agency as A
from cf.bench import guidance as G
from cf.bench import retrieval as R
from cf.eval.stats import bootstrap
from cf.llm.client import LLM

MODEL = "thinkingmachines/inkling-2-small"
STEPS = [("S0 baseline", ""), ("S1 +reading", "+reading"), ("S2 +select", "+reading+select"), ("S3 +justify", "+reading+select+justify")]
BASES = ["closed_book", "kg_rag", "kg_agentic", "kg_enrich"]


def cond(base: str, sfx: str, step: int) -> str:
    if base in ("closed_book", "kg_rag") and step >= 2:      # select/justify only change the agentic harnesses
        return base + "+reading"
    return base + sfx


def main(*run_dirs: str) -> None:
    tasks = [json.loads(x) for d in run_dirs for x in Path(d, "tasks.jsonl").read_text().split("\n") if x.strip()]
    kg = KG(version=tasks[0]["kb_version"])
    spend0 = LLM.spent_usd
    jobs = sorted({(t["id"], cond(b, sfx, i)) for t in tasks for i, (_, sfx) in enumerate(STEPS) for b in BASES},
                  key=lambda j: not j[1].startswith("closed_book"))     # drafts first
    q = {t["id"]: t for t in tasks}
    first = [j for j in jobs if j[1].startswith("closed_book")]
    rest = [j for j in jobs if not j[1].startswith("closed_book")]
    go = lambda j: {**A.answer(q[j[0]], MODEL, j[1], kg, 0), "task_id": j[0]}
    with ThreadPoolExecutor(6) as pool:
        runs = list(pool.map(go, first)) + list(pool.map(go, rest))
    by = {(r["task_id"], r["condition"]): r for r in runs if r.get("answer")}
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = config.EVAL / "experiments" / "ablate_steps" / stamp
    out.mkdir(parents=True, exist_ok=True)
    (out / "tasks.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks))
    (out / "runs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in runs))
    gold = {t["id"]: {"edges": t["gold"]["edges"], "entities": set(t["gold"]["entities"]), "anchors": set(t["gold"]["anchors"])} for t in tasks}
    rows = []
    for (tid, c), r in by.items():
        m = R.stage_metrics(kg, r, gold[tid])
        n = len(gold[tid]["entities"])
        rows.append({"task_id": tid, "condition": c, **m, "pass": round(m["used"] * n) >= min(3, n),
                     "chars": len(G._blind(r["answer"])), "read": len(r["answer"].get("read") or []),
                     "also": len(r.get("also_in_graph") or [])})
    (out / "stages.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))

    mean = lambda xs: (sum(xs) / len(xs)) if xs else None
    f = lambda x, d=2: "–" if x is None else f"{x:.{d}f}"
    L = [f"# One change at a time · {stamp} · {len(tasks)} fixed tasks · {MODEL.split('/')[-1]} · trial 0", "",
         "| Step | Condition | retrieved | grounded | used | utilisation | precision | pass | read items | chars |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for i, (name, sfx) in enumerate(STEPS):
        for b in BASES:
            c = cond(b, sfx, i)
            xs = [x for x in rows if x["condition"] == c]
            if i >= 2 and b in ("closed_book", "kg_rag"):
                continue
            L.append(f"| {name} | {b} | {f(mean([x['retrieved'] for x in xs]))} | {f(mean([x['grounded'] for x in xs if x['grounded'] is not None]))} | "
                     f"{f(mean([x['used'] for x in xs]))} | {f(mean([x['utilisation'] for x in xs if x['utilisation'] is not None]))} | "
                     f"{f(mean([x['precision'] for x in xs if x['precision'] is not None]))} | {f(mean([float(x['pass']) for x in xs]))} | "
                     f"{f(mean([x['read'] for x in xs]), 1)} | {f(mean([x['chars'] for x in xs]), 0)} |")
    types = sorted({t for x in rows for t in x["by_type"]})
    L += ["", "## Used in the answer, by object type (share of gold objects of that type)", "",
          "| Step | Condition | " + " | ".join(types) + " |", "|---|---|" + "---|" * len(types)]
    for i, (name, sfx) in enumerate(STEPS):
        for b in ("kg_agentic", "kg_enrich", "closed_book"):
            if i >= 2 and b == "closed_book":
                continue
            c = cond(b, sfx, i)
            cells = []
            for t in types:
                g = sum(x["by_type"][t][0] for x in rows if x["condition"] == c and t in x["by_type"])
                u = sum(x["by_type"][t][2] for x in rows if x["condition"] == c and t in x["by_type"])
                cells.append(f"{u / g:.2f}" if g else "–")
            L.append(f"| {name} | {b} | " + " | ".join(cells) + " |")

    # judges on the final step
    last, sfx = len(STEPS) - 1, STEPS[-1][1]
    comps = [("memory-first S3 vs memory S3", cond("kg_enrich", sfx, last), cond("closed_book", sfx, last), False),
             ("agentic S3 vs memory S3", cond("kg_agentic", sfx, last), cond("closed_book", sfx, last), False),
             ("memory-first S3 vs memory-first S0", cond("kg_enrich", sfx, last), "kg_enrich", False),
             ("agentic S3 vs agentic S0", cond("kg_agentic", sfx, last), "kg_agentic", False),
             ("memory-first S3 vs memory S3 (length-matched)", cond("kg_enrich", sfx, last), cond("closed_book", sfx, last), True),
             ("memory-first S3 vs memory-first S0 (length-matched)", cond("kg_enrich", sfx, last), "kg_enrich", True)]
    pj = []
    for name, cx, cy, lm in comps:
        for t in tasks:
            x, y = by.get((t["id"], cx)), by.get((t["id"], cy))
            if x and y:
                a, b = (length_match(x["answer"], y["answer"]) if lm else (x["answer"], y["answer"]))
                pj.append((name, t, a, b))
    with ThreadPoolExecutor(6) as pool:
        prefs = list(pool.map(lambda p: {"comparison": p[0], "task_id": p[1]["id"], **A.pairwise(
            ["z-ai/glm-5.3"], ["persona", "expert"], p[1], p[2], p[3], G.fact_sheet(kg, p[2], p[3]))}, pj))
    (out / "pairwise.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in prefs))
    grp = defaultdict(list)
    for p in prefs:
        grp[p["comparison"]].append(p["p_x"])
    L += ["", "## Judges on the final step (GLM, persona + expert, both orders)", "", "| Comparison | n | P(first preferred) [95% CI] |", "|---|---|---|"]
    for name, *_ in comps:
        v = grp.get(name)
        if v:
            b = bootstrap(v)
            L.append(f"| {name} | {len(v)} | {b[0]:.2f} [{b[1]:.2f}–{b[2]:.2f}] |")
    spend = round(LLM.spent_usd - spend0, 4)
    L.insert(1, f"Spend ${spend}.")
    rep = "\n".join(L) + "\n"
    (out / "report.md").write_text(rep)
    with (config.EVAL / "experiments.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": stamp, "level": "ablate-steps", "dir": str(out), "tasks": len(tasks), "spend_usd": spend,
                             "from": list(run_dirs)}) + "\n")
    print(rep)
    print(f"→ {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
