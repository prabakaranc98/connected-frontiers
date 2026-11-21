"""Multi-turn session tasks: built by graph algorithms, written by an LLM, checked deterministically,
and accepted only if a solver model can answer them given the gold evidence.

Each turn carries its own answer key, computed on the KB (never written by an LLM):
  key = {"kind": "set" | "labels" | "single", "ids": [...], "labels": {id: status}, "allow_empty": bool}
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict

from pydantic import BaseModel, ConfigDict

from cf import config
from cf.agent.kg import KG
from cf.crawl.noise import is_generic
from cf.llm.client import LLM

SUPPORTED = {"claimed", "confirmed", "corroborated", "verified"}


def _edges(kg: KG, rel: set[str] | None = None, head_type: str | None = None, tail_type: str | None = None):
    for e in kg.g["edges"]:
        if e["status"] not in SUPPORTED or (rel and e["relation"] not in rel):
            continue
        if head_type and kg.ents[e["head"]]["type"] != head_type or tail_type and kg.ents[e["tail"]]["type"] != tail_type:
            continue
        yield e


VAGUE = re.compile(r"^(agi|asi|ai|ml|llms?|ai (model )?training|ai adoption|ai safety|safety|scaling|inference|"
                   r"productivity|automation|innovation|efficiency|cost|reasoning|intelligence)$", re.IGNORECASE)


def _ok(kg: KG, eid: str) -> bool:
    return eid in kg.ents and not is_generic(kg.name(eid)) and not VAGUE.match(kg.name(eid).strip())


# ---- spec generators (graph algorithms → turns with computed keys) -----------------------------
def spec_opportunity(kg: KG, rnd: random.Random) -> dict | None:
    """problem → who works on it → their methods → benchmarks for it → under-explored methods."""
    works = defaultdict(set)
    for e in _edges(kg, {"works_on"}, "org", "problem"):
        works[e["tail"]].add(e["head"])
    probs = [p for p, orgs in works.items() if len(orgs) >= 2 and _ok(kg, p)]
    rnd.shuffle(probs)
    for p in probs:
        spec = _opportunity(kg, p, works)
        if spec:
            return spec
    return None


def _opportunity(kg: KG, p: str, works) -> dict | None:
    orgs = sorted(o for o in works[p] if _ok(kg, o))
    rels = {"uses_method", "uses_tech"}
    global_users = defaultdict(set)
    for e in _edges(kg, rels, "org"):
        global_users[e["tail"]].add(e["head"])
    used, gold = {}, [e["id"] for e in _edges(kg, {"works_on"}) if e["tail"] == p and e["head"] in orgs]
    for e in _edges(kg, rels, "org"):
        if e["head"] in orgs and _ok(kg, e["tail"]):
            used[e["tail"]] = e
            gold.append(e["id"])
    bench = sorted({e["tail"] for e in _edges(kg, {"measured_on"}) if e["head"] in orgs and _ok(kg, e["tail"])})
    rare = sorted(m for m in used if len(global_users[m]) == 1)
    if len(orgs) < 2 or len(used) < 3 or len(used) > 15 or not rare or len(rare) == len(used) or len(bench) > 10:
        return None
    return {"template": "opportunity", "anchors": [p], "turns": [
        {"intent": f"Ask which organisations work on the problem '{kg.name(p)}'.", "key": {"kind": "set", "ids": orgs}},
        {"intent": "Ask which methods or technologies those organisations (from the previous answer) use.",
         "key": {"kind": "set", "ids": sorted(used)}},
        {"intent": "Ask which benchmarks those organisations report results on; it is fine if there are none.",
         "key": {"kind": "set", "ids": bench, "allow_empty": True}},
        {"intent": "Ask which of those methods or technologies no other organisation in the whole ecosystem uses, "
                   "as possibly under-explored approaches to build on.", "key": {"kind": "set", "ids": rare}},
    ], "gold_edge_ids": gold}


def spec_landscape(kg: KG, rnd: random.Random) -> dict | None:
    """segment → players → which use method M → how well supported each claim is → recommend one."""
    segs = [c for c in kg.comms.values() if c["size"] >= 15 and c.get("name")]
    rnd.shuffle(segs)
    for c in segs:
        members = [e for e in kg.ents.values() if e.get("community") == c["id"] and e["type"] == "org" and _ok(kg, e["id"])]
        players = [e["id"] for e in sorted(members, key=lambda e: -(e.get("pagerank") or 0))[:8]]
        if len(players) < 5:
            continue
        by_m = defaultdict(list)
        for e in _edges(kg, {"uses_method", "offers"}, "org"):
            if e["head"] in players and kg.ents[e["tail"]]["type"] in ("method", "technology") and _ok(kg, e["tail"]):
                by_m[e["tail"]].append(e)
        ms = [m for m, es in by_m.items() if len({x["head"] for x in es}) >= 2]
        if not ms:
            continue
        m = rnd.choice(ms)
        es = by_m[m]
        best = max(es, key=lambda x: x["strength"])
        return {"template": "landscape", "anchors": [m], "segment": c["name"], "turns": [
            {"intent": f"Ask for the main organisations in the part of the AI ecosystem described as '{c['name']}'.",
             "key": {"kind": "set", "ids": players}},
            {"intent": f"Ask which of them use or offer '{kg.name(m)}'.", "key": {"kind": "set", "ids": sorted({x['head'] for x in es})}},
            {"intent": "Ask, for each of those, whether that claim is verified, corroborated, confirmed by another party, "
                       "or only self-claimed.", "key": {"kind": "labels", "labels": {x["head"]: x["status"] for x in es}}},
            {"intent": f"Ask which single one they would recommend for '{kg.name(m)}', based on how well supported the evidence is.",
             "key": {"kind": "single", "ids": sorted({x['head'] for x in es if x['strength'] == best['strength']})}},
        ], "gold_edge_ids": [x["id"] for x in es] + [e["id"] for e in kg.g["edges"] if e["head"] in players][:40]}
    return None


def spec_learn(kg: KG, rnd: random.Random) -> dict | None:
    """method → what it is a kind of / its variants → who uses it → papers/posts about it."""
    users = defaultdict(set)
    for e in _edges(kg, {"uses_method"}, None, "method"):
        users[e["tail"]].add(e["head"])
    family = defaultdict(set)
    for h in kg.g.get("hierarchy", []):
        if h["kind"] == "subtype_of":
            family[h["child"]].add(h["parent"])
            family[h["parent"]].add(h["child"])
    ms = [m for m, us in users.items() if len(us) >= 2 and any(_ok(kg, x) for x in family.get(m, ())) and _ok(kg, m)]
    if not ms:
        return None
    m = rnd.choice(ms)
    orgs = sorted(u for u in users[m] if kg.ents[u]["type"] == "org")
    models = sorted(u for u in users[m] if kg.ents[u]["type"] == "model")
    if len(orgs) < 2:
        return None
    return {"template": "learn", "anchors": [m], "turns": [
        {"intent": f"As a learner, ask what '{kg.name(m)}' is related to: broader methods it is a kind of, or variants of it.",
         "key": {"kind": "set", "ids": sorted(x for x in family[m] if _ok(kg, x))}},
        {"intent": "Ask which organisations use it in practice.", "key": {"kind": "set", "ids": orgs}},
        {"intent": "Ask which specific models are reported to use it; it is fine if there are none.",
         "key": {"kind": "set", "ids": models, "allow_empty": True}},
    ], "gold_edge_ids": [e["id"] for e in _edges(kg, {"uses_method"}) if e["tail"] == m]}


def spec_lineage(kg: KG, rnd: random.Random) -> dict | None:
    """model → its base and derivation → who offers the base → siblings on the same base (HF-verified)."""
    base_of = defaultdict(list)
    for e in _edges(kg, {"builds_on"}, "model", "model"):
        base_of[e["head"]].append(e)
    n_on = Counter(z["tail"] for es in base_of.values() for z in es)
    cands = [mid for mid, es in base_of.items() if es]
    rnd.shuffle(cands)
    cands.sort(key=lambda m: -min(n_on[base_of[m][0]["tail"]], 3))
    for x in cands:
        e = base_of[x][0]
        base = e["tail"]
        offer = sorted(o["head"] for o in _edges(kg, {"offers"}) if o["tail"] == base)
        sib = sorted(h for h, es in base_of.items() if h != x and any(z["tail"] == base for z in es))
        if not offer:
            continue
        return {"template": "lineage", "anchors": [x], "turns": [
            {"intent": f"Ask what model '{kg.name(x)}' is built on.", "key": {"kind": "set", "ids": [base]}},
            {"intent": "Ask how it was derived from that base (for example fine-tuned, quantized, merged).",
             "key": {"kind": "labels", "labels": {base: (e.get("attrs") or {}).get("derivation", "unknown")}}},
            {"intent": "Ask which organisation offers that base model.", "key": {"kind": "set", "ids": offer}},
            {"intent": "Ask which other models are built on the same base; it is fine if there are none.",
             "key": {"kind": "set", "ids": sib[:30], "allow_empty": True}},
        ], "gold_edge_ids": [e["id"]] + [o["id"] for o in _edges(kg, {"offers"}) if o["tail"] == base]}
    return None


GENERATORS = {"opportunity": spec_opportunity, "landscape": spec_landscape, "learn": spec_learn, "lineage": spec_lineage}


# ---- writer (LLM): intents → natural multi-turn user messages, no answers inside --------------
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Written(_Strict):
    persona: str
    turns: list[str]


WRITER = """You write realistic multi-turn questions a person would ask an analyst about the AI ecosystem.
You get a persona hint and one intent per turn. Write one user message per intent, in order.
Rules: natural and specific; turns after the first must refer back to the previous answer ("those", "of them", "it")
instead of repeating names; never include an answer or a hint of one; keep each turn under 40 words.
Return the persona you used (one short phrase) and the turns."""

PERSONAS = {"opportunity": "a founder looking for what to build", "landscape": "a CTO choosing a vendor",
            "learn": "an engineer learning the field", "lineage": "a researcher tracing model lineage"}


def write(spec: dict, model: str) -> dict:
    intents = "\n".join(f"{i + 1}. {t['intent']}" for i, t in enumerate(spec["turns"]))
    out = LLM(model).parse(WRITER, f"Persona hint: {PERSONAS[spec['template']]}\nIntents:\n{intents}", Written,
                           "task_write", max_tokens=1500)
    return {**spec, "persona": out.persona, "messages": out.turns}


# ---- deterministic checks -----------------------------------------------------------------------------
def check(kg: KG, s: dict) -> list[str]:
    problems = []
    if len(s.get("messages", [])) != len(s["turns"]):
        problems.append("turn count mismatch")
    anchor_names = {kg.name(a).lower() for a in s["anchors"]}
    for i, t in enumerate(s["turns"]):
        k = t["key"]
        ids = k.get("ids") or list(k.get("labels", {}))
        if not ids and not k.get("allow_empty"):
            problems.append(f"turn {i + 1}: empty key")
        missing = [x for x in ids if x not in kg.ents]
        if missing:
            problems.append(f"turn {i + 1}: ids not in KB {missing[:3]}")
        msg = (s.get("messages") or [""] * len(s["turns"]))[i].lower()
        leaked = [kg.name(x) for x in ids if x in kg.ents and len(kg.name(x)) > 3 and kg.name(x).lower() in msg
                  and kg.name(x).lower() not in anchor_names]
        if leaked:
            problems.append(f"turn {i + 1}: answer leaked in question {leaked[:3]}")
    if not s.get("gold_edge_ids"):
        problems.append("no gold evidence")
    return problems


SOLVER = "nvidia/nemotron-3.5-lightning"           # gate: a different family from the writer
GATE = 0.6


def build(n: int = 12, seed: int = 11, writer: str | None = None, solver: str = SOLVER,
          gate: float = GATE) -> tuple[list[dict], list[dict]]:
    """generate (graph algorithm) → write (Inkling) → check (deterministic) → solve (Nemotron, oracle):
    a session is accepted only if the solver, given the gold subgraph, scores ≥ gate on average."""
    from cf.llm.client import role_chain
    kg = KG()
    rnd = random.Random(seed)
    writer = writer or role_chain("extract")[0]           # Inkling-2-mini writes
    accepted, rejected = [], []
    names = list(GENERATORS)
    tries = 0
    while len(accepted) < n and tries < n * 4:
        tmpl = names[tries % len(names)]
        tries += 1
        spec = GENERATORS[tmpl](kg, rnd)
        if not spec:
            continue
        if any(s["anchors"] == spec["anchors"] and s["template"] == tmpl for s in accepted):
            continue
        try:
            s = write(spec, writer)
        except RuntimeError as e:
            rejected.append({**spec, "reasons": [f"writer failed: {str(e)[:80]}"]})
            continue
        problems = check(kg, s)
        if problems:
            rejected.append({**s, "reasons": problems})
            continue
        s = add_facts(kg, s)
        s["id"] = f"S-{tmpl}-{len(accepted) + len(rejected):03d}"
        s["kb_version"] = kg.kb_version
        s["writer"] = writer
        r = run_session(solver, s, "oracle", kg, reasoning=0)
        s["gate"] = {"solver": solver, "condition": "oracle", "turn_scores": r["turn_scores"],
                     "mean": r["mean_score"], "passed": r["mean_score"] >= gate, "cost_usd": r["cost_usd"]}
        (accepted if s["gate"]["passed"] else rejected).append(
            s if s["gate"]["passed"] else {**s, "reasons": [f"solver gate {r['mean_score']} < {gate}"]})
    return accepted, rejected


def save(sessions: list[dict], version: str) -> str:
    path = config.EVAL / "gold" / f"sessions_{version}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for s in sessions:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return str(path)


# ---- scoring a session ----------------------------------------------------------------------------------
STATUSES = ["verified", "corroborated", "confirmed", "claimed"]


def _status(label: str) -> str:
    x = label.lower()
    if "self" in x or "only claim" in x:
        return "claimed"
    return next((st for st in STATUSES if st in x or st[:-1] in x), x)


def _letters(x: str) -> str:
    return re.sub(r"[^a-z]", "", x.lower())


def score_turn(kg: KG, key: dict, items: list[dict]) -> float:
    def res(n):
        m = kg.match(n or "", k=1)
        return m[0][1] if m and m[0][0] >= 0.75 else None
    got = {r for r in (res(it.get("name")) for it in items if isinstance(it, dict)) if r}
    if key["kind"] == "labels":
        gold = key["labels"]
        pred = {res(it.get("name")): str(it.get("label") or "") for it in items if isinstance(it, dict)}
        if all(v in STATUSES for v in gold.values()):
            return round(sum(_status(pred.get(k, "")) == v for k, v in gold.items()) / len(gold), 3)
        anyl = " ".join(pred.values())                # derivation: label may sit on either model
        return round(sum(_letters(v)[:6] in _letters(pred.get(k, "") or anyl) for k, v in gold.items()) / len(gold), 3)
    gold = set(key.get("ids", []))
    if not gold:
        return 1.0 if not got else 0.0                     # correct abstention
    if key["kind"] == "single":
        return 1.0 if got & gold and len(got) <= 2 else 0.0
    tp = len(got & gold)
    p, r = tp / max(len(got), 1), tp / len(gold)
    return round(2 * p * r / (p + r), 3) if p + r else 0.0



# ---- oracle context: the gold subgraph plus the few computed facts the keys depend on -------------
def _edge_line(kg: KG, e: dict) -> str:
    d = (e.get("attrs") or {}).get("derivation")
    return (f"[{e['id']}] {kg.name(e['head'])} —{e['relation']}→ {kg.name(e['tail'])} "
            f"(status: {e['status']}, strength {e['strength']:.2f}{', derivation: ' + d if d else ''})")


def oracle_context(kg: KG, s: dict) -> str:
    lines = [_edge_line(kg, kg.edges[x]) for x in dict.fromkeys(s["gold_edge_ids"]) if x in kg.edges]
    return "\n".join(s.get("facts", []) + lines)


def add_facts(kg: KG, s: dict) -> dict:
    facts = []
    if s["template"] == "landscape":
        c = next(c for c in kg.comms.values() if c.get("name") == s["segment"])
        top = sorted((e for e in kg.ents.values() if e.get("community") == c["id"] and e["type"] == "org"),
                     key=lambda e: -(e.get("pagerank") or 0))[:15]
        facts.append(f"Segment '{c['name']}': organisations by PageRank (highest first): " + "; ".join(e["name"] for e in top))
    elif s["template"] == "opportunity":
        users = defaultdict(set)
        for e in _edges(kg, {"uses_method", "uses_tech"}, "org"):
            users[e["tail"]].add(e["head"])
        facts += [f"{kg.name(m)}: used by {len(users[m])} organisation(s) in the whole knowledge graph"
                  for m in s["turns"][1]["key"]["ids"]]
    elif s["template"] == "learn":
        m = s["anchors"][0]
        facts += [f"{kg.name(h['child'])} is a subtype of {kg.name(h['parent'])}" for h in kg.g.get("hierarchy", [])
                  if h["kind"] == "subtype_of" and m in (h["child"], h["parent"])]
    return {**s, "facts": facts}


# ---- multi-turn runner: one conversation, a JSON answer per turn, scored per turn --------------------
TURN_CONTRACT = """This is a multi-turn conversation. After each user message, reply with ONLY one JSON object:
{"answer": "<short prose; cite edge ids like [edge_id]>",
 "items": [{"name": "<entity name>", "label": "<label if the question asks for one, else empty>", "edge_ids": ["..."]}]}
List every entity that answers the question in items (empty list if the answer is none)."""


def run_session(model: str, s: dict, condition: str, kg: KG, reasoning=None, max_steps: int = 6) -> dict:
    import time

    from cf import trace
    from cf.agent import harness as H
    from cf.agent.kg import TOOL_SPECS
    llm = LLM(model)
    t0, spend0 = time.time(), LLM.spent_usd
    base = {"kg_tools": H.SYSTEM_TOOLS, "oracle": H.SYSTEM_ORACLE, "closed_book": H.SYSTEM_CLOSED}[condition]
    messages = [{"role": "system", "content": base.split("When you are done")[0] + TURN_CONTRACT}]
    tools = TOOL_SPECS if condition == "kg_tools" else None
    turns, calls = [], []
    for i, (msg_text, t) in enumerate(zip(s["messages"], s["turns"], strict=True)):
        content = msg_text
        if condition == "oracle" and i == 0:
            content = f"KNOWLEDGE GRAPH EXCERPT:\n{oracle_context(kg, s)}\n\n{msg_text}"
        messages.append({"role": "user", "content": content})
        final = None
        for step in range(max_steps):
            last = step == max_steps - 1
            if last and tools:
                messages.append({"role": "user", "content": "Step budget reached. Answer now with the JSON object."})
            try:
                m, _ = llm.chat(messages, tools=None if last else tools, name=f"session_{condition}",
                                max_tokens=2500, reasoning_max_tokens=reasoning)
            except RuntimeError as e:
                final = {"answer": "", "items": [], "error": str(e)[:200]}
                break
            tcs = m.get("tool_calls") or []
            if tcs and tools and not last:
                messages.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
                for tc in tcs:
                    fn = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                        result = getattr(kg, fn)(**args) if fn in {x["function"]["name"] for x in TOOL_SPECS} else {"error": "unknown tool"}
                    except (TypeError, ValueError, KeyError) as e:
                        result = {"error": f"bad arguments: {e}"}
                    calls.append({"turn": i, "step": step, "tool": fn, "args": tc["function"].get("arguments"),
                                  "touched": H._touched(result)})
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result)[:6000]})
                continue
            final = H._parse_final(m.get("content") or "")
            messages.append({"role": "assistant", "content": m.get("content") or ""})
            break
        final = final or {"answer": "", "items": [], "error": "no answer"}
        sc = score_turn(kg, t["key"], final.get("items") or [])
        turns.append({"turn": i, "score": sc, "items": final.get("items"), "answer": (final.get("answer") or "")[:1500],
                      "error": final.get("error") or ("parse_error" if final.get("parse_error") else None)})
        if final.get("error"):
            break
    scores = [t["score"] for t in turns] + [0.0] * (len(s["turns"]) - len(turns))
    out = {"session_id": s["id"], "template": s["template"], "model": model, "condition": condition,
           "kb_version": kg.kb_version, "run_id": trace.RUN_ID, "turns": turns, "steps": calls,
           "turn_scores": scores, "mean_score": round(sum(scores) / len(scores), 3),
           "all_turns_pass": all(x >= 0.5 for x in scores),
           "cost_usd": round(LLM.spent_usd - spend0, 5), "latency_s": round(time.time() - t0, 1)}
    trace.event("agent", {"session": s["id"], "model": model, "condition": condition, "summary": out["turn_scores"]})
    return out


def load(version: str) -> list[dict]:
    path = config.EVAL / "gold" / f"sessions_{version}.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()]


def bench(models: dict, conditions: list[str], version: str, workers: int = 6) -> tuple[list[dict], str]:
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime
    kg = KG()
    ss = load(version)
    if any(s["kb_version"] != kg.kb_version for s in ss):
        raise SystemExit(f"sessions are pinned to {ss[0]['kb_version']}, CURRENT is {kg.kb_version}: `cf kb use` first")
    jobs = [(m, r, c, s) for m, r in models.items() for c in conditions for s in ss]
    spend0 = LLM.spent_usd
    with ThreadPoolExecutor(workers) as pool:
        res = list(pool.map(lambda j: run_session(j[0], j[3], j[2], kg, reasoning=j[1]), jobs))
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = config.EVAL / "results" / f"sessions_{version}_{stamp}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in res))
    rows = defaultdict(list)
    for r in res:
        rows[(r["model"], r["condition"])].append(r)
    md = [f"# Multi-turn sessions `{version}` · KB `{kg.kb_version}` · {len(ss)} sessions · spend ${LLM.spent_usd - spend0:.3f}", "",
          "| model | condition | mean turn score | sessions all-turns-pass | turn 1 | turn 2 | turn 3 | turn 4 | tool calls | $ |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for (m, c), rs in sorted(rows.items(), key=lambda kv: -sum(r["mean_score"] for r in kv[1])):
        by_t = [[r["turn_scores"][i] for r in rs if len(r["turn_scores"]) > i] for i in range(4)]
        md.append(f"| {m.split('/')[-1]} | {c} | {sum(r['mean_score'] for r in rs) / len(rs):.2f} | "
                  f"{sum(r['all_turns_pass'] for r in rs)}/{len(rs)} | "
                  + " | ".join(f"{sum(x) / len(x):.2f}" if x else "–" for x in by_t)
                  + f" | {sum(len(r['steps']) for r in rs) / len(rs):.1f} | {sum(r['cost_usd'] for r in rs):.3f} |")
    text = "\n".join(md) + "\n"
    rep = config.ROOT / "reports" / f"{stamp}-sessions-{version}.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(text)
    return res, text
