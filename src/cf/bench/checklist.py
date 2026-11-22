"""Typed checklist scoring: one set of yes/no items, three kinds of scorer, compared item by item.

Why: the 1-5 rubric judges sat at the ceiling (95% of GLM scores were 4-5), so they barely separated answers.
Yes/no items are harder to inflate (CheckEval, arXiv 2403.18771; unverified here beyond its abstract), and
each item can be tested on its own.

Scorers (each returns P(yes) in [0, 1] per item, or None to abstain):
  code  deterministic checks on the answer's fields and the KB; abstains where a rule cannot decide
  jev   TypeSafe Jev, a typed "System One" evaluation model: one `noul` question per item, returns a probability,
        no rationale (cf.llm.typesafe, via OpenRouter's Decisions API)
  llm   an LLM judge (e.g. GLM-5.3, Nemotron) that writes evidence per item, then answers yes/no (typed schema)

Every scorer sees the same blind rendering of the answer, the person's profile and the symmetric fact sheet.
`agreement()` compares scorers per item; `unit_tests()` checks that each scorer catches deliberate defects,
including the familiarity test: a famous-but-wrong name vs a made-up name in the same slot.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cf.agent.kg import KG
from cf.bench import guidance as G
from cf.llm.client import AUTO, LLM

# ---- the checklist ------------------------------------------------------------------------------------------
# id → (dimension, question). Every item is phrased so that "yes" is good.
ITEMS: dict[str, tuple[str, str]] = {
    "fit_compute": ("fit", "Can this person carry out the main project with only the compute, money and time they stated?"),
    "fit_skills": ("fit", "Does the plan start from this person's current skills, without an unexplained prerequisite?"),
    "first_step_day": ("actionability", "Can the first step of the first project be done within one day?"),
    "stack_named": ("actionability", "Does each project name a concrete stack (specific libraries, models or datasets)?"),
    "baseline": ("rigor", "Does every experiment name a concrete baseline (a specific method, model or setting, not 'none')?"),
    "one_change": ("rigor", "Does every experiment change exactly one thing relative to its baseline?"),
    "measure": ("rigor", "Does every experiment name a specific, measurable metric?"),
    "specific_names": ("relevance", ("Does the advice name at least three specific tools, datasets, models or "
                                    "organisations beyond generic ones like Python or PyTorch?")),
    "current": ("relevance", "Does the advice reflect current practice rather than dated methods or tools?"),
    # accuracy is split into two atomic questions (TypeSafe: split compound judgments). The combined version
    # ("real, current and appropriate") got P(yes) 0.22 from Jev on good answers, so it could not detect anything.
    "no_invented": ("accuracy", "Are all the named tools, organisations, datasets and benchmarks real (none made up)?"),
    "no_dated": ("accuracy", "Are all the named tools and libraries still maintained and in current use (none "
                             "discontinued or abandoned)?"),
    "flags_uncertainty": ("honesty", "Does the advice flag at least one uncertain, unverified or self-claimed fact?"),
    "gap_or_connection": ("insight", ("Does it point out a gap or a non-obvious connection (who does what, what is "
                                     "missing) that changes the plan?")),
    "meets_success": ("usefulness", "Would following it produce what this person said success looks like?"),
}
IDS = tuple(ITEMS)


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Verdict(_S):
    item: Literal[IDS]          # type: ignore[valid-type]
    evidence: str
    answer: Literal["yes", "no"]


class ChecklistAnswer(_S):
    verdicts: list[Verdict]


def _person(task: dict, profile: dict) -> dict:
    return {k: profile.get(k, "") for k in ("label", "background", "constraints", "goal", "success")} | {"question": task["question"]}


# ---- scorer 1 · code -----------------------------------------------------------------------------------------
GENERIC = {"python", "pytorch", "numpy", "pandas", "jupyter", "git", "github", "docker", "linux", "cuda", "colab",
           "google colab", "matplotlib", "scikit-learn", "sklearn", "the basics", "tensorflow", "vs code"}
_NONE = re.compile(r"^\s*(none|n/?a|nothing|no baseline|-|tbd|the default)?\s*\.?\s*$", re.IGNORECASE)
_VAGUE = re.compile(r"see if|looks? better|vibes|qualitative(ly)? only|whether it works", re.IGNORECASE)
_HEDGE = re.compile(r"self-claimed|unverified|not verified|uncertain|unclear|may not|might not|validate|verify|"
                    r"confirm on|check (that|whether)|reported by|claims?\b", re.IGNORECASE)
_BIG = re.compile(r"(\d+)\s*(?:x\s*)?(?:nvidia\s*)?(?:h100|h200|a100|b200|gb200|gpus?)\b", re.IGNORECASE)


def score_code(ans: dict, task: dict, profile: dict, kg: KG) -> dict[str, float | None]:
    """Rules that a program can decide. None = abstain (the rule cannot tell)."""
    out: dict[str, float | None] = dict.fromkeys(IDS)
    exps = ans.get("experiments") or []
    out["baseline"] = float(bool(exps) and all(not _NONE.match(e.get("baseline") or "") and
                                               len((e.get("baseline") or "").split()) >= 2 for e in exps))
    out["measure"] = float(bool(exps) and all(len((e.get("measure") or "").split()) >= 2 and
                                              not _VAGUE.search(e.get("measure") or "") for e in exps))
    projects = ans.get("projects") or []
    out["stack_named"] = float(bool(projects) and all(
        sum(1 for s in p.get("stack") or [] if s.strip().lower() not in GENERIC) >= 2 for p in projects))
    names = list(dict.fromkeys(G._names(ans)))
    specific = [n for n in names if n.lower() not in GENERIC]
    out["specific_names"] = float(len(specific) >= 3)
    resolved = [G._resolve(kg, n) for n in specific]
    out["no_invented"] = 1.0 if specific and all(resolved) else None     # unknown names: cannot tell real from invented
    text = G._blind(ans)
    out["flags_uncertainty"] = float(bool(_HEDGE.search(text)))
    big = [int(m.group(1)) for m in _BIG.finditer(text)]
    has_cluster = re.search(r"cluster|a100s|several gpus|multi-gpu", profile.get("constraints", ""), re.IGNORECASE)
    if big and max(big) >= 8 and not has_cluster:
        out["fit_compute"] = 0.0                                            # needs ≥ 8 GPUs; the person has fewer
    return out


# ---- scorer 2 · Jev (TypeSafe System One) --------------------------------------------------------------------
def jev_questions() -> dict:
    return {i: {"type": "noul", "instructions": f"About the `advice` given to `person`: {q}",
                "criteria": {"true": "yes, the advice as written meets this", "false": "no, or only partly"}}
            for i, (_, q) in ITEMS.items()}


def score_jev(ans: dict, task: dict, profile: dict, sheet: str, client=None) -> dict[str, float | None]:
    from cf.llm.typesafe import Jev
    state = {"person": _person(task, profile), "reference": sheet, "advice": G._blind(ans)}
    answers = (client or Jev()).ask(state, jev_questions(), name="checklist_jev")
    return {i: (float(answers[i]["noul"]) if answers.get(i, {}).get("type") == "noul" else None) for i in IDS}   # refusal → None


# ---- scorer 3 · LLM judge -----------------------------------------------------------------------------------
LLM_CHECK = """You check advice given to this person: {label}. Background: {background} Constraints: {constraints}
Goal: {goal} Success looks like: {success}
Answer every item below about the advice AS WRITTEN. For each item, first write the evidence: quote or point to the
part of the advice that decides it (or say what is missing). Then answer yes or no. Partly met is no.
A REFERENCE sheet describes names in the advice from a curated knowledge base; "not in reference" does not mean false.
Items:
{items}"""


def score_llm(judge: str, ans: dict, task: dict, profile: dict, sheet: str) -> dict[str, float | None]:
    items = "\n".join(f"- {i}: {q}" for i, (_, q) in ITEMS.items())
    out = LLM(judge).parse(LLM_CHECK.format(items=items, **{k: profile.get(k, "") for k in
                                                           ("label", "background", "constraints", "goal", "success")}),
                           f"Question:\n{task['question']}\n\n{sheet}\n\nAdvice:\n{G._blind(ans)}", ChecklistAnswer,
                           "checklist_llm", max_tokens=4000, reasoning_max_tokens=AUTO)
    got = {v.item: (1.0 if v.answer == "yes" else 0.0) for v in out.verdicts}
    return {i: got.get(i) for i in IDS}


# ---- running scorers ----------------------------------------------------------------------------------------
def scorers_from(names: list[str]) -> list[str]:
    """Config names: "code", "jev", "llm:<openrouter model id>"."""
    for n in names:
        if n not in ("code", "jev") and not n.startswith("llm:"):
            raise ValueError(f"unknown checklist scorer {n!r}")
    return names


def score_one(scorer: str, ans: dict, task: dict, profile: dict, sheet: str, kg: KG, jev=None) -> dict:
    if scorer == "code":
        return score_code(ans, task, profile, kg)
    if scorer == "jev":
        return score_jev(ans, task, profile, sheet, client=jev)
    return score_llm(scorer.split(":", 1)[1], ans, task, profile, sheet)


def score_runs(scorers: list[str], runs: list[dict], tasks: dict, profiles: dict, sheets: dict, kg: KG,
               workers: int = 6, jev=None) -> list[dict]:
    """One row per (scorer, run): {scorer, task_id, model, condition, items: {id: p}}."""
    jobs = [(s, r) for s in scorers_from(scorers) for r in runs if r.get("answer")]

    def go(job):
        s, r = job
        t = tasks[r["task_id"]]
        items = score_one(s, r["answer"], t, profiles[t["persona"]], sheets[(r["task_id"], r["model"])], kg, jev)
        return {"scorer": s, "task_id": r["task_id"], "persona": t["persona"], "model": r["model"],
                "condition": r["condition"], "items": items}
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(go, jobs))


# ---- validating scorers: defects each must catch ------------------------------------------------------------
FAMOUS_WRONG = "Theano"           # famous, real, discontinued in 2017: wrong in a current plan
FAKE_NAME = "QuantaForge"         # made up
TARGETS = {"generic": ("specific_names", "stack_named"), "false_claim": ("no_invented",),
           "infeasible": ("fit_compute", "first_step_day"), "no_baseline": ("baseline", "measure"),
           "famous_wrong": ("no_dated",), "fake_name": ("no_invented",)}


def swap_name(ans: dict, kg: KG, new: str) -> dict | None:
    """Replace the first specific stack item that the KB knows with `new`, everywhere in the answer."""
    names = [n for n in G._names(ans) if n.lower() not in GENERIC and G._resolve(kg, n)]
    if not names:
        return None
    old = names[0]
    return json.loads(json.dumps(ans).replace(json.dumps(old)[1:-1], new))


def perturb(ans: dict, kind: str, kg: KG) -> dict | None:
    from cf.bench.agency import perturb as base
    if kind == "famous_wrong":
        return swap_name(ans, kg, FAMOUS_WRONG)
    if kind == "fake_name":
        return swap_name(ans, kg, FAKE_NAME)
    return base(ans, kind)


def unit_tests(scorers: list[str], tasks: list[dict], answers: list[dict], profiles: dict, kg: KG,
               workers: int = 6, jev=None) -> dict:
    """For each good answer, scorer and defect: did the targeted item flip from yes (p ≥ 0.5) to no?
    Cases where the scorer already failed the item, or abstains after the defect, are not informative and are
    skipped; a rule that abstains on the good answer but says no after the defect counts as detected.
    familiarity_gap = detection(fake_name) − detection(famous_wrong): > 0 means a made-up name is caught more often
    than a famous one that is wrong for the plan (Theano, discontinued in 2017), i.e. familiar names get a pass."""
    cases = []
    for i, (t, a) in enumerate(zip(tasks, answers, strict=True)):
        for kind in TARGETS:
            b = perturb(a, kind, kg)
            if b is not None:
                cases.append((i, kind, b))
    jobs = [(s, "base", i, answers[i]) for s in scorers for i in range(len(tasks))] + \
           [(s, kind, i, b) for s in scorers for i, kind, b in cases]

    def go(job):
        s, _kind, i, ans = job
        t = tasks[i]
        return job[:3], score_one(s, ans, t, profiles[t["persona"]], G.fact_sheet(kg, ans), kg, jev)
    with ThreadPoolExecutor(workers) as pool:
        got = dict(pool.map(go, jobs))
    rows = []
    for s in scorers:
        for i, kind, _ in cases:
            for item in TARGETS[kind]:
                before, after = got[(s, "base", i)].get(item), got[(s, kind, i)].get(item)
                # skip uninformative cases: abstained after the defect, or already failing before it.
                # A rule that abstains on the good answer but fires on the defect (e.g. "needs 64 H100s") counts.
                if after is None or (before is not None and before < 0.5) or (before is None and after >= 0.5):
                    continue
                rows.append({"scorer": s, "task": tasks[i]["id"], "kind": kind, "item": item,
                             "before": before, "after": after, "detected": after < 0.5})
    summary = {}
    for s in scorers:
        mine = [r for r in rows if r["scorer"] == s]
        by = {k: (round(sum(r["detected"] for r in mine if r["kind"] == k) / n, 3) if (n := sum(1 for r in mine if r["kind"] == k)) else None)
              for k in TARGETS}
        fam = by["fake_name"] - by["famous_wrong"] if by["fake_name"] is not None and by["famous_wrong"] is not None else None
        summary[s] = {"detected": round(sum(r["detected"] for r in mine) / len(mine), 3) if mine else None,
                      "n": len(mine), "by_kind": by, "familiarity_gap": None if fam is None else round(fam, 3)}
    return {"summary": summary, "rows": rows}


# ---- comparing scorers --------------------------------------------------------------------------------------
def agreement(rows: list[dict]) -> dict:
    """Per pair of scorers and per item: n (both answered), agreement at 0.5, Cohen's kappa, mean |p − q|."""
    by = defaultdict(dict)
    for r in rows:
        by[(r["task_id"], r["model"], r["condition"])][r["scorer"]] = r["items"]
    scorers = sorted({r["scorer"] for r in rows})
    out = {}
    for ai, a in enumerate(scorers):
        for b in scorers[ai + 1:]:
            per = {}
            for item in IDS:
                pairs = [(v[a][item], v[b][item]) for v in by.values()
                         if a in v and b in v and v[a][item] is not None and v[b][item] is not None]
                if not pairs:
                    continue
                xa, xb = [int(p >= 0.5) for p, _ in pairs], [int(q >= 0.5) for _, q in pairs]
                per[item] = {"n": len(pairs), "agree": round(sum(x == y for x, y in zip(xa, xb, strict=True)) / len(pairs), 3),
                             "kappa": G._kappa(xa, xb), "mean_abs_diff": round(sum(abs(p - q) for p, q in pairs) / len(pairs), 3)}
            out[f"{a} vs {b}"] = per
    return out


def pass_rates(rows: list[dict]) -> dict:
    """Mean P(yes) per (scorer, model, condition), overall and per item (abstentions excluded)."""
    acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for item, p in r["items"].items():
            if p is not None:
                acc[(r["scorer"], r["model"], r["condition"])][item].append(p)
    return {"|".join(k): {"overall": round(sum(sum(v) for v in d.values()) / max(sum(len(v) for v in d.values()), 1), 3),
                          "items": {i: round(sum(v) / len(v), 3) for i, v in d.items()}} for k, d in acc.items()}


def report(rows: list[dict], ut: dict | None = None) -> str:
    L = ["## Checklist (typed yes/no items; P(yes), abstentions excluded)", ""]
    pr = pass_rates(rows)
    scorers = sorted({r["scorer"] for r in rows})
    cells = sorted({(r["model"], r["condition"]) for r in rows})
    L += ["| Model | Condition | " + " | ".join(s.split("/")[-1] for s in scorers) + " |", "|---|---|" + "---|" * len(scorers)]
    for m, c in cells:
        L.append(f"| {m.split('/')[-1]} | {c} | " + " | ".join(
            f"{pr[k]['overall']:.2f}" if (k := f"{s}|{m}|{c}") in pr else "–" for s in scorers) + " |")
    L += ["", "### Per item (mean over models and conditions)", "", "| Item | Dimension | " +
          " | ".join(s.split("/")[-1] for s in scorers) + " |", "|---|---|" + "---|" * len(scorers)]
    for item, (dim, _) in ITEMS.items():
        vals = []
        for s in scorers:
            xs = [r["items"][item] for r in rows if r["scorer"] == s and r["items"].get(item) is not None]
            vals.append(f"{sum(xs) / len(xs):.2f}" if xs else "abstains")
        L.append(f"| {item} | {dim} | " + " | ".join(vals) + " |")
    ag = agreement(rows)
    if ag:
        L += ["", "### Scorer agreement per item (agreement at 0.5 · Cohen's κ · n)", "",
              "| Item | " + " | ".join(ag) + " |", "|---|" + "---|" * len(ag)]
        for item in IDS:
            L.append(f"| {item} | " + " | ".join(
                (f"{d[item]['agree']:.0%} · {d[item]['kappa'] if d[item]['kappa'] is not None else '–'} · {d[item]['n']}"
                 if item in d else "–") for d in ag.values()) + " |")
    if ut:
        L += ["", "### Scorer unit tests (targeted item flips yes → no)", "",
              "| Scorer | Detected | n | " + " | ".join(TARGETS) + " | familiarity gap |", "|---|---|---|" + "---|" * (len(TARGETS) + 1)]
        for s, v in ut["summary"].items():
            L.append(f"| {s.split('/')[-1]} | {v['detected'] if v['detected'] is not None else '–'} | {v['n']} | " + " | ".join(
                "–" if v["by_kind"][k] is None else f"{v['by_kind'][k]:.0%}" for k in TARGETS) +
                f" | {'–' if v['familiarity_gap'] is None else v['familiarity_gap']} |")
        L += ["", ("Familiarity gap = detection of a made-up name − detection of a famous but wrong one (Theano) in the same "
              "slot. Above 0: the scorer lets famous names pass.")]
    return "\n".join(L) + "\n"
