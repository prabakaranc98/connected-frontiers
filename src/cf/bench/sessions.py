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
from cf.llm.client import LLM, strict_schema

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
        ms = [m for m, es in by_m.items()                 # methods; technologies only when widely used
              if len({x["head"] for x in es}) >= (2 if kg.ents[m]["type"] == "method" else 3)]
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
        deriv = (e.get("attrs") or {}).get("derivation")
        turns = [{"intent": f"Ask what model '{kg.name(x)}' is built on.", "key": {"kind": "set", "ids": [base]}}]
        if deriv:                                       # only when the source records it (HF metadata)
            turns.append({"intent": "Ask how it was derived from that base (for example fine-tuned, quantized, merged).",
                          "key": {"kind": "labels", "labels": {base: deriv}}})
        turns += [{"intent": "Ask which organisation offers that base model.", "key": {"kind": "set", "ids": offer}},
                  {"intent": "Ask which other models are built on the same base; it is fine if there are none.",
                   "key": {"kind": "set", "ids": sib[:30], "allow_empty": True}}]
        sib_edges = [z["id"] for h in sib[:30] for z in base_of[h] if z["tail"] == base]
        return {"template": "lineage", "anchors": [x], "turns": turns,
                "gold_edge_ids": [e["id"]] + [o["id"] for o in _edges(kg, {"offers"}) if o["tail"] == base] + sib_edges}
    return None


def spec_benchmark(kg: KG, rnd: random.Random) -> dict | None:
    """benchmark → models reporting on it → who offers them → what else those models are measured on."""
    on = defaultdict(set)
    for e in _edges(kg, {"measured_on"}, "model", "benchmark"):
        on[e["tail"]].add(e["head"])
    bs = [b for b, ms in on.items() if 3 <= len(ms) <= 15 and _ok(kg, b)]
    rnd.shuffle(bs)
    for b in bs:
        models = sorted(m for m in on[b] if _ok(kg, m))
        offers = [e for e in _edges(kg, {"offers"}, "org") if e["tail"] in models]
        other = [e for e in _edges(kg, {"measured_on"}, "model", "benchmark") if e["head"] in models and e["tail"] != b and _ok(kg, e["tail"])]
        others = sorted({e["tail"] for e in other})
        if len(models) < 3 or len(others) > 12:
            continue
        return {"template": "benchmark", "anchors": [b], "turns": [
            {"intent": f"Ask which models report results on the benchmark '{kg.name(b)}'.", "key": {"kind": "set", "ids": models}},
            {"intent": "Ask which organisations offer those models; it is fine if there are none.",
             "key": {"kind": "set", "ids": sorted({e['head'] for e in offers}), "allow_empty": True}},
            {"intent": "Ask which other benchmarks those same models are also evaluated on; it is fine if there are none.",
             "key": {"kind": "set", "ids": others, "allow_empty": True}},
        ], "gold_edge_ids": [e["id"] for e in _edges(kg, {"measured_on"}) if e["tail"] == b and e["head"] in models]
                           + [e["id"] for e in offers] + [e["id"] for e in other]}
    return None


def spec_customers(kg: KG, rnd: random.Random) -> dict | None:
    """provider → its customers → how well each relationship is evidenced → which customers also use another provider."""
    serves = defaultdict(list)
    for e in _edges(kg, {"serves"}, "org", "org"):
        serves[e["head"]].append(e)
    ps = [p for p, es in serves.items() if 3 <= len({e["tail"] for e in es}) <= 12 and _ok(kg, p)]
    rnd.shuffle(ps)
    for p in ps:
        es = [e for e in serves[p] if _ok(kg, e["tail"])]
        custs = sorted({e["tail"] for e in es})
        if len(custs) < 3:
            continue
        also = [e for q, qs in serves.items() if q != p for e in qs if e["tail"] in custs]
        return {"template": "customers", "anchors": [p], "turns": [
            {"intent": f"Ask which customers '{kg.name(p)}' serves.", "key": {"kind": "set", "ids": custs}},
            {"intent": "Ask, for each of those customers, whether the relationship is verified, corroborated, confirmed by "
                       "the other party, or only claimed by the provider.",
             "key": {"kind": "labels", "labels": {e["tail"]: e["status"] for e in sorted(es, key=lambda x: x["strength"])}}},
            {"intent": "Ask which of those customers are also served by another provider in the ecosystem; it is fine if none.",
             "key": {"kind": "set", "ids": sorted({e['tail'] for e in also}), "allow_empty": True}},
        ], "gold_edge_ids": [e["id"] for e in es] + [e["id"] for e in also]}
    return None


def spec_talent(kg: KG, rnd: random.Random) -> dict | None:
    """org → roles it hires for → other orgs hiring for the same roles (education: what the frontier hires for)."""
    hires = defaultdict(set)
    for e in _edges(kg, {"hires_for"}, "org"):
        if _ok(kg, e["tail"]):
            hires[e["head"]].add(e["tail"])
    by_role = defaultdict(set)
    for o, rs in hires.items():
        for r in rs:
            by_role[r].add(o)
    orgs = [o for o, rs in hires.items() if 2 <= len(rs) <= 10 and _ok(kg, o)]
    rnd.shuffle(orgs)
    for o in orgs:
        roles = sorted(hires[o])
        peers = sorted({q for r in roles for q in by_role[r] if q != o})
        if not peers or len(peers) > 15:
            continue
        return {"template": "talent", "anchors": [o], "turns": [
            {"intent": f"Ask which roles '{kg.name(o)}' is hiring for.", "key": {"kind": "set", "ids": roles}},
            {"intent": "Ask which other organisations hire for at least one of those same roles.", "key": {"kind": "set", "ids": peers}},
        ], "gold_edge_ids": [e["id"] for e in _edges(kg, {"hires_for"}) if e["tail"] in roles and (e["head"] == o or e["head"] in peers)]}
    return None


GENERATORS = {"opportunity": spec_opportunity, "landscape": spec_landscape, "learn": spec_learn, "lineage": spec_lineage,
              "benchmark": spec_benchmark, "customers": spec_customers, "talent": spec_talent}
ANCHOR_CAP = 2                                          # sessions per anchor entity, across templates


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
            "learn": "an engineer learning the field", "lineage": "a researcher tracing model lineage",
            "benchmark": "an ML engineer comparing evaluations", "customers": "an investor checking traction claims",
            "talent": "a student planning a career in frontier AI"}


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


SOLVER = "nvidia/nemotron-3.5-lightning"           # gate: different families from the writer (Inkling)
SOLVERS = [SOLVER, "mistralai/mistral-small-2603"]   # pass if either solves every turn from the gold evidence
GATE = 0.6


def build(n: int = 12, seed: int = 11, writer: str | None = None, solvers: list[str] = SOLVERS,
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
    seen_anchor: Counter = Counter()
    while len(accepted) < n and tries < n * 8:
        tmpl = names[tries % len(names)]
        tries += 1
        spec = GENERATORS[tmpl](kg, rnd)
        if not spec:
            continue
        if any(s["anchors"] == spec["anchors"] and s["template"] == tmpl for s in accepted + rejected) \
                or seen_anchor[spec["anchors"][0]] >= ANCHOR_CAP:
            continue
        seen_anchor[spec["anchors"][0]] += 1
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
        attempts, ok = [], False
        for solver in solvers:
            r = run_session(solver, s, "oracle", kg, reasoning=0)
            passed = r["mean_score"] >= gate and min(r["turn_scores"]) > 0   # every turn answerable from its gold
            attempts.append({"solver": solver, "turn_scores": r["turn_scores"], "mean": r["mean_score"],
                          "passed": passed, "cost_usd": r["cost_usd"]})
            if passed:
                ok = True
                break
        s["gate"] = {"condition": "oracle", "passed": ok, "tries": attempts, "turn_scores": attempts[-1]["turn_scores"],
                     "mean": attempts[-1]["mean"], "cost_usd": round(sum(t["cost_usd"] for t in attempts), 5)}
        (accepted if ok else rejected).append(
            s if ok else {**s, "reasons": [f"solver gate: {[(t['solver'].split('/')[-1], t['turn_scores']) for t in attempts]}"]})
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


def turn_detail(kg: KG, key: dict, items: list[dict]) -> dict:
    """Score one turn and say WHY: precision (wrong entities named), recall (right ones missed),
    and citation validity (cited edge ids exist in the KB and touch the entity they are cited for)."""
    def res(n):
        m = kg.match(n or "", k=1, exact_first=True)
        return m[0][1] if m and m[0][0] >= 0.75 else None
    items = [it for it in items or [] if isinstance(it, dict)]
    resolved = [(it, res(it.get("name"))) for it in items]
    got = {r for _, r in resolved if r}
    cites = [(r, str(c).strip("[] ").removeprefix("edge_id:").strip()) for it, r in resolved for c in (it.get("edge_ids") or [])]
    valid = [c for _, c in cites if c in kg.edges]
    relevant = [c for r, c in cites if c in kg.edges and r in (kg.edges[c]["head"], kg.edges[c]["tail"])]
    d = {"n_pred": len(items), "n_resolved": len(got), "unresolved": [it.get("name") for it, r in resolved if not r][:5],
         "citations": len(cites), "citations_valid": len(valid), "citations_relevant": len(relevant)}
    if key["kind"] == "labels":
        gold = key["labels"]
        pred = {r: str(it.get("label") or "") for it, r in resolved}
        if all(v in STATUSES for v in gold.values()):
            ok = sum(_status(pred.get(k, "")) == v for k, v in gold.items())
        else:
            anyl = " ".join(pred.values())                # derivation: label may sit on either model
            ok = sum(_letters(v)[:6] in _letters(pred.get(k, "") or anyl) for k, v in gold.items())
        return {**d, "score": round(ok / len(gold), 3), "precision": None, "recall": round(len(got & set(gold)) / len(gold), 3)}
    gold = set(key.get("ids", []))
    if not gold:                                           # correct abstention
        return {**d, "score": 1.0 if not got else 0.0, "precision": None if not got else 0.0, "recall": None}
    tp = len(got & gold)
    p, r = tp / max(len(got), 1), tp / len(gold)
    if key["kind"] == "single":
        return {**d, "score": 1.0 if got & gold and len(got) <= 2 else 0.0, "precision": round(p, 3), "recall": round(r, 3)}
    return {**d, "score": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "precision": round(p, 3) if got else None, "recall": round(r, 3)}


def score_turn(kg: KG, key: dict, items: list[dict]) -> float:
    return turn_detail(kg, key, items)["score"]


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
class AnswerItem(_Strict):
    name: str
    label: str
    edge_ids: list[str]


class TurnAnswer(_Strict):
    answer: str
    items: list[AnswerItem]


SCHEMA = strict_schema(TurnAnswer)
FORMAT = ("Now give your final answer to my last question as JSON. items = the entities that ARE the answer "
          "(not the entity the question is about); label only if the question asks for one, else empty.")
TOOL_TURN = """This is a multi-turn conversation. For each user message, first use the tools to find the evidence
(several calls are fine), then answer in short prose, citing edge ids like [edge_id]. After that you will be asked
for the structured form of your answer."""

QUERY_HINT = """
Prefer ONE graph_query over many single-hop calls: find the start entity id, then express the multi-hop
question as a path, e.g. orgs working on a problem → their methods:
path=[{"relation":"works_on","direction":"in","type":"org"},{"relation":"uses_method","direction":"out"}].
"""

TURN_CONTRACT = """This is a multi-turn conversation. After each user message, reply with ONLY one JSON object:
{"answer": "<short prose; cite edge ids like [edge_id]>",
 "items": [{"name": "<entity name>", "label": "<label if the question asks for one, else empty>", "edge_ids": ["..."]}]}
items = the entities that ARE the answer to this turn's question, by name, e.g. for "what is X built on?" list
the base model, not X; for "which of them use M?" list those organisations, not M. Never list the entity the
question is about. Empty list if the answer is none."""


def run_session(model: str, s: dict, condition: str, kg: KG, reasoning=None, max_steps: int = 6,
                temperature: float = 0.0, trial: int = 0) -> dict:
    import time

    from cf import trace
    from cf.agent import harness as H
    from cf.agent.kg import QUERY_SPECS, TOOL_SPECS
    llm = LLM(model)
    t0, spend0 = time.time(), LLM.spent_usd
    base = {"kg_tools": H.SYSTEM_TOOLS, "graph_query": H.SYSTEM_TOOLS + QUERY_HINT, "oracle": H.SYSTEM_ORACLE,
            "graph_rag": H.SYSTEM_ORACLE, "closed_book": H.SYSTEM_CLOSED}[condition]
    contract = TOOL_TURN if condition in ("kg_tools", "graph_query") else TURN_CONTRACT
    messages = [{"role": "system", "content": base.split("When you are done")[0] + contract}]
    tools = {"kg_tools": TOOL_SPECS, "graph_query": QUERY_SPECS}.get(condition)
    allowed = {x["function"]["name"] for x in tools or []}
    turns, calls = [], []
    for i, (msg_text, t) in enumerate(zip(s["messages"], s["turns"], strict=True)):
        content = msg_text
        if condition == "oracle" and i == 0:
            content = f"KNOWLEDGE GRAPH EXCERPT:\n{oracle_context(kg, s)}\n\n{msg_text}"
        elif condition == "graph_rag":                 # fixed retrieval per turn, on the conversation so far
            r = kg.search_text(" ".join(s["messages"][:i + 1]), k=8)
            ctx = "\n".join([f"[{p['chunk_id']}] ({p['url']}) {p['text']}" for p in r["passages"]]
                            + [f"[{e['edge_id']}] {e['head']} —{e['relation']}→ {e['tail']} (status: {e['status']})"
                               for e in r["supporting_edges"]])
            calls.append({"turn": i, "step": 0, "tool": "graph_rag.retrieve", "args": None, "touched": H._touched(r)})
            content = f"RETRIEVED PASSAGES AND EDGES:\n{ctx}\n\n{msg_text}"
        messages.append({"role": "user", "content": content})
        final = None
        for step in range(max_steps):
            last = step == max_steps - 1
            if last and tools:
                messages.append({"role": "user", "content": "Step budget reached. Answer now with the JSON object."})
            try:
                m, _ = llm.chat(messages, tools=None if last else tools, name=f"session_{condition}",
                                max_tokens=2500, reasoning_max_tokens=reasoning,
                                schema=None if tools and not last else SCHEMA, temperature=temperature)
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
                        result = getattr(kg, fn)(**args) if fn in allowed else {"error": "unknown tool"}
                    except (TypeError, ValueError, KeyError) as e:
                        result = {"error": f"bad arguments: {e}"}
                    calls.append({"turn": i, "step": step, "tool": fn, "args": tc["function"].get("arguments"),
                                  "touched": H._touched(result)})
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result)[:6000]})
                continue
            text = m.get("content") or ""
            if tools:                                      # tool modes: the walk ends in prose → structured re-ask
                messages.append({"role": "assistant", "content": text})
                try:
                    m2, _ = llm.chat(messages + [{"role": "user", "content": FORMAT}], name=f"session_{condition}_format",
                                     max_tokens=2000, reasoning_max_tokens=reasoning, schema=SCHEMA, temperature=temperature)
                    final = H._parse_final(m2.get("content") or "")
                except RuntimeError as e:
                    final = {**H._parse_final(text), "format_error": str(e)[:120]}
            else:                                          # single call already constrained by the schema
                final = H._parse_final(text)
                messages.append({"role": "assistant", "content": text})
            break
        final = final or {"answer": "", "items": [], "error": "no answer"}
        det = turn_detail(kg, t["key"], final.get("items") or [])
        fmt_err = final.get("format_error") or ("parse_error" if final.get("parse_error") else None)
        turns.append({"turn": i, "score": det["score"], "detail": det, "items": final.get("items"),
                      "answer": (final.get("answer") or "")[:1500], "error": final.get("error"), "format_error": fmt_err})
        if final.get("error"):
            break
    scores = [t["score"] for t in turns] + [0.0] * (len(s["turns"]) - len(turns))
    out = {"session_id": s["id"], "template": s["template"], "model": model, "condition": condition,
           "trial": trial, "temperature": temperature,
           "kb_version": kg.kb_version, "run_id": trace.RUN_ID, "turns": turns, "steps": calls,
           "turn_scores": scores, "mean_score": round(sum(scores) / len(scores), 3),
           "all_turns_pass": all(x >= 0.5 for x in scores),
           "cost_usd": round(LLM.spent_usd - spend0, 5), "latency_s": round(time.time() - t0, 1)}
    trace.event("agent", {"session": s["id"], "model": model, "condition": condition, "summary": out["turn_scores"]})
    return out


def load(version: str) -> list[dict]:
    path = config.EVAL / "gold" / f"sessions_{version}.jsonl"
    return [json.loads(x) for x in path.read_text().split("\n") if x.strip()]


def bench(models: dict, conditions: list[str], version: str, workers: int = 6, trials: int = 1,
          temperature: float = 0.0) -> tuple[list[dict], str]:
    """Every model × mode × session × trial. Results → eval/results/sessions_<v>_<stamp>.jsonl;
    report with intervals and paired mode comparisons → reports/<stamp>-sessions-<v>.md."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime

    from cf.bench.session_report import render, summarize
    kg = KG()
    ss = load(version)
    if any(s["kb_version"] != kg.kb_version for s in ss):
        raise SystemExit(f"sessions are pinned to {ss[0]['kb_version']}, CURRENT is {kg.kb_version}: `cf kb use` first")
    _ = kg.rag                                               # build the GraphRAG index once, before threads
    jobs = [(m, r, c, s, t) for m, r in models.items() for c in conditions for s in ss for t in range(trials)]
    spend0 = LLM.spent_usd
    with ThreadPoolExecutor(workers) as pool:
        res = list(pool.map(lambda j: run_session(j[0], j[3], j[2], kg, reasoning=j[1], temperature=temperature, trial=j[4]), jobs))
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = config.EVAL / "results" / f"sessions_{version}_{stamp}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in res))
    title = (f"Multi-turn sessions `{version}` · KB `{kg.kb_version}` · {len(ss)} sessions × {trials} trial(s) at "
             f"T={temperature} · spend ${LLM.spent_usd - spend0:.3f}")
    text = render(summarize(res), title)
    rep = config.ROOT / "reports" / f"{stamp}-sessions-{version}.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(text)
    return res, text
