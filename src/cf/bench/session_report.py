"""Multi-turn session results → credible numbers: session-level metrics with 95% intervals,
pass@1 and pass^k over k trials, precision / recall / citation validity, format errors, and
paired comparisons between retrieval modes on the same sessions.
"""

from __future__ import annotations

import math
from collections import defaultdict

from cf.eval.stats import bootstrap, paired, wilson

MODES = ["closed_book", "graph_rag", "kg_tools", "graph_query", "oracle"]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def per_session(rows: list[dict]) -> dict:
    """(model, mode) → session_id → metrics averaged over trials (+ pass^k across trials)."""
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        mode = r["condition"] if r.get("harness") in (None, "h0") else f"{r['condition']}@{r['harness']}"   # never pool specs
        by[(r["model"].split("/")[-1], mode)][r["session_id"]].append(r)
    out = {}
    for cell, sess in by.items():
        out[cell] = {}
        for sid, trials in sess.items():
            def turns(t):
                return t.get("turns") or []
            exact = [all(x == 1.0 for x in t["turn_scores"]) for t in trials]
            dets = [tu.get("detail") or {} for t in trials for tu in turns(t)]
            cit = sum(d.get("citations", 0) for d in dets)
            out[cell][sid] = {
                "f1": _mean([t["mean_score"] for t in trials]),
                "turn_exact": _mean([sum(x == 1.0 for x in t["turn_scores"]) / len(t["turn_scores"]) for t in trials]),
                "pass1": sum(exact) / len(exact), "pass_k": float(all(exact)), "k": len(trials),
                "precision": _mean([d.get("precision") for d in dets]), "recall": _mean([d.get("recall") for d in dets]),
                "cite_valid": (sum(d.get("citations_valid", 0) for d in dets) / cit) if cit else None,
                "cite_relevant": (sum(d.get("citations_relevant", 0) for d in dets) / cit) if cit else None,
                "format_err": _mean([1.0 if tu.get("format_error") else 0.0 for t in trials for tu in turns(t)]),
                "tool_calls": _mean([len(t.get("steps", [])) for t in trials]),
                "cost": sum(t.get("cost_usd", 0) for t in trials), "template": trials[0]["template"]}
    return out


def summarize(rows: list[dict]) -> dict:
    ps = per_session(rows)
    cells = []
    for (m, c), sess in sorted(ps.items(), key=lambda kv: (kv[0][0], MODES.index(kv[0][1]) if kv[0][1] in MODES else 9)):
        v = list(sess.values())
        n = len(v)
        k = max(x["k"] for x in v)
        p1 = bootstrap([x["pass1"] for x in v])
        pk = sum(x["pass_k"] for x in v)
        cells.append({"model": m, "mode": c, "sessions": n, "k": k,
                      "f1": bootstrap([x["f1"] for x in v]), "turn_exact": bootstrap([x["turn_exact"] for x in v]),
                      "pass1": p1, "pass_k": (pk / n, *wilson(pk, n)),
                      "precision": bootstrap([x["precision"] for x in v]), "recall": bootstrap([x["recall"] for x in v]),
                      "cite_valid": _mean([x["cite_valid"] for x in v]), "cite_relevant": _mean([x["cite_relevant"] for x in v]),
                      "format_err": _mean([x["format_err"] for x in v]), "tool_calls": _mean([x["tool_calls"] for x in v]),
                      "cost": sum(x["cost"] for x in v)})
    comps = []
    for m in sorted({m for m, _ in ps}):
        for a, b in [("kg_tools", "closed_book"), ("oracle", "kg_tools"), ("kg_tools", "graph_query"),
                     ("graph_query", "closed_book"), ("graph_rag", "closed_book")]:
            if (m, a) in ps and (m, b) in ps:
                for metric in ("f1", "pass1"):
                    d = paired({s: x[metric] for s, x in ps[(m, a)].items()}, {s: x[metric] for s, x in ps[(m, b)].items()})
                    if d.get("n"):
                        comps.append({"model": m, "a": a, "b": b, "metric": metric, **d})
    by_tmpl = defaultdict(list)
    for (m, c), sess in ps.items():
        for x in sess.values():
            by_tmpl[(m, c, x["template"])].append(x["f1"])
    return {"cells": cells, "paired": comps,
            "by_template": {f"{m}|{c}|{t}": round(sum(v) / len(v), 3) for (m, c, t), v in sorted(by_tmpl.items())}}


def _ci(t, pct=False):
    m, lo, hi = t
    if math.isnan(m):
        return "–"
    return f"{m:.0%} [{lo:.0%}–{hi:.0%}]" if pct else f"{m:.2f} [{lo:.2f}–{hi:.2f}]"


def render(s: dict, title: str) -> str:
    L = [f"# {title}", "",
         ("Unit = session (turns and trials within a session are correlated); intervals are 95% session-bootstrap "
          "(pass^k: Wilson). pass@1 = mean over k trials of 'every turn exactly right'; pass^k = right in all k trials."), "",
         "| Model | Mode | n | Mean F1 | Turn exact | pass@1 | pass^k | Precision | Recall | Cites valid · relevant | Format err | Tools | $ |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in s["cells"]:
        cv = "–" if c["cite_valid"] is None else f"{c['cite_valid']:.0%} · {c['cite_relevant']:.0%}"
        L.append(f"| {c['model']} | {c['mode']} | {c['sessions']}×{c['k']} | {_ci(c['f1'])} | {_ci(c['turn_exact'], True)} | "
                 f"{_ci(c['pass1'], True)} | {_ci(c['pass_k'], True)} | {_ci(c['precision'])} | {_ci(c['recall'])} | {cv} | "
                 f"{c['format_err']:.0%} | {c['tool_calls']:.1f} | {c['cost']:.3f} |")
    L += ["", "## Paired comparisons (same sessions)", "",
          "| Model | A vs B | Metric | Δ (A − B) | 95% interval | P(Δ ≤ 0) |", "|---|---|---|---|---|---|"]
    for d in s["paired"]:
        L.append(f"| {d['model']} | {d['a']} vs {d['b']} | {d['metric']} | {d['diff']:+.2f} | [{d['lo']:+.2f}, {d['hi']:+.2f}] | {d['p_le0']:.3f} |")
    return "\n".join(L) + "\n"
