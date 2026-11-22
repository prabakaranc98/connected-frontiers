"""Guidance eval: does grounding in the KB improve learn / build / experiment guidance, and can a
small grounded model match a large ungrounded one?

Tasks: persona × anchor (student and research engineer × a method; forward-deployed engineer × a
problem area). Each answer is structured: what to learn (in order), projects (stack + first step),
experiments (question, baseline, change, measure), the stack.

Two independent scores
- deterministic (KB): share of named tools / orgs / methods that exist in the KB, citation validity,
  specificity (concrete named items), entities new vs the same model closed-book.
- rubric judges (general quality, not "agrees with the KB", which would favour grounding by
  construction): two judges from families not under test, 1–5 per dimension, plus pairwise preference
  in BOTH orders (position bias), citations stripped so judges cannot tell which answer was grounded.
A blind sheet of pairs goes to the owner to calibrate the judges (κ).
"""

from __future__ import annotations

import copy
import json
import random
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cf import config, trace
from cf.agent.harness import _touched
from cf.agent.kg import KG, TOOL_SPECS
from cf.bench.sessions import _ok
from cf.eval.stats import bootstrap
from cf.llm.client import AUTO, LLM, BudgetExceeded, strict_schema

SMALL = ["thinkingmachines/inkling-2-small", "qwen/qwen3.5-35b-a3b"]
LARGE = ["qwen/qwen3.5-397b-a17b", "deepseek/deepseek-v4-pro"]
JUDGES = ["z-ai/glm-5.3", "nvidia/nemotron-3.5-super-vl"]         # families neither tested nor examining
CONDITIONS = ("closed_book", "kg_tools", "kg_agentic")
GROUNDED_HARNESS = {"neighbor_limit": 50, "truncation_notice": True, "empty_hints": True, "schema_card": True}


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Project(_S):
    title: str
    what: str
    stack: list[str]
    first_step: str


class Experiment(_S):
    question: str
    baseline: str
    change: str
    measure: str


class Guidance(_S):
    summary: str
    learn: list[str]
    projects: list[Project]
    experiments: list[Experiment]
    stack: list[str]
    sources: list[str]


SCHEMA = strict_schema(Guidance)

PERSONAS = {
    "student": ("method", ("I'm a student who wants to get into {a}. Over the next 8 weeks, what should I learn first and in "
                          "what order, what should I build, and which small experiments should I run? Suggest a concrete "
                          "tech stack and 2-3 project ideas based on what companies actually do.")),
    "research_engineer": ("method", ("I'm a research engineer who wants to work on {a}. Give me a learning path, 2 projects "
                                    "that reproduce or extend what organisations do in practice, and 2 controlled "
                                    "experiments with a baseline and a metric. Name the stack.")),
    "fde": ("org", ("I'm a forward-deployed engineer about to start working with {a} as a customer. Which stack and "
                    "practices should I expect, what should I prototype before day one, and what should I measure in the "
                    "first deployment?")),
}

SYS_GROUNDED = ("You advise students and engineers. You have tools over a knowledge graph of the AI ecosystem: who works on "
                "what, which methods and tools organisations use, which models and benchmarks exist, who hires for what. "
                "Explore it first: find the anchor, follow relations to organisations, methods, tools and benchmarks. Base "
                "your advice on what you find, and prefer concrete names from the graph. Then answer in prose; you will "
                "then be asked for the structured form.")
SYS_CLOSED = ("You advise students and engineers on AI work. Answer from your own knowledge. Be concrete: name real "
              "organisations, tools, methods and benchmarks, and say what is uncertain.")
FORMAT = ("Now give your advice as JSON: summary (2-3 sentences), learn (at most 6 ordered topics), projects (2-3: "
          "title, what, stack of at most 6 tools, first_step), experiments (1-2: question, baseline, change, measure), stack "
          "(at most 8 tools and platforms), sources (edge ids you relied on, or [] if none). In the advice itself do not "
          "mention your tools, a graph or your sources; put sources only in `sources`.")
CAPS = {"learn": 6, "stack": 8, "projects": 3, "experiments": 2}


def _cap(a: dict) -> dict:
    """Same size limits for every condition (length bias)."""
    a = dict(a)
    for k, n in CAPS.items():
        a[k] = (a.get(k) or [])[:n]
    a["projects"] = [{**p, "stack": (p.get("stack") or [])[:6]} for p in a["projects"]]
    return a


GOALS = {"student": "8 weeks, a laptop and one rented GPU", "research_engineer": "one quarter, a small cluster",
         "fde": "two weeks before the first customer meeting"}


def salient(kg: KG, a: str, k: int = 12) -> list[str]:
    """Examiner's reference facts for a task: the anchor's strongest neighbours across relation types
    (organisations, methods, tools, benchmarks, roles), from supported edges only."""
    nb = []
    for eid in kg.adj.get(a, []):
        e = kg.edges[eid]
        if e["status"] == "unsupported":
            continue
        o = e["tail"] if e["head"] == a else e["head"]
        if kg.ents[o]["type"] in ("org", "method", "technology", "benchmark", "model", "role", "dataset"):
            nb.append((e["strength"], kg.ents[o].get("pagerank") or 0, o))
    seen, out = set(), []
    for _, _, o in sorted(nb, reverse=True):
        if o not in seen:
            seen.add(o)
            out.append(o)
    return out[:k]


def tasks(per_persona: int = 6, rich: int = 4, seed: int = 13) -> list[dict]:
    """Examiner, agency tasks: persona × anchor × goal, stratified by how much the KB knows about the anchor
    (rich: ≥ 6 salient neighbours over ≥ 2 relation types; thin: 2-5), so grounding is not favoured by design.
    Rich and thin anchors are dealt round-robin to the personas that share an anchor kind; each anchor once."""
    kg = KG()
    rnd = random.Random(seed)
    by_kind: dict[str, list[str]] = defaultdict(list)
    for p, (kind, _) in PERSONAS.items():
        by_kind[kind].append(p)
    assigned: dict[str, list[tuple]] = defaultdict(list)
    for kind, personas in by_kind.items():
        pool = [e["id"] for e in kg.ents.values() if e["type"] == kind and _ok(kg, e["id"])
                and (kind != "org" or sum(kg.edges[x]["relation"] in ("uses_tech", "uses_method") and kg.edges[x]["head"] == e["id"]
                                          for x in kg.adj.get(e["id"], [])) >= 2)]
        rnd.shuffle(pool)
        rich_pool, thin_pool = [], []
        for a in pool:
            sal = salient(kg, a)
            rels = {kg.edges[x]["relation"] for x in kg.adj.get(a, []) if kg.edges[x]["status"] != "unsupported"}
            if len(sal) >= 6 and len(rels) >= 2:
                rich_pool.append((a, sal, "rich"))
            elif 2 <= len(sal) <= 5:
                thin_pool.append((a, sal, "thin"))
        for n_, src in ((rich, rich_pool), (per_persona - rich, thin_pool)):
            for k in range(n_ * len(personas)):
                if k < len(src):
                    assigned[personas[k % len(personas)]].append(src[k])
    out: list[dict] = []
    for p, (_, tmpl) in PERSONAS.items():
        for a, sal, stratum in assigned[p]:
            out.append({"id": f"G-{p}-{len(out):02d}", "persona": p, "anchor": a, "stratum": stratum,
                        "kb_version": kg.kb_version, "goal": GOALS[p], "salient": sal,
                        "question": tmpl.format(a=kg.name(a)) + f" Constraints: {GOALS[p]}."})
    return out


EXAMINER = "google/gemma-4-26b-a4b-it"            # curates + writes; a family neither tested nor judging


class Curate(_S):
    reason: str
    meaningful: bool


class Written(_S):
    request: str


CURATE = ("You check tasks for an evaluation of career and engineering guidance. Is '{a}' a meaningful, specific thing for "
          "{who} to {verb}? Reject generic words, study designs, vague slogans and company-internal jargon. Reason first.")
WRITE = ("Rewrite this request in the first person, as {who} would actually ask it: natural, specific, under 70 words, "
         "keeping the goal, the constraints and the subject '{a}'. Do not add any names of companies, tools or methods.")
WHO = {"student": ("a student", "learn and build with"), "research_engineer": ("a research engineer", "research and build"),
       "fde": ("a forward-deployed engineer", "deploy for as a customer")}


def examine(per_persona: int = 6, rich: int = 4, seed: int = 13) -> tuple[list[dict], list[dict]]:
    """Examiner for agency tasks: generate (graph) → check (deterministic) → curate (LLM) → write (LLM) → leak check.
    Over-generates candidates and keeps per_persona per persona, rich/thin as asked. Returns (accepted, rejected)."""
    kg = KG()
    cands = tasks(per_persona * 3, rich * 3, seed)
    keep: dict[str, list[dict]] = defaultdict(list)
    rejected = []
    for t in cands:
        p = t["persona"]
        want = rich if t["stratum"] == "rich" else per_persona - rich
        if sum(x["stratum"] == t["stratum"] for x in keep[p]) >= want:
            continue
        who, verb = WHO[p]
        a = kg.name(t["anchor"])
        try:
            c = LLM(EXAMINER).parse(CURATE.format(a=a, who=who, verb=verb), f"Subject: {a}", Curate, "guidance_curate",
                                    max_tokens=400, reasoning_max_tokens=0)
            if not c.meaningful:
                rejected.append({**t, "reason": f"curator: {c.reason[:160]}"})
                continue
            w = LLM(EXAMINER).parse(WRITE.format(who=who, a=a), t["question"], Written, "guidance_write",
                                    max_tokens=400, reasoning_max_tokens=0)
        except BudgetExceeded:
            raise
        except RuntimeError as e:
            rejected.append({**t, "reason": f"examiner error: {str(e)[:120]}"})
            continue
        leaked = [kg.name(x) for x in t["salient"] if len(kg.name(x)) > 3 and kg.name(x).lower() in w.request.lower()
                  and kg.name(x).lower() != a.lower()]
        if a.lower() not in w.request.lower() or leaked:
            rejected.append({**t, "reason": f"writer: subject dropped or leaked {leaked[:3]}"})
            continue
        keep[p].append({**t, "template_question": t["question"], "question": w.request, "examiner": EXAMINER,
                        "curator_reason": c.reason})
    acc = [t for p in PERSONAS for t in keep[p]]
    for i, t in enumerate(acc):
        t["id"] = f"G-{t['persona']}-{i:02d}"
    return acc, rejected


def run(model: str, task: dict, condition: str, kg: KG, max_steps: int = 14) -> dict:
    llm = LLM(model)
    t0, _spend0 = time.time(), LLM.spent_usd
    grounded = condition == "kg_tools"
    if grounded:
        kg = copy.copy(kg)
        kg.empty_hints, kg.truncation_notice, kg.neighbor_limit = True, True, GROUNDED_HARNESS["neighbor_limit"]
    system = SYS_GROUNDED + ("\n\n" + kg.schema_card() if grounded else "") if grounded else SYS_CLOSED
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": task["question"]}]
    tools = TOOL_SPECS if grounded else None
    steps, prose, err = [], "", None
    for step in range(max_steps):
        last = step == max_steps - 1
        if last and tools:
            msgs.append({"role": "user", "content": "Step budget reached: answer now."})
        try:
            m, _ = llm.chat(msgs, tools=None if last else tools, name=f"guidance_{condition}", max_tokens=3500,
                            reasoning_max_tokens=AUTO)
        except BudgetExceeded:
            raise
        except RuntimeError as e:
            err = str(e)[:200]
            break
        tcs = m.get("tool_calls") or []
        if tcs and tools and not last:
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
            for tc in tcs:
                fn = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                    res = getattr(kg, fn)(**args) if fn in {x["function"]["name"] for x in TOOL_SPECS} else {"error": "unknown tool"}
                except (TypeError, ValueError, KeyError) as e:
                    res = {"error": f"bad arguments: {e}"}
                steps.append({"step": step, "tool": fn, "args": tc["function"].get("arguments"),
                              "thought": (m.get("content") or "")[:1500], "touched": _touched(res)})
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res)[:6000]})
            continue
        prose = m.get("content") or ""
        break
    answer = None
    if not err:
        msgs += [{"role": "assistant", "content": prose}, {"role": "user", "content": FORMAT}]
        try:
            m2, _ = llm.chat(msgs, name=f"guidance_{condition}_format", max_tokens=3000, reasoning_max_tokens=AUTO, schema=SCHEMA)
            answer = _cap(json.loads(m2.get("content") or "{}"))
        except BudgetExceeded:
            raise
        except (RuntimeError, ValueError) as e:
            err = f"format: {str(e)[:160]}"
    out = {"task_id": task["id"], "persona": task["persona"], "question": task["question"], "model": model,
           "condition": condition, "kb_version": kg.kb_version, "run_id": trace.RUN_ID, "answer": answer, "steps": steps,
           "prose": prose[:6000],
           "error": err, "metrics": metrics(kg, answer, task) if answer else None, "stratum": task.get("stratum"),
           "cost_usd": round(llm.spent, 5), "latency_s": round(time.time() - t0, 1)}
    trace.event("agent", {"guidance": task["id"], "model": model, "condition": condition, "metrics": out["metrics"]})
    return out


# ---- agentic retrieval: plan → research (multi-step, reads evidence) → comprehend → synthesize → verify -----
class Plan(_S):
    subquestions: list[str]


class Finding(_S):
    finding: str
    entities: list[str]
    edge_ids: list[str]
    subquestion: int
    implication: str


class Notes(_S):
    findings: list[Finding]


class LinkedProject(_S):
    title: str
    what: str
    stack: list[str]
    first_step: str
    based_on: list[int]


class AgenticGuidance(_S):
    summary: str
    learn: list[str]
    learn_based_on: list[int]
    projects: list[LinkedProject]
    experiments: list[Experiment]
    stack: list[str]
    sources: list[str]


PLAN = ("You are preparing advice for the person below. Before answering, plan research in a knowledge graph of the "
        "AI ecosystem (organisations, methods, tools, models, benchmarks, datasets, roles, with sourced evidence). "
        "Write 4-6 sub-questions whose answers would change your advice, for example: who does this in practice and "
        "for what; which methods and variants they use; which tools and platforms offer it; which data and evaluations "
        "are used; which models were built this way; who hires for it. Make each sub-question answerable by looking "
        "things up, not by opinion.")
RESEARCH = ("Research the sub-questions with the tools, in several steps:\n"
            "1. Find the anchor entity, then look at its neighbours by relation.\n"
            "2. Follow up: from an organisation to its methods, tools, customers and roles; from a method to who offers "
            "and uses it; from a model to its base and benchmarks.\n"
            "3. READ before relying: call `evidence` on the edges you will use, to see what the source actually says "
            "(a self-claim, a customer story, a benchmark result).\n"
            "4. When a query returns nothing, use the hints it gives to try another relation.\n"
            "When every sub-question has an answer or a clear 'not in the graph', reply with a short summary.")
NOTES = ("Turn your research into notes. 5-8 findings. Each finding: what you learned, specific and in one or two "
         "sentences; the entities involved; the edge ids that support it; the sub-question it answers (1-based); and "
         "what it implies for this person (a skill to learn, a project to build, a tool to use, a gap to exploit). "
         "Only what you found with the tools; say 'self-claimed' when the source is the company itself.")
ADVISE = ("Now give your advice as JSON, built FROM your findings. Every project lists in `based_on` the indices "
          "(0-based) of the findings it builds on; `learn_based_on` lists the findings behind the learning path. Prefer "
          "the specific organisations, tools, methods, models and benchmarks you found; use general knowledge only "
          "where the findings are silent, with an empty `based_on`. Make experiments controlled: one question, a "
          "baseline, one change, a measure. Limits: learn ≤ 6, projects 2-3 (stack ≤ 6 each), experiments 1-2, stack "
          "≤ 8. Do not mention your tools or a graph in the text; put edge ids only in `sources`.")
READ_GATE = ("You have not read any evidence yet. Before writing notes, call `evidence` on the 3-5 edges your advice "
             "will rely on most, and note what each source actually says.")
ADVISE_FIT = ("Now give your advice as JSON, built FROM your findings AND fitted to this person. Rules:\n"
              "1. Scope from their constraints: ONE main project sized to their stated time and compute, plus at most "
              "one optional stretch project. The first step of the main project must be doable in a day.\n"
              "2. Downscale frontier practice to their level: start with the smallest version that teaches the same "
              "thing (e.g. a plain reference implementation before modifying a large production codebase).\n"
              "3. Check prerequisites: hardware (e.g. which GPU generations a method needs), access, skills and data "
              "must match what they have; if not, change the plan.\n"
              "4. Every project lists in `based_on` the indices (0-based) of the findings it builds on; general "
              "knowledge only where findings are silent.\n"
              "5. Experiments are controlled: one question, a baseline, one change, a measure.\n"
              "Limits: learn ≤ 6, projects 1-2 (stack ≤ 6), experiments 1-2, stack ≤ 8. Do not mention your tools or a "
              "graph in the text; put edge ids only in `sources`.")


class Prereq(_S):
    project: str
    requirement: str
    person_has_it: bool
    fix: str


class PrereqCheck(_S):
    checks: list[Prereq]


PREREQ = ("Check your advice against this person. For each project, list its hard prerequisites (hardware and GPU "
          "generation, access to systems or data, skills, time) and whether the person has each one given their "
          "profile. Be strict and specific.")
PREREQ_REVISE = ("These prerequisites are not met: {gaps}. Revise the advice so every project is feasible for this "
                 "person (change the project, downscale it, or add the missing step), keeping the same JSON form.")


def _profile_text(task: dict) -> str:
    p = task.get("profile") or {}
    return (f"\n\nAbout the person: {p.get('label', '')}. Background: {p.get('background', '')} Constraints: "
            f"{p.get('constraints', '')} Goal: {p.get('goal', '')} Success looks like: {p.get('success', '')}") if p else ""


REVISE = ("These projects do not build on any finding: {titles}. Revise the advice so that each project builds on at "
          "least one finding (or replace it with one that does), keeping the same JSON form.")


def _structured(llm, msgs, out_cls, name, max_tokens=6000):
    """Structured call with one retry on truncated or invalid JSON (asks for a shorter answer)."""
    for attempt in range(2):
        extra = [] if not attempt else [{"role": "user", "content": "Your last answer was cut off. Be more concise: at most 8 "
                                                                    "items, two short sentences each."}]
        m, _ = llm.chat(msgs + extra, name=name, max_tokens=max_tokens, reasoning_max_tokens=AUTO, schema=strict_schema(out_cls))
        try:
            return json.loads(m.get("content") or "{}")
        except ValueError:
            if attempt:
                raise
    return {}


def _resolve(kg: KG, name: str) -> str | None:
    m = kg.match(name or "", k=1, exact_first=True)
    return m[0][1] if m and m[0][0] >= 0.9 else None


def _tool_loop(llm, msgs, kg, steps, max_steps, name):
    """One research loop; returns the final prose. Appends to msgs and steps."""
    for step in range(max_steps):
        last = step == max_steps - 1
        if last:
            msgs.append({"role": "user", "content": "Step budget reached: summarise what you learned."})
        m, _ = llm.chat(msgs, tools=None if last else TOOL_SPECS, name=name, max_tokens=2500, reasoning_max_tokens=AUTO)
        tcs = m.get("tool_calls") or []
        if tcs and not last:
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
            for tc in tcs:
                fn = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                    res = getattr(kg, fn)(**args) if fn in {x["function"]["name"] for x in TOOL_SPECS} else {"error": "unknown tool"}
                except (TypeError, ValueError, KeyError) as e:
                    res = {"error": f"bad arguments: {e}"}
                steps.append({"step": len(steps), "tool": fn, "args": tc["function"].get("arguments"),
                              "thought": (m.get("content") or "")[:1500], "touched": _touched(res), "phase": name})
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res)[:6000]})
            continue
        prose = m.get("content") or ""
        msgs.append({"role": "assistant", "content": prose})
        return prose
    return ""


def run_agentic(model: str, task: dict, kg: KG, max_steps: int = 18, off: frozenset = frozenset(),
                on: frozenset = frozenset()) -> dict:
    """plan → research (multi-step) → evidence gate → notes → coverage reflection → advise → synthesis check.
    `off` switches parts off for ablations: plan, read (evidence gate), reflect (coverage reflection), revise
    (synthesis check), notes (advise straight from research)."""
    llm = LLM(model)
    t0, _spend0 = time.time(), LLM.spent_usd
    kg = copy.copy(kg)
    kg.empty_hints, kg.truncation_notice, kg.neighbor_limit = True, True, GROUNDED_HARNESS["neighbor_limit"]
    fit = "fit" in on                                # fit-first variant: profile in context, scoped advice, prerequisite gate
    msgs = [{"role": "system", "content": SYS_GROUNDED + (_profile_text(task) if fit else "") + "\n\n" + kg.schema_card()},
            {"role": "user", "content": task["question"]}]
    steps: list[dict] = []
    err, plan, notes, answer, prose, gates = None, [], [], None, "", {"read_gate": False, "reflection": [], "revised": False}
    try:
        if "plan" not in off:
            m, _ = llm.chat(msgs + [{"role": "user", "content": PLAN}], name="guidance_agentic_plan", max_tokens=800,
                            reasoning_max_tokens=AUTO, schema=strict_schema(Plan))
            plan = json.loads(m.get("content") or "{}").get("subquestions", [])[:6]
            msgs.append({"role": "user", "content": RESEARCH + "\n\nSub-questions:\n" + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(plan))})
        else:
            msgs.append({"role": "user", "content": RESEARCH})
        prose = _tool_loop(llm, msgs, kg, steps, max_steps, "guidance_agentic_research")
        if "read" not in off and not any(s_["tool"] in ("evidence", "passage") for s_ in steps):   # evidence gate
            gates["read_gate"] = True
            msgs.append({"role": "user", "content": READ_GATE})
            prose += "\n" + _tool_loop(llm, msgs, kg, steps, 8, "guidance_agentic_read")
        for round_ in range(0 if "notes" in off else 2):                            # notes + coverage reflection
            notes = _structured(llm, msgs + [{"role": "user", "content": NOTES}], Notes, "guidance_agentic_notes").get("findings", [])[:10]
            covered = {f.get("subquestion") for f in notes}
            missing = [i + 1 for i in range(len(plan)) if i + 1 not in covered]
            if not missing or round_ == 1 or "reflect" in off:
                break
            gates["reflection"] = missing
            msgs.append({"role": "user", "content": "These sub-questions have no finding yet: "
                         + "; ".join(f"{i}. {plan[i - 1]}" for i in missing) + ". Research just these, then summarise."})
            prose += "\n" + _tool_loop(llm, msgs, kg, steps, 8, "guidance_agentic_reflect")
        msgs += [{"role": "user", "content": NOTES}, {"role": "assistant", "content": json.dumps({"findings": notes})}]
        advise_prompt = ADVISE_FIT if fit else ADVISE
        answer = _structured(llm, msgs + [{"role": "user", "content": advise_prompt}], AgenticGuidance, "guidance_agentic_advise")
        unlinked = [p_["title"] for p_ in answer.get("projects") or [] if not p_.get("based_on")]
        if "revise" not in off and answer.get("projects") and len(unlinked) > len(answer["projects"]) / 2:   # synthesis check
            gates["revised"] = True
            msgs += [{"role": "user", "content": advise_prompt}, {"role": "assistant", "content": json.dumps(answer)},
                     {"role": "user", "content": REVISE.format(titles="; ".join(unlinked))}]
            answer = _structured(llm, msgs, AgenticGuidance, "guidance_agentic_revise")
        if fit:                                                                     # prerequisite gate
            ctx = msgs + [{"role": "user", "content": advise_prompt}, {"role": "assistant", "content": json.dumps(answer)}]
            chk = _structured(llm, ctx + [{"role": "user", "content": PREREQ}], PrereqCheck, "guidance_agentic_prereq").get("checks", [])
            gaps = [f"{c['project']}: {c['requirement']}" for c in chk if not c.get("person_has_it")]
            gates["prereq_gaps"] = gaps
            if gaps:
                answer = _structured(llm, ctx + [{"role": "user", "content": PREREQ_REVISE.format(gaps="; ".join(gaps[:8]))}],
                                     AgenticGuidance, "guidance_agentic_prereq_revise")
        answer = _cap(answer)
    except BudgetExceeded:
        raise
    except (RuntimeError, ValueError) as e:
        err = str(e)[:200]
    met = metrics(kg, answer, task) if answer else None
    if met and answer:
        projects = answer.get("projects") or []
        met = {**met, "findings": len(notes), "findings_with_valid_edges": sum(1 for f in notes if any(x in kg.edges for x in f.get("edge_ids") or [])),
               "projects_linked_to_findings": round(sum(1 for p_ in projects if p_.get("based_on")) / max(len(projects), 1), 3),
               "evidence_reads": sum(1 for s_ in steps if s_["tool"] in ("evidence", "passage", "documents")),
               "salient_in_findings": round(len({x for f in notes for n in f.get("entities") or [] if (x := _resolve(kg, n))}
                                                 & set(task.get("salient") or [])) / max(len(task.get("salient") or []), 1), 3),
               "plan_coverage": round(len({f.get("subquestion") for f in notes} & set(range(1, len(plan) + 1))) / max(len(plan), 1), 3)}
    out = {"task_id": task["id"], "persona": task["persona"], "question": task["question"], "model": model,
           "condition": "kg_agentic" + ("+" + "+".join(sorted(on)) if on else "") + (":" + ",".join(sorted(off)) if off else ""),
           "kb_version": kg.kb_version,
           "run_id": trace.RUN_ID, "plan": plan, "notes": notes,
           "gates": gates, "answer": answer, "steps": steps, "prose": prose[:6000], "error": err, "metrics": met,
           "stratum": task.get("stratum"), "cost_usd": round(llm.spent, 5), "latency_s": round(time.time() - t0, 1)}
    trace.event("agent", {"guidance": task["id"], "model": model, "condition": "kg_agentic", "metrics": met, "gates": gates})
    return out


# ---- memory-first, graph-enriched: draft from memory → check claims in the graph → revise only what evidence changes ----
class Check(_S):
    claim: str
    kind: Literal["name", "fact", "who_now", "gap"]
    lookup: str


class Checks(_S):
    checks: list[Check]


class Change(_S):
    kind: Literal["replaced", "added", "flagged", "gap", "removed"]
    what: str
    finding: int


class EnrichedGuidance(_S):
    summary: str
    learn: list[str]
    learn_based_on: list[int]
    projects: list[LinkedProject]
    experiments: list[Experiment]
    stack: list[str]
    sources: list[str]
    changes: list[Change]


CHECKS = ("Here is a draft of your advice, written from your own knowledge:\n{draft}\n\nList 5-8 things in it that a "
          "knowledge graph of the AI ecosystem could confirm, correct or sharpen: named tools, organisations, datasets "
          "and benchmarks (kind `name`); factual claims about who uses or offers what (kind `fact`); and always one "
          "`who_now` check (which organisations do this in practice now) and one `gap` check (what is missing or "
          "unverified). For each, write what to look up.")
ENRICH_RESEARCH = ("Check these items with the tools. Find the entity, follow its relations, and call `evidence` on "
                   "the edges you will rely on. Record 'not in the graph' when a lookup finds nothing; that is not "
                   "proof the claim is false. When every item is checked, reply with a short summary.")
ENRICH = ("Now revise the draft. Keep its structure, its learning path and its projects where the evidence does not "
          "change them: the draft is the plan. Change only what the findings change:\n"
          "- replace a name the findings show is wrong or dated;\n"
          "- add a specific organisation, tool, dataset or benchmark the findings show is used for this;\n"
          "- flag a fact that is only self-claimed or unverified;\n"
          "- state a gap the findings show (e.g. no benchmark exists for X), if it changes the plan.\n"
          "List every change in `changes` with the finding index (0-based) behind it. Projects list in `based_on` the "
          "findings they use (empty if unchanged from the draft). Limits: learn ≤ 6, projects 2-3 (stack ≤ 6 each), "
          "experiments 1-2, stack ≤ 8. Do not mention your tools or a graph in the text; put edge ids only in `sources`.")


def run_enrich(model: str, task: dict, kg: KG, draft: dict, max_steps: int = 14) -> dict:
    """Memory-first: `draft` is this model's closed-book answer (the same one the closed-book condition is scored
    on), so the comparison isolates what grounding changes. Returns the revised answer plus the recorded diff."""
    llm = LLM(model)
    t0 = time.time()
    kg = copy.copy(kg)
    kg.empty_hints, kg.truncation_notice, kg.neighbor_limit = True, True, GROUNDED_HARNESS["neighbor_limit"]
    d = draft.get("answer") or {}
    msgs = [{"role": "system", "content": SYS_GROUNDED + "\n\n" + kg.schema_card()},
            {"role": "user", "content": task["question"]}]
    steps: list[dict] = []
    err, checks, notes, answer, prose = None, [], [], None, ""
    try:
        checks = _structured(llm, msgs + [{"role": "user", "content": CHECKS.format(draft=_blind(d))}], Checks,
                             "guidance_enrich_checks", max_tokens=1500).get("checks", [])[:8]
        msgs.append({"role": "user", "content": ENRICH_RESEARCH + "\n\nItems:\n" +
                     "\n".join(f"{i + 1}. [{c['kind']}] {c['claim']} → look up: {c['lookup']}" for i, c in enumerate(checks))})
        prose = _tool_loop(llm, msgs, kg, steps, max_steps, "guidance_enrich_research")
        notes = _structured(llm, msgs + [{"role": "user", "content": NOTES}], Notes, "guidance_enrich_notes").get("findings", [])[:10]
        msgs += [{"role": "user", "content": NOTES}, {"role": "assistant", "content": json.dumps({"findings": notes})},
                 {"role": "user", "content": "The draft again:\n" + _blind(d) + "\n\n" + ENRICH}]
        answer = _structured(llm, msgs, EnrichedGuidance, "guidance_enrich_revise")
        changes = answer.pop("changes", [])
        answer = _cap(answer)
    except BudgetExceeded:
        raise
    except (RuntimeError, ValueError) as e:
        err, changes = str(e)[:200], []
    met = metrics(kg, answer, task) if answer else None
    if met:
        before, after = set(_names(d)), set(_names(answer))
        met = {**met, "findings": len(notes), "changes": len(changes),
               "changes_by_kind": {k: sum(1 for c in changes if c.get("kind") == k) for k in ("replaced", "added", "flagged", "gap", "removed")},
               "names_added": sorted(after - before), "names_removed": sorted(before - after),
               "evidence_reads": sum(1 for s_ in steps if s_["tool"] in ("evidence", "passage", "documents")),
               "salient_in_findings": round(len({x for f in notes for n in f.get("entities") or [] if (x := _resolve(kg, n))}
                                                 & set(task.get("salient") or [])) / max(len(task.get("salient") or []), 1), 3)}
    out = {"task_id": task["id"], "persona": task["persona"], "question": task["question"], "model": model,
           "condition": "kg_enrich", "kb_version": kg.kb_version, "run_id": trace.RUN_ID, "plan": [c.get("claim") for c in checks],
           "checks": checks, "notes": notes, "changes": changes, "draft": d, "answer": answer, "steps": steps,
           "prose": prose[:6000], "error": err, "metrics": met, "stratum": task.get("stratum"),
           "cost_usd": round(llm.spent + (draft.get("cost_usd") or 0), 5), "latency_s": round(time.time() - t0, 1)}
    trace.event("agent", {"guidance": task["id"], "model": model, "condition": "kg_enrich", "metrics": met})
    return out


# ---- deterministic, KB-checkable metrics -------------------------------------------------------------------
def _names(a: dict) -> list[str]:
    names = list(a.get("stack") or []) + list(a.get("learn") or [])
    for p in a.get("projects") or []:
        names += list(p.get("stack") or [])
    return [n.strip() for n in names if n and n.strip()]


def metrics(kg: KG, a: dict, task: dict | None = None) -> dict:
    names = list(dict.fromkeys(_names(a) + _mentions(kg, a)))
    hit = {}
    for n in names:
        m = kg.match(n, k=1, exact_first=True)
        if m and m[0][0] >= 0.9:
            hit[n] = m[0][1]
    srcs = [re.sub(r"[\[\]]|edge_id:", "", s).strip() for s in a.get("sources") or []]
    valid = [s for s in srcs if s in kg.edges]
    return {"named": len(names), "in_kb": len(hit), "kb_grounded_share": round(len(hit) / len(names), 3) if names else None,
            "kb_entities": sorted(set(hit.values())), "citations": len(srcs), "citations_valid": len(valid),
            "projects": len(a.get("projects") or []), "experiments": len(a.get("experiments") or []),
            "experiments_complete": sum(1 for e in a.get("experiments") or [] if all((e.get(k) or "").strip() for k in ("question", "baseline", "change", "measure"))),
            "chars": len(json.dumps(a)),
            "salient_coverage": round(len(set(hit.values()) & set(task["salient"])) / len(task["salient"]), 3)
            if task and task.get("salient") else None}


def _mentions(kg: KG, a: dict) -> list[str]:
    """Entity names mentioned in the free text (summary, project descriptions, steps): exact KB names only."""
    text = " ".join([a.get("summary") or ""] + [f"{p.get('what', '')} {p.get('first_step', '')}" for p in a.get("projects") or []])
    words = re.findall(r"[A-Za-z0-9][\w.+-]*", text)
    found = []
    for n in (4, 3, 2, 1):
        for i in range(len(words) - n + 1):
            g = " ".join(words[i:i + n])
            if len(g) >= 3:
                x = kg.exact(g)                       # exact names only: a fuzzy scan per n-gram is far too slow
                if x and kg.ents[x]["type"] in ("org", "technology", "method", "model", "benchmark"):
                    found.append(kg.name(x))
    return found


# ---- rubric judges (blind) ---------------------------------------------------------------------------------
RUBRIC = """You judge advice given to {persona_desc}. Score each dimension 1-5 (5 = excellent):
- accuracy: claims about tools, companies and methods are correct and current; nothing invented
- actionability: concrete steps, named stack, a clear first step; someone could start tomorrow
- insight: non-obvious, well-connected advice beyond a generic tutorial list
- experiment_design: experiments have a real question, a baseline, one controlled change, a measurable outcome
- fit: matches the person's role and the stated goal
Judge only the text. Length is not quality. A REFERENCE sheet lists what a curated knowledge base says about the
names in the answers; "not in reference" does NOT mean false. Write your rationale before your scores."""

PERSONA_DESC = {"student": "a student entering a field", "research_engineer": "a research engineer",
                "fde": "a forward-deployed engineer preparing for customer work"}


class Scores(_S):
    rationale: str
    accuracy: int = Field(ge=1, le=5)
    actionability: int = Field(ge=1, le=5)
    insight: int = Field(ge=1, le=5)
    experiment_design: int = Field(ge=1, le=5)
    fit: int = Field(ge=1, le=5)


class Pref(_S):
    rationale: str
    winner: Literal["A", "B", "tie"]


_LEAK = re.compile(r"\s?(according to|from|in|per) (the|our|my) (knowledge )?graph|knowledge graph|\bKG\b|edge[ _]?id", re.IGNORECASE)
# "The graph shows X" survived the filter above (found 2026-11-22 in one pilot answer): name the source neutrally
# instead of deleting words, so the sentence still reads. "CUDA Graph" and "graph neural network" are left alone.
_LEAK_THE = re.compile(r"\b(the|this|our|my) graph\b(?! neural)", re.IGNORECASE)


_CITE = re.compile(r"\[\s*(?:[a-z_]+:[^\]\s,]+(?:\|[^\]\s,]+)+)(?:\s*,\s*[a-z_]+:[^\]\s,]+(?:\|[^\]\s,]+)+)*\s*\]")


def _blind(a: dict) -> str:
    """The same plain-text rendering for every condition: summary, learning path, projects, experiments, stack.
    Internal pointers (sources, based_on) are dropped; inline edge-id citations and mentions of a graph are removed.
    (A previous version stripped every bracketed JSON list over six characters, which deleted whole sections.)"""
    a = a or {}
    L = ["Summary: " + (a.get("summary") or ""), "", "What to learn, in order:"]
    L += [f"{i + 1}. {x}" for i, x in enumerate(a.get("learn") or [])]
    L += ["", "Projects:"]
    for p_ in a.get("projects") or []:
        L += [f"- {p_.get('title', '')}: {p_.get('what', '')}", f"  Stack: {', '.join(p_.get('stack') or [])}",
              f"  First step: {p_.get('first_step', '')}"]
    L += ["", "Experiments:"]
    for e in a.get("experiments") or []:
        L += [f"- {e.get('question', '')}", (f"  Baseline: {e.get('baseline', '')} · Change: {e.get('change', '')} · "
                                             f"Measure: {e.get('measure', '')}")]
    L += ["", "Stack: " + ", ".join(a.get("stack") or [])]
    text = "\n".join(L)
    text = _LEAK.sub("", _CITE.sub("", text))
    return _LEAK_THE.sub(lambda m: "The evidence" if m.group(1)[0].isupper() else "the evidence", text)


def fact_sheet(kg: KG, *answers: dict) -> str:
    """Symmetric reference: one card per entity named in ANY of the answers (same sheet for both)."""
    names = list(dict.fromkeys(n for a in answers for n in _names(a or {}) + _mentions(kg, a or {})))
    L = []
    for n in names[:40]:
        m = kg.match(n, k=1, exact_first=True)
        if not (m and m[0][0] >= 0.9):
            L.append(f"- {n}: not in reference")
            continue
        eid = m[0][1]
        rel = [kg.edges[x] for x in kg.adj.get(eid, []) if kg.edges[x]["status"] != "unsupported"][:4]
        facts = "; ".join(f"{kg.name(e['head'])} {e['relation'].replace('_', ' ')} {kg.name(e['tail'])} ({e['status']})" for e in rel)
        L.append(f"- {n}: {kg.ents[eid]['type']}{'; ' + facts if facts else ''}")
    return "REFERENCE\n" + "\n".join(L)


def judge_scores(judge: str, r: dict, sheet: str) -> dict:
    out = LLM(judge).parse(RUBRIC.format(persona_desc=PERSONA_DESC[r["persona"]]),
                           f"Question:\n{r['question']}\n\n{sheet}\n\nAdvice:\n{_blind(r['answer'])}", Scores,
                           "guidance_judge", max_tokens=900, reasoning_max_tokens=0)
    return out.model_dump()


def judge_pair(judge: str, q: dict, a: dict, b: dict, sheet: str) -> dict:
    sys_ = RUBRIC.format(persona_desc=PERSONA_DESC[q["persona"]]) + "\nCompare two answers; which helps this person more?"
    out = LLM(judge).parse(sys_, f"Question:\n{q['question']}\n\n{sheet}\n\nAnswer A:\n{_blind(a['answer'])}\n\n"
                                 f"Answer B:\n{_blind(b['answer'])}", Pref, "guidance_pair", max_tokens=700, reasoning_max_tokens=0)
    return out.model_dump()


def pairwise(judges: list[str], q: dict, x: dict, y: dict, sheet: str) -> dict:
    """Both orders × every judge. Returns P(x preferred), position consistency, and the raw judgements
    (LLM-as-a-judge; an evaluation label set, nothing is trained on it)."""
    votes, consistent, raw = [], 0, []
    for j in judges:
        a1 = judge_pair(j, q, x, y, sheet)
        a2 = judge_pair(j, q, y, x, sheet)
        v1 = 1.0 if a1["winner"] == "A" else 0.5 if a1["winner"] == "tie" else 0.0
        v2 = 1.0 if a2["winner"] == "B" else 0.5 if a2["winner"] == "tie" else 0.0
        votes += [v1, v2]
        consistent += v1 == v2
        raw += [{"judge": j, "order": "xy", "x_pref": v1, "rationale": a1["rationale"]},
                {"judge": j, "order": "yx", "x_pref": v2, "rationale": a2["rationale"]}]
    return {"p_x": sum(votes) / len(votes), "position_consistent": consistent / len(judges), "raw": raw}


# ---- the experiment ----------------------------------------------------------------------------------------
DIMS = ("accuracy", "actionability", "insight", "experiment_design", "fit")


def experiment(models: list[str] | None = None, judges: list[str] | None = None, per_persona: int = 6,
               workers: int = 6) -> dict:
    from datetime import UTC, datetime
    models, judges = models or SMALL + LARGE, judges or JUDGES
    kg = KG()
    ts, rej = examine(per_persona)
    q = {t["id"]: t for t in ts}
    jobs = [(m, t, c) for m in models for t in ts for c in CONDITIONS]
    spend0 = LLM.spent_usd
    with ThreadPoolExecutor(workers) as pool:
        runs = list(pool.map(lambda j: run_agentic(j[0], j[1], kg) if j[2] == "kg_agentic" else run(j[0], j[1], j[2], kg), jobs))
    ok = [r for r in runs if r["answer"]]
    if len(ok) < 0.9 * len(runs):                          # infrastructure failures invalidate the comparison
        raise RuntimeError(f"invalid experiment: {len(runs) - len(ok)}/{len(runs)} runs failed")
    by = {(r["model"], r["task_id"], r["condition"]): r for r in ok}
    # rubric scores: each answer judged with the fact sheet of its own task pair (same sheet for both conditions)
    sheets = {(m, t["id"]): fact_sheet(kg, *(by[(m, t["id"], c)]["answer"] for c in CONDITIONS if (m, t["id"], c) in by))
              for m in models for t in ts}
    with ThreadPoolExecutor(workers) as pool:
        scored = list(pool.map(lambda jr: (jr[0], jr[1], judge_scores(jr[0], jr[1], sheets[(jr[1]["model"], jr[1]["task_id"])])),
                               [(j, r) for j in judges for r in ok]))
    rubric = defaultdict(list)
    for j, r, sc in scored:
        rubric[(r["model"], r["task_id"], r["condition"])].append({"judge": j, **sc})
    # pairwise: same model grounded vs closed book, and small grounded vs large closed book
    pairs = [(f"{m.split('/')[-1]}: {a} vs {b}", t["id"], (m, t["id"], a), (m, t["id"], b)) for m in models for t in ts
             for a, b in (("kg_tools", "closed_book"), ("kg_agentic", "closed_book"), ("kg_agentic", "kg_tools"))]
    pairs += [(f"{sm.split('/')[-1]} agentic vs {lg.split('/')[-1]} closed", t["id"], (sm, t["id"], "kg_agentic"), (lg, t["id"], "closed_book"))
              for sm in SMALL if sm in models for lg in LARGE if lg in models for t in ts]
    pairs = [p_ for p_ in pairs if p_[2] in by and p_[3] in by]
    with ThreadPoolExecutor(workers) as pool:
        prefs = list(pool.map(lambda p_: {"comparison": p_[0], "task_id": p_[1], "x": p_[2], "y": p_[3],
                                         **pairwise(judges, q[p_[1]], by[p_[2]], by[p_[3]],
                                                    fact_sheet(kg, by[p_[2]]["answer"], by[p_[3]]["answer"]))}, pairs))
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    res = {"ts": stamp, "kb_version": kg.kb_version, "models": models, "judges": judges, "tasks": ts, "rejected_tasks": rej,
           "runs": runs,
           "rubric": {"|".join(k): v for k, v in rubric.items()}, "pairwise": prefs,
           "spend_usd": round(LLM.spent_usd - spend0, 4)}
    (config.EVAL / "results").mkdir(parents=True, exist_ok=True)
    (config.EVAL / "results" / f"guidance_{stamp}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    (config.ROOT / "reports" / f"{stamp}-guidance.md").write_text(report(res))
    (config.EVAL / "gold" / f"guidance_review_{stamp}.md").write_text(review_sheet(res))
    (config.EVAL / "gold" / f"judgments_guidance_{stamp}.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in preferences(res)))
    return res


def preferences(res: dict) -> list[dict]:
    """LLM-as-a-judge pairwise judgements as records: prompt, preferred, other, margin and the judges' rationales
    (only pairs with a clear, position-consistent majority)."""
    runs = {(r["model"], r["task_id"], r["condition"]): r for r in res["runs"] if r["answer"]}
    q = {t["id"]: t for t in res["tasks"]}
    out = []
    for p_ in res["pairwise"]:
        x, y = runs[tuple(p_["x"])], runs[tuple(p_["y"])]
        if abs(p_["p_x"] - 0.5) < 0.25 or p_["position_consistent"] < 0.5:
            continue
        chosen, rejected = (x, y) if p_["p_x"] > 0.5 else (y, x)
        out.append({"prompt": q[p_["task_id"]]["question"], "persona": q[p_["task_id"]]["persona"],
                    "preferred": chosen["answer"], "other": rejected["answer"],
                    "preferred_meta": {"model": chosen["model"], "condition": chosen["condition"]},
                    "other_meta": {"model": rejected["model"], "condition": rejected["condition"]},
                    "margin": round(abs(p_["p_x"] - 0.5) * 2, 3), "judges": res["judges"],
                    "rationales": [r["rationale"] for r in p_["raw"]], "kb_version": res["kb_version"]})
    return out


def _kappa(a: list[int], b: list[int]) -> float | None:
    if not a:
        return None
    cats = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b, strict=True)) / len(a)
    pe = sum((a.count(c) / len(a)) * (b.count(c) / len(b)) for c in cats)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else None


def _fmt(b) -> str:
    return f"{b[0]:.2f} [{b[1]:.2f}–{b[2]:.2f}]"


def report(res: dict) -> str:
    rub = {tuple(k.split("|")): v for k, v in res["rubric"].items()}
    runs = {(r["model"], r["task_id"], r["condition"]): r for r in res["runs"] if r["answer"]}
    strata = {t["id"]: t["stratum"] for t in res["tasks"]}
    L = [(f"# Guidance eval · KB `{res['kb_version']}` · {len(res['tasks'])} tasks · judges: "
         f"{', '.join(j.split('/')[-1] for j in res['judges'])} · ${res['spend_usd']}"), "",
         ("Rubric 1-5 (mean over judges; overall = mean of dimensions, 95% task-bootstrap interval). KB metrics are "
         "deterministic. Salient coverage = share of the Examiner's reference entities the answer surfaced."), "",
         "| Model | Mode | " + " | ".join(DIMS) + " | overall | KB-grounded | salient coverage | complete experiments | chars |",
         "|---|---|" + "---|" * (len(DIMS) + 5)]
    for m in res["models"]:
        for c in CONDITIONS:
            keys = [k for k in rub if k[0] == m and k[2] == c]
            if not keys:
                continue
            per = {d: [sum(x[d] for x in rub[k]) / len(rub[k]) for k in keys] for d in DIMS}
            overall = [sum(per[d][i] for d in DIMS) / len(DIMS) for i in range(len(keys))]
            mets = [runs[k]["metrics"] for k in keys if k in runs]
            avg = {f: sum((x.get(f) or 0) for x in mets) / len(mets) for f in ("kb_grounded_share", "salient_coverage", "experiments_complete", "chars")}
            L.append(f"| {m.split('/')[-1]} | {c} | " + " | ".join(f"{sum(per[d]) / len(per[d]):.2f}" for d in DIMS)
                     + f" | {_fmt(bootstrap(overall))} | {avg['kb_grounded_share']:.2f} | {avg['salient_coverage']:.2f} | "
                       f"{avg['experiments_complete']:.1f} | {avg['chars']:.0f} |")
    L += ["", "## Pairwise preference", "",
          "Both orders × both judges per task; 0.5 = no preference. Length-matched = tasks where the two answers differ by ≤ 25% in length.", "",
          "| Comparison | n | P(first preferred) | rich tasks | thin tasks | length-matched | position-consistent |", "|---|---|---|---|---|---|---|"]
    grp = defaultdict(list)
    for p_ in res["pairwise"]:
        grp[p_["comparison"]].append(p_)
    for name, ps in grp.items():
        lab = name
        pr = [x["p_x"] for x in ps if strata[x["task_id"]] == "rich"]
        th = [x["p_x"] for x in ps if strata[x["task_id"]] == "thin"]
        lm = [x["p_x"] for x in ps if runs.get(tuple(x["x"])) and runs.get(tuple(x["y"])) and
              abs(runs[tuple(x["x"])]["metrics"]["chars"] - runs[tuple(x["y"])]["metrics"]["chars"])
              <= 0.25 * max(runs[tuple(x["x"])]["metrics"]["chars"], runs[tuple(x["y"])]["metrics"]["chars"])]
        cons = sum(x["position_consistent"] for x in ps) / len(ps)
        mean = lambda xs: f"{sum(xs) / len(xs):.2f} (n={len(xs)})" if xs else "–"
        L.append(f"| {lab} | {len(ps)} | {_fmt(bootstrap([x['p_x'] for x in ps]))} | {mean(pr)} | {mean(th)} | {mean(lm)} | {cons:.0%} |")
    if len(res["judges"]) == 2:
        j1, j2 = res["judges"]
        va = [round(r["x_pref"] * 2) for p_ in res["pairwise"] for r in p_["raw"] if r["judge"] == j1]
        vb = [round(r["x_pref"] * 2) for p_ in res["pairwise"] for r in p_["raw"] if r["judge"] == j2]
        L += ["", f"Inter-judge agreement on pairwise votes: Cohen's κ = {_kappa(va, vb)} over {len(va)} judgements."]
    return "\n".join(L) + "\n"


def review_sheet(res: dict, n: int = 10, seed: int = 4) -> str:
    """Blind pairs for the owner (grounded vs closed book, same model), order randomised; key at the end."""
    rnd = random.Random(seed)
    runs = {(r["model"], r["task_id"], r["condition"]): r for r in res["runs"] if r["answer"]}
    cands = [(m, t["id"]) for m in res["models"] for t in res["tasks"]
             if (m, t["id"], "kg_tools") in runs and (m, t["id"], "closed_book") in runs]
    rnd.shuffle(cands)
    L, key = ["# Guidance review (blind)", "", "For each question: which answer would help this person more? Write A, B or =.", ""], []
    for i, (m, tid) in enumerate(cands[:n]):
        pair = [runs[(m, tid, "kg_tools")], runs[(m, tid, "closed_book")]]
        rnd.shuffle(pair)
        key.append(f"{i + 1}. A = {pair[0]['condition']}, B = {pair[1]['condition']} ({m.split('/')[-1]})")
        L += [f"## {i + 1}. {pair[0]['question']}", ""]
        for tag, r in zip("AB", pair, strict=True):
            L += [f"### {tag}", "", "```", _blind(r["answer"])[:3000], "```", ""]
        L += ["Better: __", ""]
    return "\n".join(L + ["---", "## Key", ""] + key) + "\n"
