"""Persona discovery tasks: can an agent with the KB surface things worth knowing, not just answer QA?

Five personas, each a different kind of discovery. The agent must state what it found as TYPED CLAIMS
(gap · status · pattern · step · fact) with entity names and numbers, so each claim can be recomputed
on the graph. Closed-book answers get the same checks by name, so the comparison is fair.

Metrics per answer:
  claim precision      share of checkable claims that hold on the KB
  groundedness         share of claims whose cited edges exist and touch the named entities
  discovery rate       entities named by the KB agent that the same model did not name closed-book
Owner review: a blind side-by-side sheet (A/B order randomised) for usefulness and novelty.

Caveat: "holds on the KB" is not "true in the world": KB truth is measured separately (silver).
"""

from __future__ import annotations

import json
import random
import time
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cf import config, trace
from cf.agent.kg import KG, ST, TOOL_SPECS
from cf.bench.sessions import SUPPORTED, _edges, _ok
from cf.llm.client import LLM, strict_schema


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Claim(_Strict):
    kind: Literal["fact", "gap", "status", "pattern", "step"]
    text: str
    entities: list[str]          # names; fact: [head, tail] · gap/pattern: [subject] · status: [head, tail] · step: [first, then]
    relation: str                # KB relation the claim is about (e.g. works_on, serves, uses_method, offers)
    number: int                  # gap: claimed max providers · pattern: claimed min orgs · else 0
    status: str                  # status claims: verified | corroborated | confirmed | claimed · else ""
    edge_ids: list[str]


class Brief(_Strict):
    summary: str
    claims: list[Claim]


SCHEMA = strict_schema(Brief)

CLAIM_RULES = """State what you found as claims. Each claim has a kind:
- fact: one relation between two entities, e.g. entities=[Harvey, contract review], relation=works_on
- gap: a subject with few providers, e.g. entities=[contract review], relation=works_on, number=2 means "at most 2 organisations work on it"
- status: how well a relation is evidenced, e.g. entities=[Harvey, Allen & Overy], relation=serves, status=claimed
- pattern: something many organisations share, e.g. entities=[fine-tuning], relation=offers, number=3 means "at least 3 organisations offer it"
- step: a learning order, e.g. entities=[fine-tuning, LoRA] means "learn fine-tuning before LoRA"
Use exact entity names. number=0 and status="" when not used. Cite edge ids when you have them."""

PERSONAS = {
    "student": "I'm a student who wants to work on {a}. What should I learn first and in what order, which organisations "
               "use it, and which roles are they hiring for?",
    "professional": "I work alongside the companies in '{a}'. What patterns recur across them: what they offer, whom they "
                    "serve, which methods they use? Give the patterns with how many companies share each.",
    "vc": "I'm evaluating startups working on {a}. Who are they, which of their customer or partner claims are confirmed by "
          "the other party versus only self-claimed, and is the space crowded or empty?",
    "founder": "I want to build something in {a}. Where is the opening: what's missing or under-served, who is closest, "
               "which methods and benchmarks apply, and what would be a first experiment?",
    "engineer": "I need to choose a stack around {a}. Which organisations offer it, which models do they serve, and which "
                "benchmarks do those models report?",
}


# ---- anchors from the graph (each persona needs enough structure to discover something) ---------------
def anchors(kg: KG, persona: str, n: int, rnd: random.Random) -> list[str]:
    if persona == "student":
        users = defaultdict(set)
        for e in _edges(kg, {"uses_method"}, "org", "method"):
            users[e["tail"]].add(e["head"])
        fam = {h["parent"] for h in kg.g.get("hierarchy", []) if h["kind"] == "subtype_of"} | \
              {h["child"] for h in kg.g.get("hierarchy", []) if h["kind"] == "subtype_of"}
        pool = [m for m, us in users.items() if len(us) >= 3 and m in fam and _ok(kg, m)]
    elif persona == "professional":
        pool = [f"seg:{c['id']}" for c in kg.comms.values() if c.get("named_by") and c["size"] >= 40]
    elif persona in ("vc", "founder"):
        works = defaultdict(set)
        for e in _edges(kg, {"works_on"}, "org", "problem"):
            works[e["tail"]].add(e["head"])
        pool = [p for p, os_ in works.items() if 2 <= len(os_) <= 12 and _ok(kg, p)]
    else:                                                    # engineer: offered technologies/methods
        off = defaultdict(set)
        for e in _edges(kg, {"offers"}, "org"):
            if kg.ents[e["tail"]]["type"] in ("technology", "method"):
                off[e["tail"]].add(e["head"])
        pool = [t for t, os_ in off.items() if len(os_) >= 3 and _ok(kg, t)]
    rnd.shuffle(pool)
    return pool[:n]


def label(kg: KG, a: str) -> str:
    return kg.comms[int(a[4:])]["name"] if a.startswith("seg:") else kg.name(a)


def build(per_persona: int = 3, seed: int = 5) -> list[dict]:
    kg = KG()
    rnd = random.Random(seed)
    tasks = []
    for p, tmpl in PERSONAS.items():
        for a in anchors(kg, p, per_persona, rnd):
            tasks.append({"id": f"D-{p}-{len(tasks):02d}", "persona": p, "anchor": a, "kb_version": kg.kb_version,
                          "question": tmpl.format(a=label(kg, a))})
    return tasks


# ---- checking claims on the KB ------------------------------------------------------------------------
def _res(kg: KG, name: str) -> str | None:
    m = kg.match(name or "", k=1, exact_first=True)
    return m[0][1] if m and m[0][0] >= 0.75 else None


def _between(kg: KG, a: str, b: str, rel: str | None) -> list[dict]:
    return [kg.edges[x] for x in kg.adj.get(a, []) if {kg.edges[x]["head"], kg.edges[x]["tail"]} == {a, b}
            and kg.edges[x]["status"] in SUPPORTED and (not rel or kg.edges[x]["relation"] == rel)]


def check(kg: KG, c: dict) -> dict:
    """→ {checkable, holds, grounded, why}. 'holds' is recomputed on the graph, never taken from the agent."""
    ids = [_res(kg, n) for n in c["entities"]]
    rel = c.get("relation") or None
    if rel and rel not in {x["relation"] for x in kg.edges.values()}:
        rel = None                                           # unknown relation name: check without it
    cites = [str(x).strip("[] ").removeprefix("edge_id:").strip() for x in c.get("edge_ids") or []]
    valid = [x for x in cites if x in kg.edges]
    named = {i for i in ids if i}
    grounded = bool(valid) and all({kg.edges[x]["head"], kg.edges[x]["tail"]} & named for x in valid)
    out = {"checkable": True, "holds": False, "grounded": grounded, "resolved": [kg.name(i) if i else None for i in ids]}
    k = c["kind"]
    if k in ("fact", "status"):
        if len(ids) < 2 or not ids[0] or not ids[1]:
            return {**out, "checkable": False, "why": "entities not found in KB"}
        es = _between(kg, ids[0], ids[1], rel)
        if k == "fact":
            return {**out, "holds": bool(es), "why": f"{len(es)} supporting edge(s)"}
        want = (c.get("status") or "").lower()
        st = max((e["status"] for e in es), key=ST.index, default=None)
        return {**out, "holds": st is not None and want in (st, "self-claimed" if st == "claimed" else st),
                "why": f"KB status {st}"}
    if k in ("gap", "pattern"):
        if not ids or not ids[0] or not rel:
            return {**out, "checkable": False, "why": "subject or relation missing"}
        orgs = {e["head"] if e["tail"] == ids[0] else e["tail"] for e in (kg.edges[x] for x in kg.adj.get(ids[0], []))
                if e["relation"] == rel and e["status"] in SUPPORTED}
        n = len(orgs)
        holds = n <= c["number"] if k == "gap" else (c["number"] >= 2 and n >= c["number"])
        return {**out, "holds": holds, "why": f"{n} entities on '{rel}' (claimed {'≤' if k == 'gap' else '≥'} {c['number']})"}
    if k == "step":
        if len(ids) < 2 or not ids[0] or not ids[1]:
            return {**out, "checkable": False, "why": "entities not found in KB"}
        a, b = ids
        parent = any(h["child"] == b and h["parent"] == a for h in kg.g.get("hierarchy", []))
        wrong = any(h["child"] == a and h["parent"] == b for h in kg.g.get("hierarchy", []))
        if not parent and not wrong:
            return {**out, "checkable": False, "why": "no hierarchy between them"}
        return {**out, "holds": parent, "why": "parent before child" if parent else "child before parent"}
    return {**out, "checkable": False, "why": "unknown kind"}


def score(kg: KG, brief: dict) -> dict:
    claims = brief.get("claims") or []
    checks = [check(kg, c) for c in claims]
    chk = [x for x in checks if x["checkable"]]
    ents = {n for c in claims for n in (_res(kg, e) for e in c["entities"]) if n}
    return {"claims": len(claims), "checkable": len(chk), "holds": sum(x["holds"] for x in chk),
            "claim_precision": round(sum(x["holds"] for x in chk) / len(chk), 3) if chk else None,
            "grounded": round(sum(x["grounded"] for x in checks) / len(checks), 3) if checks else None,
            "kb_entities": sorted(ents), "by_kind": dict(sorted({c["kind"]: 0 for c in claims}.items())), "checks": checks}


# ---- running a brief ----------------------------------------------------------------------------------
SYSTEM_TOOLS = ("You are an analyst of the frontier-AI ecosystem with tools over a knowledge graph. Explore it: find the "
                "relevant entities, follow their relations, compare. Look for what is non-obvious: gaps, rare methods, "
                "claims that are only self-reported, patterns shared by many companies. Then answer in prose, citing edge "
                "ids. You will then be asked for your findings as structured claims.")
SYSTEM_CLOSED = ("You are an analyst of the frontier-AI ecosystem. Answer from your own knowledge; say when you are unsure. "
                 "Look for what is non-obvious: gaps, rare methods, self-reported claims, recurring patterns.")


def run(model: str, task: dict, condition: str, kg: KG, reasoning="auto", max_steps: int = 12) -> dict:
    llm = LLM(model)
    t0, spend0 = time.time(), LLM.spent_usd
    tools = TOOL_SPECS if condition == "kg_tools" else None
    msgs = [{"role": "system", "content": SYSTEM_TOOLS if tools else SYSTEM_CLOSED}, {"role": "user", "content": task["question"]}]
    steps, prose, err = [], "", None
    for step in range(max_steps):
        last = step == max_steps - 1
        if last and tools:
            msgs.append({"role": "user", "content": "Step budget reached: answer now."})
        try:
            m, _ = llm.chat(msgs, tools=None if last else tools, name=f"discovery_{condition}", max_tokens=3000,
                            reasoning_max_tokens=reasoning)
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
                steps.append({"step": step, "tool": fn, "args": tc["function"].get("arguments")})
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res)[:6000]})
            continue
        prose = m.get("content") or ""
        break
    brief = {"summary": prose, "claims": []}
    if not err:
        msgs.append({"role": "assistant", "content": prose})
        msgs.append({"role": "user", "content": CLAIM_RULES + "\nNow list your findings as claims (6-12)."})
        try:
            m2, _ = llm.chat(msgs, name=f"discovery_{condition}_claims", max_tokens=3000, reasoning_max_tokens=reasoning,
                             schema=SCHEMA)
            brief = {**json.loads(m2.get("content") or "{}"), "prose": prose}
        except (RuntimeError, ValueError) as e:
            err = f"claims: {str(e)[:160]}"
    out = {"task_id": task["id"], "persona": task["persona"], "question": task["question"], "model": model, "condition": condition,
           "kb_version": kg.kb_version, "run_id": trace.RUN_ID, "brief": brief, "steps": steps, "error": err,
           "score": score(kg, brief), "cost_usd": round(LLM.spent_usd - spend0, 5), "latency_s": round(time.time() - t0, 1)}
    trace.event("agent", {"discovery": task["id"], "model": model, "condition": condition, "score": {
        k: v for k, v in out["score"].items() if k != "checks"}})
    return out


def bench(models: list[str], tasks: list[dict], workers: int = 6) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor
    kg = KG()
    jobs = [(m, t, c) for m in models for t in tasks for c in ("closed_book", "kg_tools")]
    with ThreadPoolExecutor(workers) as pool:
        res = list(pool.map(lambda j: run(j[0], j[1], j[2], kg), jobs))
    # discovery rate: KB-agent entities the same model did not name closed-book
    closed = {(r["model"], r["task_id"]): set(r["score"]["kb_entities"]) for r in res if r["condition"] == "closed_book"}
    for r in res:
        if r["condition"] == "kg_tools":
            mine = set(r["score"]["kb_entities"])
            new = mine - closed.get((r["model"], r["task_id"]), set())
            r["score"]["discovered"] = len(new)
            r["score"]["discovery_rate"] = round(len(new) / len(mine), 3) if mine else None
    return res


def report(res: list[dict]) -> str:
    rows = defaultdict(list)
    for r in res:
        rows[(r["persona"], r["model"].split("/")[-1], r["condition"])].append(r["score"])

    def avg(xs):
        xs = [x for x in xs if x is not None]
        return f"{sum(xs) / len(xs):.2f}" if xs else "–"
    L = ["| Persona | Model | Mode | Tasks | Claims | Checkable | Claim precision | Grounded | Discovered (new vs closed book) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for (p, m, c), ss in sorted(rows.items()):
        L.append(f"| {p} | {m} | {c} | {len(ss)} | {avg([s['claims'] for s in ss])} | {avg([s['checkable'] for s in ss])} | "
                 f"{avg([s['claim_precision'] for s in ss])} | {avg([s['grounded'] for s in ss])} | "
                 f"{avg([s.get('discovered') for s in ss]) if c == 'kg_tools' else ''} |")
    return "\n".join(L) + "\n"


def review_sheet(res: list[dict], seed: int = 3) -> str:
    """Blind A/B sheet for the owner: same task, KB agent vs closed book, order randomised."""
    rnd = random.Random(seed)
    by = defaultdict(dict)
    for r in res:
        by[(r["task_id"], r["model"])][r["condition"]] = r
    L = ["# Discovery review (blind)", "", ("For each task: which answer is more useful and more novel to you? "
         "Write A, B or = after each line. The key is at the bottom."), ""]
    key = []
    for i, ((tid, m), d) in enumerate(sorted(by.items())):
        if len(d) < 2:
            continue
        pair = [d["kg_tools"], d["closed_book"]]
        rnd.shuffle(pair)
        key.append(f"{i + 1}. A = {pair[0]['condition']}, B = {pair[1]['condition']} ({m.split('/')[-1]})")
        L += [f"## {i + 1}. {tid} · {pair[0]['persona']}", "", f"> {pair[0]['question']}", ""]
        for tag, r in zip("AB", pair, strict=True):
            b = r["brief"]
            L += [f"### {tag}", "", (b.get("summary") or b.get("prose") or "")[:1800], ""]
            L += [f"- [{c['kind']}] {c['text']}" for c in (b.get("claims") or [])[:12]] + [""]
        L += ["More useful: __   More novel: __", ""]
    return "\n".join(L + ["---", "## Key", ""] + key) + "\n"


def save(res: list[dict], tasks: list[dict], tag: str) -> dict:
    from datetime import UTC, datetime
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    (config.EVAL / "gold").mkdir(parents=True, exist_ok=True)
    (config.EVAL / "gold" / f"discovery_tasks_{tag}.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (config.EVAL / "results").mkdir(parents=True, exist_ok=True)
    out = config.EVAL / "results" / f"discovery_{tag}_{stamp}.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in res))
    rep = config.ROOT / "reports" / f"{stamp}-discovery-{tag}.md"
    rep.write_text(f"# Persona discovery `{tag}` · KB `{res[0]['kb_version']}`\n\n" + report(res))
    sheet = config.EVAL / "gold" / f"discovery_review_{tag}.md"
    sheet.write_text(review_sheet(res))
    return {"results": str(out), "report": str(rep), "review_sheet": str(sheet)}
