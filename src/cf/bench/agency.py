"""Agency testbed: persona-curated tasks → answers in several conditions → persona + expert LLM judges →
validated, cached, config-driven experiments (docs/AGENCY_EVAL.md).

    cf experiment configs/experiments/agency_pilot.yaml

Fast iteration:
- every model answer is cached by (request, model, condition, harness version): changing a judge, a rubric or the
  report re-uses the answers and costs only the judging;
- experiments are YAML files (personas, task counts, conditions, models, judges, validation, budget);
- judge unit tests (perturbations) run before any result is trusted.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cf import config
from cf.agent.kg import KG
from cf.bench import guidance as G
from cf.bench.sessions import _ok
from cf.eval.stats import bootstrap
from cf.llm.client import AUTO, LLM, BudgetExceeded

OUT = config.EVAL / "experiments"
CACHE = config.EVAL / "cache" / "agency"
HARNESS_VERSION = "agentic-v5"            # bump when run_agentic's prompts or gates change (invalidates the cache)
ENRICH_VERSION = "enrich-v4"
RAG_VERSION = "rag-v1"              # same, for run_enrich (memory-first, graph-enriched)


def personas() -> dict:
    return config.load_yaml("personas.yaml")


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- 1 · Examiner: persona-curated tasks ----------------------------------------------------------------
def _pool(kg: KG, kind: str) -> list[str]:
    if kind == "org":          # customers whose stack the KB knows
        return [e["id"] for e in kg.ents.values() if e["type"] == "org" and _ok(kg, e["id"])
                and sum(kg.edges[x]["relation"] in ("uses_tech", "uses_method") and kg.edges[x]["head"] == e["id"]
                        for x in kg.adj.get(e["id"], [])) >= 2]
    if kind == "technology":   # tools offered or used by several organisations
        return [e["id"] for e in kg.ents.values() if e["type"] == "technology" and _ok(kg, e["id"])
                and sum(kg.edges[x]["relation"] in ("offers", "uses_tech") for x in kg.adj.get(e["id"], [])) >= 2]
    return [e["id"] for e in kg.ents.values() if e["type"] == kind and _ok(kg, e["id"])]


def candidates(persona_keys: list[str], per_persona: int, rich: int, seed: int) -> list[dict]:
    """Graph-generated candidates, stratified rich/thin, each anchor used once across personas."""
    kg, P = KG(), personas()
    rnd = random.Random(seed)
    by_kind = defaultdict(list)
    for k in persona_keys:
        by_kind[P[k]["anchor"]].append(k)
    out = []
    for kind, keys in by_kind.items():
        pool = _pool(kg, kind)
        rnd.shuffle(pool)
        rich_pool, thin_pool = [], []
        for a in pool:
            sal = G.salient(kg, a)
            rels = {kg.edges[x]["relation"] for x in kg.adj.get(a, []) if kg.edges[x]["status"] != "unsupported"}
            (rich_pool if len(sal) >= 6 and len(rels) >= 2 else thin_pool if 2 <= len(sal) <= 5 else []).append((a, sal))
        for n_, src, stratum in ((rich, rich_pool, "rich"), (per_persona - rich, thin_pool, "thin")):
            for i in range(min(n_ * len(keys), len(src))):
                a, sal = src[i]
                k = keys[i % len(keys)]
                out.append({"persona": k, "anchor": a, "stratum": stratum, "salient": sal, "kb_version": kg.kb_version,
                            "template": P[k]["request"].format(a=kg.name(a))})
    return out


class Curate(_S):
    reason: str
    meaningful: bool


class Written(_S):
    request: str


CURATE = ("You check tasks for an evaluation of career and engineering guidance. The asker is: {label} ({background}). "
          "Is '{a}' a meaningful, specific subject for this person to learn, build, research or deploy for? Reject generic "
          "words, study designs, vague slogans and company-internal jargon. Reason first.")
WRITE = ("Rewrite this request in the first person, as this person would actually ask it: {label}. Background: "
         "{background} Constraints: {constraints} Keep it natural, specific, under 90 words; keep the subject '{a}' and "
         "the constraints. Do not add any names of companies, tools or methods.")


def curate(cands: list[dict], per_persona: int, rich: int, examiner: str = G.EXAMINER) -> tuple[list[dict], list[dict]]:
    """Curate (is the subject meaningful for THIS persona?) → write in the persona's voice → leak check."""
    kg, P = KG(), personas()
    keep, rejected = defaultdict(list), []
    for c in cands:
        k, p = c["persona"], P[c["persona"]]
        want = rich if c["stratum"] == "rich" else per_persona - rich
        if sum(x["stratum"] == c["stratum"] for x in keep[k]) >= want:
            continue
        a = kg.name(c["anchor"])
        ck = CACHE / "examiner" / (hashlib.sha256(json.dumps([k, c["anchor"], c["template"], examiner, CURATE, WRITE]).encode()).hexdigest()[:24] + ".json")
        try:
            if ck.exists():                                  # reproducible task sets: the Examiner's outputs are cached
                d = json.loads(ck.read_text())
                cu, w = Curate(**d["curate"]), (Written(**d["written"]) if d.get("written") else None)
            else:
                cu = LLM(examiner).parse(CURATE.format(label=p["label"], background=p["background"], a=a), f"Subject: {a}",
                                         Curate, "agency_curate", max_tokens=400, reasoning_max_tokens=0)
                w = LLM(examiner).parse(WRITE.format(label=p["label"], background=p["background"],
                                                     constraints=p["constraints"], a=a), c["template"], Written,
                                        "agency_write", max_tokens=500, reasoning_max_tokens=0) if cu.meaningful else None
                ck.parent.mkdir(parents=True, exist_ok=True)
                ck.write_text(json.dumps({"curate": cu.model_dump(), "written": w.model_dump() if w else None}))
            if not cu.meaningful:
                rejected.append({**c, "reason": f"curator: {cu.reason[:160]}"})
                continue
        except BudgetExceeded:
            raise
        except RuntimeError as e:
            rejected.append({**c, "reason": f"examiner error: {str(e)[:120]}"})
            continue
        leaked = [kg.name(x) for x in c["salient"] if len(kg.name(x)) > 3 and kg.name(x).lower() in w.request.lower()
                  and kg.name(x).lower() != a.lower()]
        if a.lower() not in w.request.lower() or leaked:
            rejected.append({**c, "reason": f"writer: subject dropped or leaked {leaked[:3]}"})
            continue
        keep[k].append({**c, "question": w.request, "examiner": examiner, "curator_reason": cu.reason})
    acc = [t for k in keep for t in keep[k]]
    for i, t in enumerate(acc):
        t["id"] = f"A-{t['persona']}-{i:02d}"
        t["split"] = "dev" if int(hashlib.md5(t["id"].encode()).hexdigest(), 16) % 4 == 0 else "heldout"
    return acc, rejected


# ---- 2 · answers, cached ------------------------------------------------------------------------------
def _key(task: dict, model: str, condition: str, trial: int = 0) -> str:
    extra = [trial] if trial else []                    # trial 0 keeps the keys of every earlier cached answer
    h = hashlib.sha256(json.dumps([task["question"], task["kb_version"], model, condition, *extra,
                                   HARNESS_VERSION if condition.startswith("kg_agentic") else
                                   ENRICH_VERSION if condition.startswith("kg_enrich") else
                                   RAG_VERSION if condition.startswith("kg_rag") else ""]).encode()).hexdigest()[:24]
    return h


def answer(task: dict, model: str, condition: str, kg: KG, trial: int = 0) -> dict:
    """Cached by (question, KB, model, condition, harness version, trial). kg_enrich revises trial 0's closed-book
    answer of the same trial index, so each trial pairs a draft with its own revision."""
    f = CACHE / f"{_key(task, model, condition, trial)}.json"
    if f.exists():
        return {**json.loads(f.read_text()), "cached": True, "trial": trial}
    t = {**task, "persona": task["persona"], "profile": personas()[task["persona"]]}
    head, _, offs = condition.partition(":")         # "kg_agentic+reading+select:read" = switches on, harness parts off
    base, on = head.split("+")[0], frozenset(head.split("+")[1:])
    off = frozenset(x for x in offs.split(",") if x)
    if base == "kg_agentic":
        r = G.run_agentic(model, t, kg, off=off, on=on)
    elif base == "kg_rag":                     # typical RAG: one retrieval pass, context in the prompt
        r = G.run_rag(model, t, kg, on=on)
    elif base == "kg_enrich":                  # memory-first: revise this model's own (cached) closed-book answer
        draft = answer(task, model, "closed_book" + ("+reading" if "reading" in on else ""), kg, trial)
        if not draft.get("answer"):
            return {**draft, "condition": condition, "error": f"no draft: {draft.get('error')}"}
        r = G.run_enrich(model, t, kg, draft, on=on)
    else:
        r = G.run(model, t, base, kg, on=on)
    r["condition"] = condition
    r["trial"] = trial
    if r.get("answer"):
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(r, ensure_ascii=False, default=str))
    return r


# ---- 3 · judges: persona (the asker) and expert (a frontier practitioner) ---------------------------------------
class PersonaScores(_S):
    rationale: str
    usefulness: int = Field(ge=1, le=5)
    fit: int = Field(ge=1, le=5)
    would_act: int = Field(ge=1, le=5)


class ExpertScores(_S):
    rationale: str
    frontier_relevance: int = Field(ge=1, le=5)
    insight: int = Field(ge=1, le=5)
    actionability: int = Field(ge=1, le=5)
    experiment_rigor: int = Field(ge=1, le=5)
    accuracy: int = Field(ge=1, le=5)


class Pref(_S):
    rationale: str
    winner: Literal["A", "B", "tie"]


PERSONA_JUDGE = """You ARE this person: {label}. Background: {background} Constraints: {constraints} Goal: {goal}
You asked the question below and received advice. Judge it as yourself. Write your reasoning first, then score 1-5:
- usefulness: 1 generic, I learn nothing new · 3 some useful steps · 5 changes what I would do this week
- fit: 1 ignores my skills or constraints · 3 partly fits · 5 fits my background, time and compute. Check prerequisites (hardware, access, skills): a plan I cannot run scores at most 2.
- would_act: 1 no · 3 maybe · 5 yes, starting now
A REFERENCE sheet describes names in the advice from a curated knowledge base; "not in reference" does not mean false.
Length is not quality."""

EXPERT_JUDGE = """You are a senior practitioner at the frontier of AI research and engineering, reviewing advice given to:
{label} ({background}; constraints: {constraints}). Write your reasoning first, then score 1-5:
- frontier_relevance: 1 dated or generic practice · 3 current mainstream · 5 reflects what leading teams do now
- insight: 1 a tutorial list anyone could find · 3 some useful connections · 5 non-obvious, specific connections that change the plan
- actionability: 1 vague or infeasible under the constraints · 3 concrete but partly feasible · 5 concrete first steps and stack, feasible as stated
- experiment_rigor: 1 no real experiment · 3 a question and a measure · 5 question, baseline, one controlled change, measure, a threat to validity. An experiment without a real baseline or control scores at most 2.
- accuracy: 1 invented or wrong claims · 3 mostly right, unqualified · 5 correct, with uncertainty and self-claims flagged
A REFERENCE sheet describes names in the advice from a curated knowledge base; "not in reference" does not mean false.
Length is not quality."""


def _ctx(task: dict) -> dict:
    return personas()[task["persona"]]


def score(judge: str, role: str, task: dict, ans: dict, sheet: str) -> dict:
    p = _ctx(task)
    sys_ = (PERSONA_JUDGE if role == "persona" else EXPERT_JUDGE).format(**p)
    cls = PersonaScores if role == "persona" else ExpertScores
    out = LLM(judge).parse(sys_, f"Question:\n{task['question']}\n\n{sheet}\n\nAdvice:\n{G._blind(ans)}", cls,
                           f"agency_score_{role}", max_tokens=3000, reasoning_max_tokens=AUTO)
    return out.model_dump()


def prefer(judge: str, role: str, task: dict, a: dict, b: dict, sheet: str) -> dict:
    p = _ctx(task)
    sys_ = (PERSONA_JUDGE if role == "persona" else EXPERT_JUDGE).format(**p) + \
        "\nNow compare two answers to the same question. Which is better for this person? Reason first."
    out = LLM(judge).parse(sys_, f"Question:\n{task['question']}\n\n{sheet}\n\nAnswer A:\n{G._blind(a)}\n\nAnswer B:\n{G._blind(b)}",
                           Pref, f"agency_pair_{role}", max_tokens=3000, reasoning_max_tokens=AUTO)
    return out.model_dump()


def pairwise(judges: list[str], roles: list[str], task: dict, x: dict, y: dict, sheet: str) -> dict:
    raw = []
    for j in judges:
        for role in roles:
            a1, a2 = prefer(j, role, task, x, y, sheet), prefer(j, role, task, y, x, sheet)
            v1 = 1.0 if a1["winner"] == "A" else 0.5 if a1["winner"] == "tie" else 0.0
            v2 = 1.0 if a2["winner"] == "B" else 0.5 if a2["winner"] == "tie" else 0.0
            raw.append({"judge": j, "role": role, "xy": v1, "yx": v2, "consistent": v1 == v2,
                        "rationales": [a1["rationale"], a2["rationale"]]})
    return {"p_x": sum((r["xy"] + r["yx"]) / 2 for r in raw) / len(raw),
            "position_consistent": sum(r["consistent"] for r in raw) / len(raw), "raw": raw}


# ---- 4 · validating the judges: perturbation unit tests -------------------------------------------------------
FAKE = {"tool": "QuantaForge", "org": "Helixon Labs"}


def perturb(ans: dict, kind: str) -> dict:
    """Deterministic edits of a good answer; each should lower one dimension."""
    a = json.loads(json.dumps(ans))
    if kind == "generic":            # strip the specifics
        a["projects"] = [{**p, "what": "Build a small project in this area and evaluate it.", "stack": ["Python", "PyTorch"],
                          "first_step": "Read a tutorial."} for p in a.get("projects") or []]
        a["stack"] = ["Python", "PyTorch"]
        a["learn"] = ["The basics", "Intermediate topics", "Advanced topics"]
    elif kind == "false_claim":      # one invented tool and organisation, stated as fact
        a["stack"] = (a.get("stack") or []) + [FAKE["tool"]]
        a["summary"] = (a.get("summary") or "") + f" {FAKE['org']}, the market leader, uses {FAKE['tool']} for this in production."
    elif kind == "infeasible":       # break the constraints
        a["summary"] = (a.get("summary") or "") + " You will need a cluster of 64 H100 GPUs for at least six months."
        a["projects"] = [{**p, "first_step": "Reserve 64 H100 GPUs for six months and pretrain a 70B model from scratch."}
                         for p in a.get("projects") or []]
    elif kind == "no_baseline":      # experiments without baselines or controls
        a["experiments"] = [{"question": e["question"], "baseline": "none", "change": "try things", "measure": "see if it looks better"}
                            for e in a.get("experiments") or []]
    return a


TARGET = {"generic": ("expert", "insight"), "false_claim": ("expert", "accuracy"),
          "infeasible": ("persona", "fit"), "no_baseline": ("expert", "experiment_rigor")}


def judge_unit_tests(judges: list[str], tasks: list[dict], answers: list[dict], kg: KG, workers: int = 8) -> dict:
    """For each good answer and perturbation: does the targeted dimension drop? Pass ≥ 80% per judge.
    All judge calls run in parallel (reasoning judges take up to a minute per call)."""
    base_jobs = [(j, role, i) for i in range(len(tasks)) for j in judges for role in ("persona", "expert")]
    pert_jobs = [(j, kind, i) for i in range(len(tasks)) for j in judges for kind in TARGET]
    sheets = [G.fact_sheet(kg, a) for a in answers]
    with ThreadPoolExecutor(workers) as pool:
        base = dict(zip(base_jobs, pool.map(lambda x: score(x[0], x[1], tasks[x[2]], answers[x[2]], sheets[x[2]]), base_jobs), strict=True))
        pert = dict(zip(pert_jobs, pool.map(lambda x: score(x[0], TARGET[x[1]][0], tasks[x[2]], perturb(answers[x[2]], x[1]),
                                                             G.fact_sheet(kg, perturb(answers[x[2]], x[1]))), pert_jobs), strict=True))
    rows = []
    for (j, kind, i), s_ in pert.items():
        role, dim = TARGET[kind]
        b = base[(j, role, i)][dim]
        rows.append({"judge": j, "task": tasks[i]["id"], "kind": kind, "dim": dim, "before": b, "after": s_[dim],
                     "detected": s_[dim] < b})
    res = {}
    for j in judges:
        mine = [r for r in rows if r["judge"] == j]
        res[j] = {"detected": round(sum(r["detected"] for r in mine) / max(len(mine), 1), 3),
                  "by_kind": {k: round(sum(r["detected"] for r in mine if r["kind"] == k) /
                                       max(sum(1 for r in mine if r["kind"] == k), 1), 3) for k in TARGET},
                  "passes": sum(r["detected"] for r in mine) / max(len(mine), 1) >= 0.8}
    return {"summary": res, "rows": rows}


# ---- 5 · experiments from config ------------------------------------------------------------------------------
def run_experiment(cfg_path: str) -> dict:
    cfg = config.load_yaml(cfg_path) if not Path(cfg_path).is_absolute() else __import__("yaml").safe_load(Path(cfg_path).read_text())
    name, stamp = cfg["name"], datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = OUT / name / stamp
    out.mkdir(parents=True, exist_ok=True)
    kg = KG()
    spend0 = LLM.spent_usd
    T = cfg["tasks"]
    over = T.get("oversample", 4)                         # curation rejects some; generate spares
    tasks, rejected = curate(candidates(T["personas"], T["per_persona"] * over, T["rich"] * over, T.get("seed", 13)),
                             T["per_persona"], T["rich"])
    if T.get("split"):
        tasks = [t for t in tasks if t["split"] == T["split"]] or tasks
    (out / "tasks.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks))
    models, conds, workers = cfg["models"], cfg["conditions"], cfg.get("workers", 6)
    jobs = [(t, m, c) for t in tasks for m in models for c in conds]
    jobs += [(t, m, "closed_book") for t in tasks for m in cfg.get("large_closed_book", [])]   # H3: large, from memory
    # closed-book answers first: kg_enrich revises exactly the cached closed-book answer that gets scored
    first = sorted(jobs, key=lambda j: j[2] != "closed_book")
    n_closed = sum(1 for j in first if j[2] == "closed_book")
    with ThreadPoolExecutor(workers) as pool:
        runs = list(pool.map(lambda j: {**answer(j[0], j[1], j[2], kg), "task_id": j[0]["id"]}, first[:n_closed]))
        runs += list(pool.map(lambda j: {**answer(j[0], j[1], j[2], kg), "task_id": j[0]["id"]}, first[n_closed:]))
    ok = [r for r in runs if r.get("answer")]
    if len(ok) < 0.9 * len(runs):
        raise RuntimeError(f"invalid experiment: {len(runs) - len(ok)}/{len(runs)} runs failed")
    (out / "runs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in runs))
    by = {(r["task_id"], r["model"], r["condition"]): r for r in ok}
    q = {t["id"]: t for t in tasks}
    J = cfg["judges"]
    result = {"name": name, "ts": stamp, "kb_version": kg.kb_version, "config": cfg, "tasks": len(tasks),
              "rejected_tasks": len(rejected)}
    # judge validation first
    if cfg.get("validate_judges", True):
        sample = [r for r in ok if r["condition"].startswith("kg_agentic")][: cfg.get("unit_test_answers", 4)] or ok[:4]
        ut = judge_unit_tests(J["models"], [q[r["task_id"]] for r in sample], [r["answer"] for r in sample], kg)
        (out / "judge_unit_tests.json").write_text(json.dumps(ut, indent=1))
        result["judge_unit_tests"] = ut["summary"]
    # absolute scores, both roles
    sheets = {}
    for r in ok:
        sheets.setdefault((r["task_id"], r["model"]), G.fact_sheet(kg, *(by[(r["task_id"], r["model"], c)]["answer"]
                                                                       for c in conds if (r["task_id"], r["model"], c) in by)))
    jobs = [(j, role, r) for j in J["models"] for role in J["roles"] for r in ok]
    with ThreadPoolExecutor(workers) as pool:
        scores = list(pool.map(lambda x: {"judge": x[0], "role": x[1], "task_id": x[2]["task_id"], "model": x[2]["model"],
                                          "condition": x[2]["condition"],
                                          **score(x[0], x[1], q[x[2]["task_id"]], x[2]["answer"], sheets[(x[2]["task_id"], x[2]["model"])])}, jobs))
    (out / "scores.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in scores))
    # pairwise comparisons named in the config
    pjobs = []
    for comp in cfg.get("comparisons", []):
        for t in tasks:
            x, y = (t["id"], comp["x"]["model"], comp["x"]["condition"]), (t["id"], comp["y"]["model"], comp["y"]["condition"])
            if x in by and y in by:
                pjobs.append((comp["name"], t, by[x], by[y]))
    with ThreadPoolExecutor(workers) as pool:
        prefs = list(pool.map(lambda p_: {"comparison": p_[0], "task_id": p_[1]["id"], "persona": p_[1]["persona"],
                                          "stratum": p_[1]["stratum"],
                                          **pairwise(J["models"], J["roles"], p_[1], p_[2]["answer"], p_[3]["answer"],
                                                     G.fact_sheet(kg, p_[2]["answer"], p_[3]["answer"]))}, pjobs))
    (out / "pairwise.jsonl").write_text("".join(json.dumps(p_, ensure_ascii=False) + "\n" for p_ in prefs))
    ck = cfg.get("checklist")
    if ck:                                   # typed yes/no items, scored by code, Jev and LLM judges, then compared
        crow, cut = run_checklist(ck, tasks, ok, kg, workers)
        (out / "checklist.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in crow))
        result["checklist_unit_tests"] = cut["summary"] if cut else None
        if cut:
            (out / "checklist_unit_tests.json").write_text(json.dumps(cut, indent=1))
    result["spend_usd"] = round(LLM.spent_usd - spend0, 4)
    rep = report(result, tasks, ok, scores, prefs)
    if ck:
        from cf.bench import checklist as C
        rep += "\n" + C.report(crow, cut)
    (out / "report.md").write_text(rep)
    (out / "result.json").write_text(json.dumps(result, indent=1, default=str))
    with (config.EVAL / "experiments.jsonl").open("a") as f:
        f.write(json.dumps({"ts": stamp, "level": "agency", "name": name, "dir": str(out), "spend_usd": result["spend_usd"],
                            "judge_unit_tests": result.get("judge_unit_tests")}, default=str) + "\n")
    return {**result, "dir": str(out), "report": rep}


def _sheets(kg: KG, runs: list[dict]) -> dict:
    """One symmetric fact sheet per (task, model), covering every condition's answer."""
    by = defaultdict(list)
    for r in runs:
        by[(r["task_id"], r["model"])].append(r["answer"])
    return {k: G.fact_sheet(kg, *v) for k, v in by.items()}


def run_checklist(ck: dict, tasks: list[dict], runs: list[dict], kg: KG, workers: int = 6) -> tuple[list[dict], dict | None]:
    from cf.bench import checklist as C
    q, prof = {t["id"]: t for t in tasks}, personas()
    rows = C.score_runs(ck["scorers"], runs, q, prof, _sheets(kg, runs), kg, workers)
    cut = None
    if ck.get("unit_tests", True):
        sample = [r for r in runs if r["condition"] != "closed_book"][: ck.get("unit_test_answers", 4)] or runs[:4]
        cut = C.unit_tests(ck["scorers"], [q[r["task_id"]] for r in sample], [r["answer"] for r in sample], prof, kg, workers)
    return rows, cut


def rescore_checklist(exp_dir: str, scorers: list[str], unit_tests: bool = True) -> dict:
    """Score an existing experiment's cached answers with the checklist (no new answers are generated)."""
    from cf.bench import checklist as C
    d = Path(exp_dir)
    tasks = [json.loads(x) for x in (d / "tasks.jsonl").read_text().split("\n") if x.strip()]
    runs = [r for x in (d / "runs.jsonl").read_text().split("\n") if x.strip() and (r := json.loads(x)).get("answer")]
    kg = KG(version=tasks[0]["kb_version"])
    spend0 = LLM.spent_usd
    rows, cut = run_checklist({"scorers": scorers, "unit_tests": unit_tests}, tasks, runs, kg)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    (d / f"checklist-{stamp}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    rep = f"# Checklist re-score of `{d.parent.name}/{d.name}` · {stamp}\n\nScorers: {', '.join(scorers)} · spend " \
          f"${LLM.spent_usd - spend0:.4f}\n\n" + C.report(rows, cut)
    (d / f"checklist-{stamp}.md").write_text(rep)
    if cut:
        (d / f"checklist_unit_tests-{stamp}.json").write_text(json.dumps(cut, indent=1))
    with (config.EVAL / "experiments.jsonl").open("a") as f:
        f.write(json.dumps({"ts": stamp, "level": "agency-checklist", "of": f"{d.parent.name}/{d.name}", "dir": str(d),
                            "scorers": scorers, "spend_usd": round(LLM.spent_usd - spend0, 5),
                            "unit_tests": cut["summary"] if cut else None}) + "\n")
    return {"report": rep, "rows": len(rows), "spend_usd": round(LLM.spent_usd - spend0, 5)}


PERSONA_DIMS = ("usefulness", "fit", "would_act")
EXPERT_DIMS = ("frontier_relevance", "insight", "actionability", "experiment_rigor", "accuracy")


def _dmean(per: dict, role: str, d: str) -> str:
    xs = [x[d] for (r, _), ss in per.items() if r == role for x in ss]
    return f"{sum(xs) / len(xs):.2f}" if xs else "–"


def _role_ci(per: dict, role: str, dims: tuple) -> str:
    vals = [sum(sum(x[d] for d in dims) / len(dims) for x in ss) / len(ss) for (r, _), ss in per.items() if r == role]
    if not vals:
        return "–"
    b = bootstrap(vals)
    return f"{b[0]:.2f} [{b[1]:.2f}–{b[2]:.2f}]"


def report(result: dict, tasks: list[dict], runs: list[dict], scores: list[dict], prefs: list[dict]) -> str:
    L = [f"# Agency experiment `{result['name']}` · {result['ts']} · KB `{result['kb_version']}`", "",
         f"{result['tasks']} tasks ({result['rejected_tasks']} rejected by the Examiner) · spend ${result['spend_usd']}", ""]
    if result.get("judge_unit_tests"):
        L += ["## Judge validation (perturbation unit tests)", "", "| Judge | Detected | generic | false claim | infeasible | no baseline | Pass (≥ 80%) |",
              "|---|---|---|---|---|---|---|"]
        for j, s in result["judge_unit_tests"].items():
            b = s["by_kind"]
            L.append(f"| {j.split('/')[-1]} | {s['detected']:.0%} | {b['generic']:.0%} | {b['false_claim']:.0%} | "
                     f"{b['infeasible']:.0%} | {b['no_baseline']:.0%} | {'yes' if s['passes'] else '**no**'} |")
        L.append("")
    L += ["## Scores (mean over judges; 95% task-bootstrap interval on the role's mean)", "",
          "| Model | Condition | " + " | ".join(PERSONA_DIMS) + " | persona mean | " + " | ".join(EXPERT_DIMS) + " | expert mean |",
          "|---|---|" + "---|" * (len(PERSONA_DIMS) + len(EXPERT_DIMS) + 2)]
    cells = defaultdict(lambda: defaultdict(list))
    for s in scores:
        cells[(s["model"], s["condition"])][(s["role"], s["task_id"])].append(s)
    for (m, c), per in sorted(cells.items()):
        L.append(f"| {m.split('/')[-1]} | {c} | " + " | ".join(_dmean(per, "persona", d) for d in PERSONA_DIMS)
                 + f" | {_role_ci(per, 'persona', PERSONA_DIMS)} | " + " | ".join(_dmean(per, "expert", d) for d in EXPERT_DIMS)
                 + f" | {_role_ci(per, 'expert', EXPERT_DIMS)} |")
    L += ["", "## Pairwise (both orders × judges × roles; 0.5 = no preference)", "",
          "| Comparison | n | P(x preferred) | rich | thin | position-consistent |", "|---|---|---|---|---|---|"]
    grp = defaultdict(list)
    for p_ in prefs:
        grp[p_["comparison"]].append(p_)
    for name, ps in grp.items():
        mean = lambda xs: f"{sum(xs) / len(xs):.2f} (n={len(xs)})" if xs else "–"
        b = bootstrap([p_["p_x"] for p_ in ps])
        L.append(f"| {name} | {len(ps)} | {b[0]:.2f} [{b[1]:.2f}–{b[2]:.2f}] | {mean([p_['p_x'] for p_ in ps if p_['stratum'] == 'rich'])} | "
                 f"{mean([p_['p_x'] for p_ in ps if p_['stratum'] == 'thin'])} | {sum(p_['position_consistent'] for p_ in ps) / len(ps):.0%} |")
    by_p = defaultdict(list)
    for p_ in prefs:
        by_p[(p_["comparison"], p_["persona"])].append(p_["p_x"])
    if by_p:
        L += ["", "### By persona", "", "| Comparison | Persona | P(x preferred) | n |", "|---|---|---|---|"]
        L += [f"| {c} | {p} | {sum(v) / len(v):.2f} | {len(v)} |" for (c, p), v in sorted(by_p.items())]
    _ = (tasks, runs, re)
    return "\n".join(L) + "\n"


# ---- 6 · the application: grounded advice for a person ------------------------------------------------------
def advise(question: str, persona: str = "undergrad_capstone", model: str = "thinkingmachines/inkling-2-small") -> dict:
    """Ask as a persona; the agentic harness researches the KB and builds advice from cited findings.
    Returns the run plus a markdown card with every finding's sources (status, publisher, URL)."""
    P = personas()[persona]
    kg = KG()
    q = f"{question}\n\nAbout me: {P['background']} Constraints: {P['constraints']} Goal: {P['goal']}"
    task = {"id": "advise", "persona": persona, "question": q, "kb_version": kg.kb_version, "salient": [], "stratum": None}
    r = G.run_agentic(model, task, kg)
    a = r.get("answer") or {}
    L = [f"# {question}", "", f"*Asked as: {P['label']} · model {model.split('/')[-1]} · KB {kg.kb_version}*", "",
         a.get("summary") or "", "", "## Learn, in this order", ""]
    L += [f"{i + 1}. {x}" for i, x in enumerate(a.get("learn") or [])]
    L += ["", "## Build", ""]
    for p_ in a.get("projects") or []:
        based = ", ".join(f"F{i + 1}" for i in p_.get("based_on") or [])
        L += [f"**{p_['title']}**" + (f" (built on {based})" if based else ""), "", p_["what"], "",
              f"Stack: {', '.join(p_.get('stack') or [])}  ", f"First step: {p_['first_step']}", ""]
    L += ["## Experiments", ""]
    L += [f"- **{e['question']}** Baseline: {e['baseline']}. Change: {e['change']}. Measure: {e['measure']}." for e in a.get("experiments") or []]
    L += ["", "## What the advice is built on", ""]
    for i, f in enumerate(r.get("notes") or []):
        L.append(f"**F{i + 1}.** {f['finding']} *{f['implication']}*")
        for eid in (f.get("edge_ids") or [])[:3]:
            e = kg.edges.get(eid)
            if e:
                ev = e["evidence"][0] if e["evidence"] else {}
                L.append(f"  - {kg.name(e['head'])} —{e['relation']}→ {kg.name(e['tail'])} · *{e['status']}* · "
                         f"[{ev.get('publisher', 'source')}]({ev.get('source_url', '')})")
        L.append("")
    L += ["---", ("Statuses: *claimed* = one source, often the company itself; *confirmed* = the other party agrees; "
          "*corroborated* = independent sources agree; *verified* = a primary registry. Explore: https://pracha.me/connected-frontiers/")]
    card = "\n".join(L) + "\n"
    out = config.DATA / "advice"
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower())[:50].strip("-")
    path = out / f"{datetime.now(UTC):%Y%m%d-%H%M}-{slug}.md"
    path.write_text(card)
    return {**r, "card": card, "card_path": str(path)}
