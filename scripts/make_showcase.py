"""Showcase: the same question answered from memory, with plain graph tools, and with the agentic harness.

    uv run python scripts/make_showcase.py OUT.html RUNS.json [RUNS.json ...]

Each RUNS.json is a list of guidance runs (cf.bench.guidance.run / run_agentic outputs) or an experiment result
(with "runs"). Cards are grouped by question. Entities that ONLY the grounded answers name (not in any closed-book
answer to the same question) are highlighted; the agentic column lists the findings the advice was built on.
"""

import json
import sys
from collections import defaultdict
from html import escape as E

from cf.agent.kg import KG
from cf.bench.guidance import _mentions, _names, _resolve

ORDER = {"closed_book": 0, "kg_tools": 1, "kg_agentic": 2}
LABEL = {"closed_book": "From memory", "kg_tools": "Graph tools (plain loop)", "kg_agentic": "Agentic harness (plan → research → read → notes)"}


def load(paths):
    runs = []
    for p in paths:
        d = json.load(open(p))
        runs += d["runs"] if isinstance(d, dict) and "runs" in d else (d if isinstance(d, list) else [d])
    return [r for r in runs if r.get("answer")]


def ents(kg, a):
    return {x for n in _names(a) + _mentions(kg, a) if (x := _resolve(kg, n))}


def col(kg, r, only, judge=None):
    a, m = r["answer"], r.get("metrics") or {}
    name = lambda n: (f'<b class="new">{E(n)}</b>' if _resolve(kg, n) in only else E(n))   # noqa: E731
    h = [f'<div class="col {r["condition"]}"><div class="head"><span class="mode">{E(LABEL[r["condition"]])}</span>'
         f'<span class="model">{E(r["model"].split("/")[-1])}</span></div>',
         f'<p class="sum">{E(a.get("summary") or "")}</p>', '<div class="lbl">Learn</div><ol>']
    h += [f"<li>{E(x)}</li>" for x in a.get("learn") or []] + ["</ol>", '<div class="lbl">Build</div>']
    for p in a.get("projects") or []:
        based = p.get("based_on")
        h.append(f'<div class="proj"><b>{E(p["title"])}</b>{" <span class=fb>built on findings " + ", ".join(str(i + 1) for i in based) + "</span>" if based else ""}'
                 f'<div>{E(p["what"])}</div><div class="chips">{"".join(f"<span>{name(s)}</span>" for s in p.get("stack") or [])}</div></div>')
    h.append('<div class="lbl">Experiments</div>')
    for e in a.get("experiments") or []:
        h.append(f'<div class="exp"><b>{E(e["question"])}</b><div>baseline: {E(e["baseline"])} · change: {E(e["change"])} · measure: {E(e["measure"])}</div></div>')
    if r.get("notes"):
        h.append('<div class="lbl">Findings it built on</div><ol class="find">')
        for f in r["notes"]:
            h.append(f'<li>{E(f["finding"])} <span class="cite">{len(f.get("edge_ids") or [])} cited edges</span></li>')
        h.append("</ol>")
    stats = [f'{m.get("in_kb", 0)} of {m.get("named", 0)} named items found in the graph']
    if m.get("salient_in_findings") is not None:
        stats.append(f'{round(m["salient_in_findings"] * 100)}% of the key organisations surfaced')
    if m.get("citations_valid"):
        stats.append(f'{m["citations_valid"]} valid citations')
    if r.get("steps"):
        stats.append(f'{len(r["steps"])} tool calls')
    stats.append(f'${r.get("cost_usd", 0):.3f}')
    h.append(f'<div class="stats">{" · ".join(E(s) for s in stats)}</div>')
    if judge is not None:
        h.append(f'<div class="judge">{E(judge)}</div>')
    return "".join(h) + "</div>"


def main(out, paths):
    runs = load(paths)
    kg = KG(version=runs[0]["kb_version"])
    by_q = defaultdict(list)
    for r in runs:
        by_q[r["question"]].append(r)
    cards = []
    for q, rs in by_q.items():
        rs.sort(key=lambda r: (ORDER[r["condition"]], "397" not in r["model"]))
        closed = set().union(*(ents(kg, r["answer"]) for r in rs if r["condition"] == "closed_book"))
        only = set().union(*(ents(kg, r["answer"]) for r in rs if r["condition"] != "closed_book")) - closed
        persona = rs[0].get("persona", "")
        found = []
        for r in rs:
            for f in r.get("notes") or []:
                for n in f.get("entities") or []:
                    x = _resolve(kg, n)
                    if x and x not in closed and kg.name(x) not in found:
                        found.append(kg.name(x))
        banner = (f'<div class="banner"><b>Surfaced only with the graph:</b> {E(", ".join(found[:14]))}</div>' if found else "")
        cards.append(f'<section class="card"><div class="persona">{E(persona.replace("_", " "))}</div><h2>“{E(q)}”</h2>{banner}'
                     f'<div class="grid">{"".join(col(kg, r, only) for r in rs)}</div>'
                     f'<p class="note">Bold names appear only in the grounded answers, not in any answer from memory. '
                     f'Every finding links to edges whose source quote and status (claimed, confirmed, corroborated, verified) '
                     f'can be opened in the explorer.</p></section>')
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Grounded Guidance Showcase</title><style>
:root{{--bg:#f8fafc;--card:#fff;--ink:#0f172a;--muted:#475569;--line:#e2e8f0;--accent:#2563eb;--new:#059669;--chip:#f1f5f9}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0f1419;--card:#161b22;--ink:#e6edf3;--muted:#9aa4b1;--line:#2b3139;--accent:#6ea8fe;--new:#34d399;--chip:#21262d}}}}
:root[data-theme="dark"]{{--bg:#0f1419;--card:#161b22;--ink:#e6edf3;--muted:#9aa4b1;--line:#2b3139;--accent:#6ea8fe;--new:#34d399;--chip:#21262d}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14.5px/1.5 Inter,system-ui,-apple-system,Segoe UI,sans-serif}}
.wrap{{max-width:1320px;margin:0 auto;padding:32px 16px}} h1{{font-size:28px;margin:0 0 6px}} .lead{{color:var(--muted);max-width:860px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px;margin:24px 0}}
.persona{{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}} h2{{font-size:18px;font-weight:600;margin:6px 0 16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}}
.col{{border:1px solid var(--line);border-radius:12px;padding:14px}} .col.kg_agentic{{border-color:var(--accent);border-width:2px}}
.head{{display:flex;justify-content:space-between;gap:8px;margin-bottom:6px}} .mode{{font-weight:700}} .model{{color:var(--muted);font-size:12.5px}}
.sum{{color:var(--muted)}} .lbl{{font-size:11.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:12px 0 4px}}
ol{{margin:0;padding-left:18px}} li{{margin:2px 0}} .proj,.exp{{margin:6px 0}} .proj>div,.exp>div{{color:var(--muted);font-size:13.5px}}
.chips span{{display:inline-block;background:var(--chip);border-radius:10px;padding:1px 8px;margin:3px 4px 0 0;font-size:12.5px}}
b.new{{color:var(--new)}} .fb{{font-size:11.5px;color:var(--accent);margin-left:6px}} .find li{{font-size:13.5px}} .cite{{color:var(--muted);font-size:12px}}
.stats{{margin-top:12px;padding-top:8px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px}} .note{{color:var(--muted);font-size:12.5px;margin-top:14px}}
.banner{{background:var(--chip);border-left:4px solid var(--new);border-radius:8px;padding:10px 12px;margin:0 0 14px}}
.judge{{margin-top:6px;font-size:12.5px;font-weight:600}} a{{color:var(--accent)}}
</style></head><body><div class="wrap">
<h1>Same question, three ways to answer it</h1>
<p class="lead">Each card shows one request answered by the same small model from memory, with plain graph tools, and with an agentic
harness that plans, researches the <a href="https://pracha.me/connected-frontiers/">Connected Frontiers</a> graph, reads the evidence,
writes findings, and builds its advice from them. A large model answering from memory is shown for comparison. Cases where grounding
did not help are included.</p>
{"".join(cards)}
</div></body></html>'''
    open(out, "w").write(html)
    print(out, len(cards), "cards")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
