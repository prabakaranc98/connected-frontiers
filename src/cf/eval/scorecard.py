"""Per-KB scorecard: is the KB true, does it cover the ecosystem, is it useful, what does it cost.

Three layers, each against a reference OUTSIDE the thing measured:
  1 truth      silver judges re-read the source page (status calibration, verifier, ER)
    coverage   owner's must-have list (recall) + a capture–recapture estimate (indicative)
    structure  connectivity, isolates, status mix
  2 usefulness Examiner sessions run by the Reasoner per retrieval mode (KB-derived keys: this measures
               use of the KB, not its truth, which is why layer 1 exists)
  3 cost       LLM spend by stage from the call log; churn vs the parent KB

No single overall number on purpose (counts and scores are evidence, not targets).
"""

from __future__ import annotations

import glob
import json
from collections import Counter
from pathlib import Path

import networkx as nx

from cf import config, kb

GOLD = config.EVAL / "gold"
RESULTS = config.EVAL / "results"
MUST_HAVE = config.CONFIGS / "must_have.yaml"


def _structure(g: dict) -> dict:
    G = nx.Graph()
    G.add_nodes_from(e["id"] for e in g["entities"])
    G.add_edges_from((e["head"], e["tail"]) for e in g["edges"] if e["status"] != "unsupported")
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    n = G.number_of_nodes() or 1
    st = Counter(e["status"] for e in g["edges"])
    multi = sum(1 for e in g["edges"] if len({x["publisher"] for x in e["evidence"]}) > 1)
    return {"entities": len(g["entities"]), "edges": len(g["edges"]),
            "largest_component_share": round(len(comps[0]) / n, 3) if comps else 0,
            "isolated_share": round(sum(1 for c in comps if len(c) == 1) / n, 3),
            "avg_degree": round(2 * G.number_of_edges() / n, 2),
            "status_mix": {k: round(v / max(len(g["edges"]), 1), 3) for k, v in st.most_common()},
            "multi_publisher_edges": multi, "types": dict(Counter(e["type"] for e in g["entities"]).most_common())}


def _coverage(g: dict) -> dict:
    """Lincoln–Petersen on orgs: capture 1 = orgs named on their own/vendor pages (self), capture 2 = orgs
    named by independent sources. Independence is assumed, so this is indicative, not a measurement."""
    ents = {e["id"]: e for e in g["entities"]}
    self_, other = set(), set()
    for e in g["edges"]:
        for x in e["evidence"]:
            for side in (e["head"], e["tail"]):
                if ents[side]["type"] != "org":
                    continue
                (self_ if x["source_kind"] == "self" else other).add(side)
    m = len(self_ & other)
    est = round(len(self_) * len(other) / m) if m else None
    seen = len(self_ | other)
    out = {"orgs_observed": seen, "capture_self": len(self_), "capture_independent": len(other), "recaptured": m,
           "lincoln_petersen_estimate": est, "observed_share_of_estimate": round(seen / est, 3) if est else None,
           "must_have": None}
    if MUST_HAVE.exists():
        import yaml

        from cf.agent.kg import KG
        want = yaml.safe_load(MUST_HAVE.read_text()) or []
        kg = KG(version=g.get("_version"))
        hits, misses = [], []
        for w in want:
            name = w if isinstance(w, str) else w.get("name")
            mm = kg.match(name, k=1)
            (hits if mm and mm[0][0] >= 0.9 else misses).append(name)
        out["must_have"] = {"listed": len(want), "found": len(hits), "recall": round(len(hits) / max(len(want), 1), 3),
                            "missing": misses}
    return out


def _truth(v: str) -> dict | None:
    f = GOLD / f"silver_summary_kb_{v}.json"
    if not f.exists():
        return None
    s = json.loads(f.read_text())
    pv = s["verification"]["production_verifier"]
    er = s["entity_resolution"]
    return {"status_calibration": s["status_calibration"], "adapter_verified_not_judged": s.get("adapter_verified_edges_not_judged"),
            "judges_kappa": s["verification"]["fleiss_kappa_judges"], "verifier_false_support": pv["false_support_rate"],
            "verifier_false_reject": pv["false_reject_rate"], "verifier_accuracy": pv["accuracy"],
            "er": {k: er.get(k) for k in er if k not in ("per_judge", "judge_agreement_with_others")},
            "disputed_for_owner": s["verification"]["disputed"], "spend_usd": s["spend_usd"]}


def _usefulness(v: str) -> dict | None:
    """Latest session-benchmark run on this KB, summarised with session-level intervals."""
    from cf.bench.session_report import summarize
    files = sorted(glob.glob(str(RESULTS / "sessions_*.jsonl")), key=lambda f: Path(f).stat().st_mtime)
    for f in reversed(files):
        rows = [json.loads(x) for x in Path(f).read_text().split("\n") if x.strip()]
        rows = [r for r in rows if r.get("kb_version") == v]
        if rows:
            return {"run_file": Path(f).name, "sessions": len({r["session_id"] for r in rows}), **summarize(rows)}
    return None


def _cost() -> dict:
    log = config.DATA / "interim" / "llm_calls.jsonl"
    by = Counter()
    for line in log.read_text().split("\n") if log.exists() else []:
        if not line.strip():
            continue
        r = json.loads(line)
        call = r.get("call", "?")
        stage = ("extract" if "extract" in call else "verify" if "verify" in call else "er" if "er_" in call or "judge" in call
                 else "segments" if "segment" in call else "sessions/bench" if "session" in call or "bench" in call or "task" in call
                 else call)
        by[stage] += r.get("cost_usd") or 0
    return {"all_time_usd": round(sum(by.values()), 3), "by_stage": {k: round(v, 3) for k, v in by.most_common()}}


def compute(version: str | None = None) -> dict:
    v = version or kb.current()
    g = json.loads(kb.graph_path(v).read_text())
    g["_version"] = v
    man = json.loads((kb.path(v) / "manifest.json").read_text())
    parent = man.get("parent")
    churn = kb.diff(parent, v) if parent and (kb.path(parent) / "graph.json").exists() else None
    if churn:
        churn = {k: churn[k] for k in ("entities_added", "entities_removed", "edges_added", "edges_removed", "edges_status_changed")}
    return {"kb_version": v, "parent": parent, "pages": man["counts"].get("pages"), "structure": _structure(g),
            "coverage": _coverage(g), "truth": _truth(v), "usefulness": _usefulness(v), "cost": _cost(), "churn_vs_parent": churn}


def _signed(x: float | None) -> str:
    return "–" if x is None else f"{x:+.2f}"


def render(s: dict) -> str:
    st, cv, tr, us, co = s["structure"], s["coverage"], s["truth"], s["usefulness"], s["cost"]
    L = [f"# Scorecard · KB `{s['kb_version']}`", "",
         f"{s['pages']:,} pages · {st['entities']:,} entities · {st['edges']:,} edges · parent `{s['parent']}`", "",
         "No single overall number: each row is evidence against a reference outside the thing measured.", "",
         "## 1 · Is the KB true?", ""]
    if tr:
        L += ["Silver ensemble re-reads each edge's source page (4 judges, majority ≥ 3).", "",
              "| Status | Edges judged | Supported by the cited page |", "|---|---|---|"]
        L += [f"| {k} | {x['judged']} | {x['silver_supported'] if x['silver_supported'] is not None else '–'} |"
              for k, x in tr["status_calibration"].items()]
        L += ["", (f"- Verifier vs silver: accuracy {tr['verifier_accuracy']}, false support {tr['verifier_false_support']}, "
                  f"false reject {tr['verifier_false_reject']} · judges κ {tr['judges_kappa']}"),
              f"- {tr['adapter_verified_not_judged']} adapter-verified edges (structured API facts) are not page-judged.",
              f"- Entity resolution vs silver: {json.dumps(tr['er'])}",
              f"- {tr['disputed_for_owner']} disputed items wait for owner review."]
    else:
        L += ["_Not measured yet: run `cf silver-kb`._"]
    L += ["", "## 1 · Does it cover the ecosystem?", "",
          (f"- Orgs observed: {cv['orgs_observed']:,}. Capture–recapture (self pages × independent pages): estimate "
          f"{cv['lincoln_petersen_estimate']}, observed share {cv['observed_share_of_estimate']} "
          "(indicative: the two captures are not independent).")]
    if cv["must_have"]:
        mh = cv["must_have"]
        L += [f"- Must-have list: {mh['found']}/{mh['listed']} found (recall {mh['recall']}). Missing: {', '.join(mh['missing'][:20]) or 'none'}"]
    else:
        L += ["- Must-have list: _pending: owner to write `configs/must_have.yaml`._"]
    L += ["", "## 1 · Is it clean and connected?", "",
          f"- Largest component {st['largest_component_share']:.1%} · isolated {st['isolated_share']:.1%} · avg degree {st['avg_degree']}",
          f"- Status mix: {', '.join(f'{k} {v:.1%}' for k, v in st['status_mix'].items())}",
          f"- Edges with > 1 publisher: {st['multi_publisher_edges']:,}", "",
          "## 2 · Is it useful? (Examiner sessions, Reasoner per retrieval mode)", ""]
    if us:
        from cf.bench.session_report import _ci
        L += [(f"{us['sessions']} gated sessions (`{us['run_file']}`). Keys come from the KB, so this measures use of the KB, "
              "not its truth. Intervals: 95% session bootstrap."), "",
              "| Model | Mode | Mean F1 | Turn exact | pass@1 |", "|---|---|---|---|---|"]
        L += [f"| {c['model']} | {c['mode']} | {_ci(c['f1'])} | {_ci(c['turn_exact'], True)} | {_ci(c['pass1'], True)} |"
              for c in us["cells"]]
        sig = [d for d in us["paired"] if d["metric"] == "f1"]
        L += ["", "Paired (same sessions, mean F1): " + " · ".join(
            f"{d['model']} {d['a']}−{d['b']} {d['diff']:+.2f} [{d['lo']:+.2f}, {d['hi']:+.2f}]" for d in sig)]
    else:
        L += ["_Not measured yet: run `cf sessions` then `cf sessions-bench`._"]
    L += ["", "## 3 · What does it cost, and how much did it change?", "",
          f"- LLM spend, all time: ${co['all_time_usd']} · by stage: " + ", ".join(f"{k} ${v}" for k, v in co["by_stage"].items())]
    if s["churn_vs_parent"]:
        L += [f"- Churn vs parent: {json.dumps(s['churn_vs_parent'])}"]
    return "\n".join(L) + "\n"


def write(version: str | None = None) -> tuple[Path, dict]:
    s = compute(version)
    out = config.ROOT / "reports" / f"scorecard-{s['kb_version']}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(s))
    (config.EVAL / "results").mkdir(parents=True, exist_ok=True)
    (config.EVAL / "results" / f"scorecard_{s['kb_version']}.json").write_text(json.dumps(s, indent=1))
    return out, s
