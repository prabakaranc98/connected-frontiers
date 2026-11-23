"""Answer hand-written showcase questions three ways and score them with the cheap checklist scorers.

    CF_LLM_BUDGET_USD=1 uv run python scripts/run_showcase_questions.py [configs/experiments/showcase_questions.yaml]

Writes eval/experiments/showcase_questions/<stamp>/{tasks,runs,checklist}.jsonl, report.md and showcase.html,
and appends a ledger record. Answers are cached like every agency run (eval/cache/agency).
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml

from cf import config
from cf.agent.kg import KG
from cf.bench import agency as A
from cf.bench import checklist as C
from cf.bench import guidance as G
from cf.llm.client import LLM


def main(cfg_path: str = "configs/experiments/showcase_questions.yaml") -> None:
    cfg = yaml.safe_load(Path(cfg_path).read_text())
    kg = KG()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = config.EVAL / "experiments" / "showcase_questions" / stamp
    out.mkdir(parents=True, exist_ok=True)
    tasks = []
    for q in cfg["questions"]:
        if q["anchor"] not in kg.ents:
            raise SystemExit(f"anchor {q['anchor']} not in KB {kg.kb_version}")
        tasks.append({"id": q["id"], "persona": q["persona"], "anchor": q["anchor"], "question": q["question"],
                      "kb_version": kg.kb_version, "salient": G.salient(kg, q["anchor"]), "stratum": "hand-written",
                      "expect": q["expect"], "split": "showcase"})
    (out / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    m, spend0 = cfg["model"], LLM.spent_usd
    with ThreadPoolExecutor(6) as pool:            # closed book first: kg_enrich revises that exact answer
        runs = list(pool.map(lambda t: {**A.answer(t, m, "closed_book", kg), "task_id": t["id"]}, tasks))
        rest = [(t, c) for t in tasks for c in cfg["conditions"] if c != "closed_book"]
        runs += list(pool.map(lambda tc: {**A.answer(tc[0], m, tc[1], kg), "task_id": tc[0]["id"]}, rest))
    (out / "runs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in runs))
    ok = [r for r in runs if r.get("answer")]
    rows, _ = A.run_checklist({"scorers": cfg["checklist_scorers"], "unit_tests": False}, tasks, ok, kg)
    (out / "checklist.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    spend = round(LLM.spent_usd - spend0, 4)
    L = [f"# Showcase questions · {stamp} · KB `{kg.kb_version}` · {m.split('/')[-1]} · spend ${spend}", "",
         "| Question | Expect | Condition | named | in graph | key entities found | findings | changes | evidence reads | jev | $ |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    jev = {(r["task_id"], r["condition"]): r["items"] for r in rows if r["scorer"] == "jev"}
    for t in tasks:
        for r in [x for x in ok if x["task_id"] == t["id"]]:
            mt = r["metrics"] or {}
            j = jev.get((t["id"], r["condition"])) or {}
            jv = [v for v in j.values() if v is not None]
            L.append(f"| {t['id']} | {t['expect'].split(' (')[0]} | {r['condition']} | {mt.get('named')} | {mt.get('in_kb')} | "
                     f"{mt.get('salient_coverage')} | {mt.get('findings', '–')} | {mt.get('changes', '–')} | "
                     f"{mt.get('evidence_reads', '–')} | {sum(jv) / len(jv):.2f} | {r.get('cost_usd', 0):.3f} |" if jv else
                     f"| {t['id']} | – | {r['condition']} | – | – | – | – | – | – | – | – |")
    L += ["", C.report(rows)]
    (out / "report.md").write_text("\n".join(L))
    with (config.EVAL / "experiments.jsonl").open("a") as f:
        f.write(json.dumps({"ts": stamp, "level": "agency-showcase", "name": "showcase_questions", "dir": str(out),
                            "model": m, "spend_usd": spend, "runs": len(runs), "ok": len(ok)}) + "\n")
    print("\n".join(L[:4 + len(ok)]))
    print(f"→ {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
