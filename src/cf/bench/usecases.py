"""End-to-end use-case testbed: generate task sets from the catalogue, answer them, score each stage.

    uv run cf usecases configs/experiments/usecases_v1.yaml

1. generate   for each use case (configs/usecases.yaml), sample anchors of its type from the KB in two strata (rich:
              ≥ 12 gold entities, thin: 4-11), fill the question template, have the Examiner (Gemma, a family neither
              tested nor judging) check the subject and rewrite the question in the persona's voice, reject leaks,
              and compute the question-aware gold from the use case's gold spec.
2. answer     every condition × model × trial (cached; closed-book first so memory-first revises the scored draft).
3. score      retrieval → grounding → use per run (cf.bench.retrieval), the typed checklist (code + Jev), and
              pairwise persona/expert judges on the configured comparisons (trial 0, both orders).
4. report     per use case and condition, with the spread across trials so noise is visible.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml

from cf import config
from cf.agent.kg import KG
from cf.bench import agency as A
from cf.bench import checklist as C
from cf.bench import guidance as G
from cf.bench import retrieval as R
from cf.eval.stats import bootstrap
from cf.llm.client import LLM, BudgetExceeded

RICH, THIN = 12, (4, 11)


def catalog() -> dict:
    return yaml.safe_load((config.ROOT / "configs" / "usecases.yaml").read_text())


def _fill(spec, anchor: str):
    if isinstance(spec, str):
        return spec.replace("{anchor}", anchor)
    if isinstance(spec, list):
        return [_fill(x, anchor) for x in spec]
    if isinstance(spec, dict):
        return {k: _fill(v, anchor) for k, v in spec.items()}
    return spec


# deterministic backstop for the LLM curator, which is not consistent (it accepted "engineering" as a job role and
# "AI agents" as a research direction in one run, and rejected the latter in another)
GENERIC = {"engineering", "research", "product", "design", "sales", "marketing", "operations", "ai agents", "agents",
           "ai", "machine learning", "deep learning", "robotics", "ai inference", "ai model training", "customer support",
           "llms", "generative ai", "data", "software", "infrastructure", "evaluation", "safety", "security"}


def _ok_name(n: str) -> bool:
    return (2 < len(n) <= 40 and not any(c in n for c in "|/\\{}[]") and len(n.split()) <= 5
            and n.strip().lower() not in GENERIC)


def candidates(kg: KG, uc: dict, seed: int, n: int) -> dict[str, list[dict]]:
    """Anchors of the use case's type, split by how much gold the graph holds for them; better-known first."""
    pool = [e for e in kg.ents.values() if e["type"] == uc["anchor_type"] and kg.degree(e["id"]) >= 3 and _ok_name(e["name"])]
    pool.sort(key=lambda e: -(e.get("pagerank") or 0))
    out = {"rich": [], "thin": []}
    for e in pool[:400]:
        g = R.gold(kg, _fill(uc["gold"], e["id"]))
        size = len(g["entities"])
        stratum = "rich" if size >= RICH else "thin" if THIN[0] <= size <= THIN[1] else None
        if stratum and len(out[stratum]) < n * 12:
            out[stratum].append({"anchor": e["id"], "gold_size": size})
    rng = random.Random(seed)
    for k in out:                                  # sample among the better-known half, so tasks are not all the top hubs
        head = out[k][: max(n * 10, 1)]
        rng.shuffle(head)
        out[k] = head
    return out


# The curator's question depends on the use case's intent. One question for all ("a meaningful subject to learn or
# build?") rejected every job role as "not a technical subject" (found 2026-11-22).
CURATE_BY_INTENT = {
    "career": "Is '{a}' a real job role at AI companies that this person could realistically aim for? Reject sales, "
              "legal and non-technical roles, and titles too generic to prepare for.",
    "adopt": "Is '{a}' something an engineer building LLM-based product features would realistically evaluate and adopt? "
             "Reject consumer brands, unrelated platforms and ambiguous names.",
    "deploy": "Is '{a}' a real organisation that could be an AI deployment customer, with enough public information to "
              "prepare for? Reject generic or ambiguous names.",
    "research": "Is '{a}' specific enough to be a PhD research direction (a problem with open questions), not a whole "
                "field, a business function or a buzzword?",
    "build": "Is '{a}' a real, specific model or dataset this person could fine-tune, build on or use? Reject internal "
             "test artefacts and ambiguous names.",
    "learn": "Is '{a}' a meaningful, specific technique this person could learn by implementing it? Reject generic words.",
}
# The curator must not judge existence from its own memory: it rejected Qwen3.8-27B, Claude Opus 5.5 and
# DeepSeek-V4.1-Flash as "not real" (its training cutoff; found 2026-11-22). Names come from a curated graph.
CURATE_ROLE = ("You check tasks for an evaluation of career and engineering guidance. The asker is: {label} ({background}). "
               "The subject comes from a curated knowledge graph of the AI ecosystem built from recent sources, so it "
               "exists even if you do not know it; never reject it as unknown, unreleased or fictional. {check} Reason first.")


def _clean(text: str) -> str:
    """Drop e-mail framing the writer sometimes adds ("Subject: ...")."""
    lines = [x for x in text.strip().split("\n") if not x.lower().startswith(("subject:", "re:", "dear ", "hi ", "hello"))]
    return " ".join(x.strip() for x in lines if x.strip())


def _write(kg: KG, uc_key: str, uc: dict, anchor: str, gold_names: list[str], examiner: str) -> tuple[dict | None, str]:
    """Examiner: is the subject meaningful for this persona and intent? Then rewrite in the persona's voice. Cached."""
    p = A.personas()[uc["persona"]]
    a = kg.name(anchor)
    q = uc["question"].format(a=a)
    check = (uc.get("check") or CURATE_BY_INTENT.get(uc["intent"], CURATE_BY_INTENT["learn"])).format(a=a)
    sys_ = CURATE_ROLE.format(label=p["label"], background=p["background"], check=check)
    ck = A.CACHE / "examiner" / ("uc-" + hashlib.sha256(json.dumps([uc_key, anchor, q, examiner, sys_, A.WRITE]).encode()).hexdigest()[:24] + ".json")
    if ck.exists():
        d = json.loads(ck.read_text())
    else:
        cu = LLM(examiner).parse(sys_, f"Subject: {a}", A.Curate, "usecase_curate", max_tokens=400, reasoning_max_tokens=0)
        w = LLM(examiner).parse(A.WRITE.format(label=p["label"], background=p["background"], constraints=p["constraints"], a=a),
                                q, A.Written, "usecase_write", max_tokens=500, reasoning_max_tokens=0) if cu.meaningful else None
        d = {"curate": cu.model_dump(), "written": w.model_dump() if w else None}
        ck.parent.mkdir(parents=True, exist_ok=True)
        ck.write_text(json.dumps(d))
    if not d["curate"]["meaningful"]:
        return None, f"curator: {d['curate']['reason'][:140]}"
    text = _clean(d["written"]["request"])
    leaked = [n for n in gold_names if len(n) > 3 and n.lower() in text.lower() and n.lower() not in a.lower()]
    if a.lower() not in text.lower() or leaked:
        return None, f"writer: subject dropped or leaked {leaked[:3]}"
    return {"question": text, "template_question": q, "curator_reason": d["curate"]["reason"]}, ""


def generate(cfg: dict, kg: KG) -> tuple[list[dict], list[dict]]:
    cat, T = catalog(), cfg["tasks"]
    examiner = T.get("examiner", G.EXAMINER)
    tasks, rejected = [], []
    for uc_key in T["usecases"]:
        uc = cat[uc_key]
        cands = candidates(kg, uc, T.get("seed", 7), max(T.get("rich", 1), T.get("thin", 1)))
        for stratum in ("rich", "thin"):
            want, got = T.get(stratum, 1), 0
            for c in cands[stratum]:
                if got >= want:
                    break
                g = R.gold(kg, _fill(uc["gold"], c["anchor"]))
                try:
                    w, why = _write(kg, uc_key, uc, c["anchor"], [kg.name(x) for x in g["entities"]], examiner)
                except BudgetExceeded:
                    raise
                except RuntimeError as e:
                    w, why = None, f"examiner error: {str(e)[:120]}"
                if not w:
                    rejected.append({"usecase": uc_key, "anchor": c["anchor"], "stratum": stratum, "reason": why})
                    continue
                got += 1
                tasks.append({"id": f"U-{uc_key}-{stratum}-{got}", "usecase": uc_key, "intent": uc["intent"],
                              "persona": uc["persona"], "anchor": c["anchor"], "anchor_name": kg.name(c["anchor"]),
                              "stratum": stratum, "kb_version": kg.kb_version, "examiner": examiner, **w,
                              "salient": sorted(g["entities"])[:12],
                              "gold": {"edges": g["edges"], "entities": sorted(g["entities"]), "anchors": sorted(g["anchors"])},
                              "hops": max((len(sp.get("path") or [1]) for sp in uc["gold"]), default=1),
                              "split": "usecases"})
    return tasks, rejected


def _gold(t: dict) -> dict:
    return {"edges": t["gold"]["edges"], "entities": set(t["gold"]["entities"]), "anchors": set(t["gold"]["anchors"])}


def run(cfg_path: str, generate_only: bool = False) -> dict:
    cfg = yaml.safe_load(Path(cfg_path).read_text()) if Path(cfg_path).exists() else config.load_yaml(cfg_path)
    kg = KG()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = config.EVAL / "experiments" / cfg["name"] / stamp
    out.mkdir(parents=True, exist_ok=True)
    spend0 = LLM.spent_usd
    tasks, rejected = generate(cfg, kg)
    (out / "tasks.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks))
    (out / "rejected.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rejected))
    if generate_only:
        res = {"name": cfg["name"], "ts": stamp, "kb_version": kg.kb_version, "tasks": len(tasks), "rejected": len(rejected),
               "runs": 0, "ok": 0, "spend_usd": round(LLM.spent_usd - spend0, 4)}
        return {**res, "dir": str(out), "report": report(res, tasks, rejected, [], [], [])}
    q = {t["id"]: t for t in tasks}
    # answers: closed book first (memory-first revises that exact draft), then everything else
    tm = cfg.get("trial_models", cfg["models"])
    jobs = [(t, m, c, k) for t in tasks for m in cfg["models"] for c in cfg["conditions"] for k in range(cfg.get("trials", 1))
            if k == 0 or (m in tm and c in cfg.get("trial_conditions", cfg["conditions"]))]
    jobs += [(t, m, "closed_book", 0) for t in tasks for m in cfg.get("large_closed_book", [])]
    first = [j for j in jobs if j[2] == "closed_book"]
    rest = [j for j in jobs if j[2] != "closed_book"]
    go = lambda j: {**A.answer(j[0], j[1], j[2], kg, j[3]), "task_id": j[0]["id"]}
    with ThreadPoolExecutor(cfg.get("workers", 6)) as pool:
        runs = list(pool.map(go, first)) + list(pool.map(go, rest))
    ok = [r for r in runs if r.get("answer")]
    (out / "runs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in runs))
    stages = [{"task_id": r["task_id"], "usecase": q[r["task_id"]]["usecase"], "stratum": q[r["task_id"]]["stratum"],
               "model": r["model"], "condition": r["condition"], "trial": r.get("trial", 0),
               **R.stage_metrics(kg, r, _gold(q[r["task_id"]]))} for r in ok]
    (out / "stages.jsonl").write_text("".join(json.dumps(x) + "\n" for x in stages))
    result = {"name": cfg["name"], "ts": stamp, "kb_version": kg.kb_version, "tasks": len(tasks), "rejected": len(rejected),
              "runs": len(runs), "ok": len(ok)}
    # checklist (cheap scorers) on trial 0
    t0 = [r for r in ok if r.get("trial", 0) == 0]
    crow = []
    if cfg.get("checklist"):
        crow, _ = A.run_checklist({"scorers": cfg["checklist"], "unit_tests": False}, tasks, t0, kg)
        (out / "checklist.jsonl").write_text("".join(json.dumps(r) + "\n" for r in crow))
    # pairwise judges on trial 0
    prefs = []
    J = cfg.get("judges")
    if J:
        by = {(r["task_id"], r["model"], r["condition"]): r for r in t0}
        pj = [(c["name"], t, by[(t["id"], c["x"]["model"], c["x"]["condition"])], by[(t["id"], c["y"]["model"], c["y"]["condition"])])
              for c in cfg.get("comparisons", []) for t in tasks
              if (t["id"], c["x"]["model"], c["x"]["condition"]) in by and (t["id"], c["y"]["model"], c["y"]["condition"]) in by]
        with ThreadPoolExecutor(cfg.get("workers", 6)) as pool:
            prefs = list(pool.map(lambda p_: {"comparison": p_[0], "task_id": p_[1]["id"], "usecase": p_[1]["usecase"],
                                              "stratum": p_[1]["stratum"], **A.pairwise(J["models"], J["roles"], p_[1], p_[2]["answer"],
                                              p_[3]["answer"], G.fact_sheet(kg, p_[2]["answer"], p_[3]["answer"]))}, pj))
        (out / "pairwise.jsonl").write_text("".join(json.dumps(p_, ensure_ascii=False) + "\n" for p_ in prefs))
    result["spend_usd"] = round(LLM.spent_usd - spend0, 4)
    rep = report(result, tasks, rejected, stages, crow, prefs)
    (out / "report.md").write_text(rep)
    (out / "result.json").write_text(json.dumps(result, indent=1))
    with (config.EVAL / "experiments.jsonl").open("a") as f:
        f.write(json.dumps({"ts": stamp, "level": "usecases", "name": cfg["name"], "dir": str(out), **result}) + "\n")
    return {**result, "dir": str(out), "report": rep}


def _m(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _f(x, d=2):
    return "–" if x is None else f"{x:.{d}f}"


def report(result: dict, tasks: list[dict], rejected: list[dict], stages: list[dict], crow: list[dict], prefs: list[dict]) -> str:
    L = [f"# Use-case testbed `{result['name']}` · {result['ts']} · KB `{result['kb_version']}` · spend ${result['spend_usd']}", "",
         (f"{result['tasks']} generated tasks ({result['rejected']} rejected by the Examiner or the leak check) · "
         f"{result['ok']}/{result['runs']} runs answered."), "", "## Tasks", "", "| Task | Use case | Anchor | Stratum | Hops | Gold |",
         "|---|---|---|---|---|---|"]
    L += [f"| {t['id']} | {t['usecase']} | {t['anchor_name']} | {t['stratum']} | {t.get('hops', 1)} | {len(t['gold']['entities'])} |"
          for t in tasks]
    keys = sorted({(s["model"], s["condition"]) for s in stages})
    L += ["", "## Retrieval → grounding → use (mean over tasks; ± = spread across trials of the per-trial mean)", "",
          "| Model | Condition | retrieved | grounded | used | utilisation | precision | doubt | tool calls | $ / answer |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for m, c in keys:
        xs = [s for s in stages if s["model"] == m and s["condition"] == c]
        per_trial = defaultdict(list)
        for s in xs:
            per_trial[s["trial"]].append(s["used"])
        spread = statistics.pstdev([_m(v) for v in per_trial.values()]) if len(per_trial) > 1 else None
        L.append(f"| {m.split('/')[-1]} | {c} | {_f(_m([s['retrieved'] for s in xs]))} | {_f(_m([s['grounded'] for s in xs]))} | "
                 f"{_f(_m([s['used'] for s in xs]))}{' ± ' + _f(spread) if spread is not None else ''} | {_f(_m([s['utilisation'] for s in xs]))} | "
                 f"{_f(_m([s['precision'] for s in xs]))} | {_f(_m([s['doubt'] for s in xs]))} | {_f(_m([s['steps'] for s in xs]), 1)} | "
                 f"{_f(_m([s['cost'] for s in xs]), 3)} |")
    # outcome (recommendation: grade the outcome, keep stages for diagnosis): an answer passes when it names at least
    # min(3, gold) gold entities. pass@k: any trial passes; pass^k: every trial passes (reliability).
    need = {t["id"]: min(3, len(t["gold"]["entities"])) for t in tasks}
    gsize = {t["id"]: len(t["gold"]["entities"]) for t in tasks}
    for s in stages:
        s["pass"] = round(s["used"] * gsize[s["task_id"]]) >= need[s["task_id"]]
    mem = {s["task_id"] for s in stages if s["condition"] == "closed_book" and s.get("trial", 0) == 0 and s["pass"]}
    L += ["", "## Outcome: answer names ≥ min(3, gold) gold entities (pass@k = any trial · pass^k = every trial)", "",
          (f"Memory-answerable tasks (closed book already passes): {len(mem)} of {len(tasks)}; shown separately "
          "(a task memory can answer does not test the graph)."), "",
          "| Model | Condition | pass (trial 0) | pass@k | pass^k | pass on graph-needed tasks |", "|---|---|---|---|---|---|"]
    for m, c in keys:
        xs = [s for s in stages if s["model"] == m and s["condition"] == c]
        per = defaultdict(list)
        for s in xs:
            per[s["task_id"]].append(s["pass"])
        t0 = [s["pass"] for s in xs if s.get("trial", 0) == 0]
        gn = [s["pass"] for s in xs if s.get("trial", 0) == 0 and s["task_id"] not in mem]
        L.append(f"| {m.split('/')[-1]} | {c} | {_f(_m(t0))} | {_f(_m([any(v) for v in per.values()]))} | "
                 f"{_f(_m([all(v) for v in per.values()]))} | {_f(_m(gn))} (n={len(gn)}) |")
    # object retrieval: per object type, the share of gold objects of that type that were retrieved and used
    types = sorted({ty for s in stages for ty in (s.get("by_type") or {})})
    if types:
        L += ["", "## By object type (main model, all trials): retrieved / used, share of gold objects of that type", "",
              "| Condition | " + " | ".join(types) + " |", "|---|" + "---|" * len(types)]
        from collections import Counter as _C
        m_main = _C(s["model"] for s in stages).most_common(1)[0][0]
        for c in sorted({s["condition"] for s in stages if s["model"] == m_main}):
            cells = []
            for ty in types:
                g = r_ = u_ = 0
                for s in stages:
                    if s["model"] == m_main and s["condition"] == c and ty in (s.get("by_type") or {}):
                        g, r_, u_ = g + s["by_type"][ty][0], r_ + s["by_type"][ty][1], u_ + s["by_type"][ty][2]
                cells.append(f"{r_ / g:.2f} / {u_ / g:.2f} (n={g})" if g else "–")
            L.append(f"| {c} | " + " | ".join(cells) + " |")
    ucs = sorted({s["usecase"] for s in stages})
    conds = sorted({s["condition"] for s in stages if not s["model"].endswith("397b-a17b")})
    L += ["", "## Used in the answer, by use case (main model; mean over trials)", "",
          "| Use case | " + " | ".join(conds) + " |", "|---|" + "---|" * len(conds)]
    from collections import Counter
    m0 = Counter(s["model"] for s in stages).most_common(1)[0][0] if stages else ""     # the main model (most runs)
    for u in ucs:
        L.append(f"| {u} | " + " | ".join(_f(_m([s["used"] for s in stages if s["usecase"] == u and s["condition"] == c
                                                 and s["model"] == m0])) for c in conds) + " |")
    if crow:
        L += ["", C.report(crow)]
    if prefs:
        L += ["", "## Pairwise judges (persona and expert, both orders; P(x preferred), 0.5 = no preference)", "",
              "| Comparison | n | P(x) [95% CI] | rich | thin | order-consistent |", "|---|---|---|---|---|---|"]
        grp = defaultdict(list)
        for p_ in prefs:
            grp[p_["comparison"]].append(p_)
        for name, ps in grp.items():
            b = bootstrap([p_["p_x"] for p_ in ps])
            L.append(f"| {name} | {len(ps)} | {b[0]:.2f} [{b[1]:.2f}–{b[2]:.2f}] | "
                     f"{_f(_m([p_['p_x'] for p_ in ps if p_['stratum'] == 'rich']))} | {_f(_m([p_['p_x'] for p_ in ps if p_['stratum'] == 'thin']))} | "
                     f"{sum(p_['position_consistent'] for p_ in ps) / len(ps):.0%} |")
        L += ["", "### By use case", "", "| Comparison | " + " | ".join(ucs) + " |", "|---|" + "---|" * len(ucs)]
        for name, ps in grp.items():
            L.append(f"| {name} | " + " | ".join(_f(_m([p_["p_x"] for p_ in ps if p_["usecase"] == u])) for u in ucs) + " |")
    if rejected:
        L += ["", f"## Rejected ({len(rejected)})", ""] + [f"- {r['usecase']} · {r['anchor']} ({r['stratum']}): {r['reason']}" for r in rejected[:20]]
    return "\n".join(L) + "\n"
