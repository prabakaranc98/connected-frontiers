"""Meta loop, level L2 (harness): diagnose failures → propose harness specs → select on train →
confirm on held-out → log. One iteration = one controlled experiment.

Guards
- The held-out split is only used for the promotion decision, never for diagnosis or proposal.
- The proposer is a different model family from the Reasoners it tunes, and it only sees failure
  summaries from the train split.
- The search space is bounded (HarnessSpec fields); free text is limited to a short strategy note.
- Promotion: paired Δ mean F1 on held-out with a 95% interval above 0 for the target mode, and no
  significant drop elsewhere. Every iteration is appended to eval/experiments.jsonl.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from cf import config
from cf.agent.kg import KG
from cf.bench.session_report import per_session, render, summarize
from cf.bench.sessions import HARNESS_H0, run_session
from cf.eval.stats import paired
from cf.llm.client import AUTO, LLM

LEDGER = config.EVAL / "experiments.jsonl"
PROPOSER = "mistralai/mistral-small-2603"           # different family from Inkling / Qwen (the tuned Reasoners)


def pool(sets: tuple[str, ...] = ("s1", "s2")) -> list[dict]:
    """Distinct-anchor sessions from several sets, each with a deterministic train / heldout split."""
    out, seen = [], set()
    for v in sets:
        for line in (config.EVAL / "gold" / f"sessions_{v}.jsonl").read_text().split("\n"):
            if not line.strip():
                continue
            s = json.loads(line)
            key = (s["template"], s["anchors"][0])
            if key in seen:
                continue
            seen.add(key)
            s = {**s, "id": f"{v}:{s['id']}"}
            s["split"] = "heldout" if int(hashlib.md5(s["id"].encode()).hexdigest(), 16) % 2 else "train"
            out.append(s)
    return out


def grid(models: list[str], modes: list[str], sessions: list[dict], harness: dict, trials: int = 1,
         temperature: float = 0.0, workers: int = 6) -> list[dict]:
    kg = KG()
    _ = kg.rag
    jobs = [(m, c, s, t) for m in models for c in modes for s in sessions for t in range(trials)]
    with ThreadPoolExecutor(workers) as pool_:
        rows = list(pool_.map(lambda j: run_session(j[0], j[2], j[1], kg, reasoning=AUTO, temperature=temperature,
                                                    trial=j[3], harness=harness), jobs))
    bad = sum(1 for r in rows for t in r["turns"] if t.get("error"))
    turns = sum(len(r["turns"]) for r in rows) or 1
    if bad / turns > 0.02:                                   # infrastructure errors invalidate the comparison
        raise RuntimeError(f"invalid experiment: {bad}/{turns} turns errored (e.g. {next(t['error'] for r in rows for t in r['turns'] if t.get('error'))[:120]})")
    return rows


# ---- diagnosis (train only) ------------------------------------------------------------------------
def diagnose(rows: list[dict], sessions: dict, max_examples: int = 8) -> dict:
    c, ex = Counter(), []
    for r in rows:
        steps = Counter(s["turn"] for s in r["steps"])
        for t in r["turns"]:
            if t["score"] >= 1.0:
                continue
            d = t.get("detail") or {}
            k = sessions[r["session_id"]]["turns"][t["turn"]]["key"]
            kind = ("answered nothing" if not t.get("items") else "wrong labels" if k["kind"] == "labels"
                    else "missed entities" if (d.get("recall") or 0) < 1 and (d.get("precision") or 0) >= 0.8
                    else "extra entities" if (d.get("precision") or 0) < 0.8 and (d.get("recall") or 0) >= 0.8
                    else "missed and extra")
            c[f"{r['condition']}: {kind}"] += 1
            if steps[t["turn"]] >= r.get("max_steps", 6) - 1:
                c[f"{r['condition']}: hit step budget"] += 1
            if len(ex) < max_examples:
                ex.append({"mode": r["condition"], "question": sessions[r["session_id"]]["messages"][t["turn"]],
                           "answer_size": len(k.get("ids") or k.get("labels") or []), "failure": kind,
                           "tools_used": [s["tool"] for s in r["steps"] if s["turn"] == t["turn"]][:12],
                           "returned": [i.get("name") for i in (t.get("items") or [])][:8]})
    return {"failure_counts": dict(c.most_common()), "examples": ex}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Spec(_Strict):
    rationale: str
    max_steps: int = Field(ge=4, le=14)
    neighbor_limit: int = Field(ge=10, le=100)
    truncation_notice: bool
    empty_hints: bool
    schema_card: bool
    extra_instructions: str = Field(max_length=700)


class Proposal(_Strict):
    specs: list[Spec]


PROPOSE = """You improve the harness of a tool-using agent that answers multi-turn questions from a knowledge graph.
You can only change these switches:
- max_steps (4-14): tool calls allowed per turn
- neighbor_limit (10-100): edges returned by `neighbors` by default
- truncation_notice: tell the agent when a list was cut and how many items were left out
- empty_hints: when a query finds nothing, show the relations and entity types that do exist at that node
- schema_card: put the graph's relation vocabulary (which relation links which types) in the system prompt
- extra_instructions: a short strategy note added to the system prompt (max 700 chars)
Read the failure summary and propose {n} DIFFERENT specs, each targeting the most frequent failures.
Explain each in one sentence (rationale)."""


def propose(current: dict, diag: dict, n: int = 3) -> list[dict]:
    user = f"Current spec: {json.dumps({k: v for k, v in current.items() if k != 'id'})}\n\nFailures (train split):\n{json.dumps(diag, indent=1)[:6000]}"
    out = LLM(PROPOSER).parse(PROPOSE.format(n=n), user, Proposal, "meta_propose", max_tokens=2500)
    return [{**s.model_dump(), "id": f"h{i + 1}"} for i, s in enumerate(out.specs[:n])]


def _f1(rows, mode):
    ps = per_session([r for r in rows if r["condition"] == mode])
    return {(m, sid): x["f1"] for (m, _), sess in ps.items() for sid, x in sess.items()}


def iterate(models: list[str], modes: tuple[str, ...] = ("kg_tools", "graph_query"), n_props: int = 3,
            heldout_trials: int = 2) -> dict:
    from cf import kb
    sessions = pool()
    by_id = {s["id"]: s for s in sessions}
    train = [s for s in sessions if s["split"] == "train"]
    held = [s for s in sessions if s["split"] == "heldout"]
    spend0 = LLM.spent_usd
    # 1 · baseline on train, diagnose, propose
    base_tr = grid(models, list(modes), train, HARNESS_H0)
    diag = diagnose(base_tr, by_id)
    props = propose(HARNESS_H0, diag, n_props)
    # 2 · select on train: mean paired Δ F1 over models × modes
    scored = []
    for p in props:
        rows = grid(models, list(modes), train, p)
        ds = []
        for mode in modes:
            a, b = _f1(rows, mode), _f1(base_tr, mode)
            ds.append(paired(a, b))
        gain = sum(d.get("diff", 0) for d in ds) / len(ds)
        scored.append({"spec": p, "train_gain": round(gain, 3), "train_paired": ds})
    best = max(scored, key=lambda x: x["train_gain"])
    # 3 · confirm on held-out (only now is it touched): baseline vs best, k trials, plus cheap reference modes
    ref = grid(models, ["closed_book", "oracle"], held, HARNESS_H0, trials=1)
    base_ho = grid(models, list(modes), held, HARNESS_H0, trials=heldout_trials, temperature=0.7)
    best_ho = grid(models, list(modes), held, best["spec"], trials=heldout_trials, temperature=0.7)
    decision = {}
    for mode in modes:
        for m in models:
            mm = m.split("/")[-1]
            a = {sid: v for (mod, sid), v in _f1(best_ho, mode).items() if mod == mm}
            b = {sid: v for (mod, sid), v in _f1(base_ho, mode).items() if mod == mm}
            decision[f"{mm}|{mode}"] = paired(a, b)
    wins = [d for d in decision.values() if d.get("n") and d["lo"] > 0]
    losses = [d for d in decision.values() if d.get("n") and d["hi"] < 0]
    promote = bool(wins) and not losses
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    rec = {"ts": stamp, "level": "L2-harness", "kb_version": kb.current(), "models": models, "modes": list(modes),
           "sessions": {"train": len(train), "heldout": len(held)}, "diagnosis": diag, "proposals": scored,
           "selected": best["spec"], "heldout_paired": decision, "promote": promote,
           "spend_usd": round(LLM.spent_usd - spend0, 4)}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    rows_all = ref + base_ho + best_ho
    (config.EVAL / "results").mkdir(parents=True, exist_ok=True)
    (config.EVAL / "results" / f"meta_{stamp}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_all))
    rep = render(summarize(rows_all), f"Meta loop L2 · held-out ({len(held)} sessions) · h0 vs {best['spec']['id']}")
    (config.ROOT / "reports" / f"{stamp}-meta-L2.md").write_text(_report(rec) + "\n" + rep)
    return rec


def _report(rec: dict) -> str:
    L = [f"# Meta loop · L2 harness · {rec['ts']}", "",
         (f"KB `{rec['kb_version']}` · train {rec['sessions']['train']} / held-out {rec['sessions']['heldout']} sessions · "
         f"spend ${rec['spend_usd']}"), "", "## Diagnosis (train)", ""]
    L += [f"- {k}: {v}" for k, v in rec["diagnosis"]["failure_counts"].items()]
    L += ["", "## Proposals (selected on train)", "", "| Spec | Train gain (mean paired ΔF1) | Rationale |", "|---|---|---|"]
    L += [f"| {p['spec']['id']} | {p['train_gain']:+.3f} | {p['spec']['rationale']} |" for p in rec["proposals"]]
    L += ["", f"Selected: `{json.dumps({k: v for k, v in rec['selected'].items() if k != 'rationale'})}`", "",
          "## Held-out decision (paired, same sessions)", "", "| Model · mode | Δ F1 | 95% interval | P(Δ≤0) |", "|---|---|---|---|"]
    L += [f"| {k} | {d['diff']:+.3f} | [{d['lo']:+.3f}, {d['hi']:+.3f}] | {d['p_le0']:.3f} |"
          for k, d in rec["heldout_paired"].items() if d.get("n")]
    L += ["", f"**Promote: {'yes' if rec['promote'] else 'no'}** (rule: some interval above 0, none below 0)."]
    return "\n".join(L) + "\n"


def confirm(spec_ids: tuple[str, ...] = ("h2", "h3"), models: list[str] | None = None,
            modes: tuple[str, ...] = ("kg_tools", "graph_query"), trials: int = 2) -> dict:
    """Re-run only the held-out confirmation for specs proposed in the last VALID train phase
    (e.g. after an infrastructure failure invalidated the held-out part). Appends a ledger record."""
    from cf import kb
    recs = [json.loads(x) for x in LEDGER.read_text().split("\n") if x.strip()]
    base = next(r for r in reversed(recs) if r.get("proposals"))
    specs = {p["spec"]["id"]: p["spec"] for p in base["proposals"]}
    models = models or base["models"]
    held = [s for s in pool() if s["split"] == "heldout"]
    spend0 = LLM.spent_usd
    temp = 0.0 if trials == 1 else 0.7                       # one trial: deterministic; several: sampled (pass^k)
    runs = {"h0": grid(models, list(modes), held, HARNESS_H0, trials=trials, temperature=temp)}
    for sid in spec_ids:
        runs[sid] = grid(models, list(modes), held, specs[sid], trials=trials, temperature=temp)
    decisions = {}
    for sid in spec_ids:
        for mode in modes:
            for m in models:
                mm = m.split("/")[-1]
                a = {s: v for (mod, s), v in _f1(runs[sid], mode).items() if mod == mm}
                b = {s: v for (mod, s), v in _f1(runs["h0"], mode).items() if mod == mm}
                decisions[f"{sid}|{mm}|{mode}"] = paired(a, b)
    verdict = {}
    for sid in spec_ids:
        ds = [d for k, d in decisions.items() if k.startswith(sid + "|") and d.get("n")]
        verdict[sid] = bool([d for d in ds if d["lo"] > 0]) and not [d for d in ds if d["hi"] < 0]
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    rec = {"ts": stamp, "level": "L2-harness", "kind": "heldout_confirmation", "of": base["ts"], "kb_version": kb.current(),
           "models": models, "modes": list(modes), "heldout_sessions": len(held), "trials": trials,
           "specs": {s: specs[s] for s in spec_ids}, "heldout_paired": decisions, "promote": verdict,
           "spend_usd": round(LLM.spent_usd - spend0, 4)}
    with LEDGER.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    rows = [r for rs in runs.values() for r in rs]
    (config.EVAL / "results" / f"meta_confirm_{stamp}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    L = [f"# Meta loop · L2 held-out confirmation · {stamp}", "", (f"Of train phase `{base['ts']}` · {len(held)} held-out sessions × "
         f"{trials} trial(s) · spend ${rec['spend_usd']}"), "", "| Spec · model · mode | Δ F1 vs h0 | 95% interval | P(Δ≤0) |",
         "|---|---|---|---|"]
    L += [f"| {k} | {d['diff']:+.3f} | [{d['lo']:+.3f}, {d['hi']:+.3f}] | {d['p_le0']:.3f} |" for k, d in decisions.items() if d.get("n")]
    L += ["", "Promote (some interval above 0, none below): " + ", ".join(f"{s} {'yes' if v else 'no'}" for s, v in verdict.items())]
    (config.ROOT / "reports" / f"{stamp}-meta-L2-confirm.md").write_text("\n".join(L) + "\n\n" + render(summarize(rows), "Held-out runs"))
    return rec
