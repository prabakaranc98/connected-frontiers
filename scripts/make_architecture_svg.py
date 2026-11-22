"""Generate docs/architecture.svg: the system as built (v0.1), planned parts dashed.

    python scripts/make_architecture_svg.py docs/architecture.svg

Grid of 8 px; each box states one thing (a label and at most one hint).
"""

import sys
from html import escape as E

W, H = 1400, 960
INK, MUTED, LINE, BG = "#0F172A", "#64748B", "#94A3B8", "#F8FAFC"
C = {"con": "#2563EB", "kb": "#059669", "rea": "#EA580C", "exa": "#7C3AED", "eva": "#DB2777", "lab": "#0891B2", "app": "#475569"}
o: list[str] = []
_n = [0]


def t(x, y, s, size=12, weight=400, fill=MUTED, anchor="start", ls=0.0):
    extra = f' letter-spacing="{ls}em"' if ls else ""
    o.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{extra}>{E(s)}</text>')


def card(x, y, w, h, color, role, title):
    _n[0] += 1
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="#FFFFFF" stroke="#E2E8F0" filter="url(#sh)"/>')
    o.append(f'<clipPath id="c{_n[0]}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16"/></clipPath>')
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="4" fill="{color}" clip-path="url(#c{_n[0]})"/>')
    o.append(f'<circle cx="{x + 29}" cy="{y + 30}" r="5" fill="{color}"/>')
    t(x + 42, y + 34, role, 11.5, 700, color, ls=0.14)
    t(x + 24, y + 60, title, 18, 700, INK)


def pill(x, y, w, h, label, hint, color, dashed=False, strong=False, n=None):
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    op = "0.14" if strong else "0.06"
    sw = "2" if strong else "1"
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{color}" fill-opacity="{op}" stroke="{color}" '
             f'stroke-opacity="{0.9 if strong else 0.35}" stroke-width="{sw}"{dash}/>')
    tx = x + 14
    if n is not None:
        o.append(f'<circle cx="{x + 20}" cy="{y + h / 2}" r="10" fill="{color}"/>')
        t(x + 20, y + h / 2 + 4, str(n), 10.5, 700, "#FFFFFF", "middle")
        tx = x + 38
    if hint:
        t(tx, y + h / 2 - 2, label, 13, 600, INK)
        t(tx, y + h / 2 + 13, hint, 11, 400, MUTED)
    else:
        t(tx, y + h / 2 + 4, label, 13, 600, INK)
    if dashed:
        t(x + w - 10, y + 15, "planned", 10, 700, color, "end", 0.08)


def arrow(d, color=LINE, dashed=False, marker="a"):
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    o.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.6"{dash} marker-end="url(#{marker})"/>')


def flow(pts, color=LINE, marker="a", r=10):
    """Polyline with rounded corners and an arrowhead; pts = [(x, y), ...] with axis-aligned segments."""
    d = f"M{pts[0][0]},{pts[0][1]}"
    for (x0, y0), (x1, y1), (x2, y2) in zip(pts, pts[1:], pts[2:], strict=False):
        dx1, dy1 = (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0)
        dx2, dy2 = (x2 > x1) - (x2 < x1), (y2 > y1) - (y2 < y1)
        d += f" L{x1 - dx1 * r},{y1 - dy1 * r} Q{x1},{y1} {x1 + dx2 * r},{y1 + dy2 * r}"
    d += f" L{pts[-1][0]},{pts[-1][1]}"
    o.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" marker-end="url(#{marker})"/>')


def tag(x, y, s, color=MUTED):
    w = 6.6 * len(s) + 18
    o.append(f'<rect x="{x - w / 2}" y="{y - 11}" width="{w}" height="22" rx="11" fill="#FFFFFF" stroke="#E2E8F0"/>')
    t(x, y + 4, s, 10.5, 600, color, "middle")


o.append(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
t(48, 50, "Connected Frontiers · architecture (v0.1, as built)", 24, 700, INK)
t(48, 74, "A versioned knowledge base of the AI ecosystem, built by curation, used by agents, and measured by a testbed. Dashed = planned.", 13.5, 400, MUTED)

# ---- row A: Constructor → KB → Reasoner ------------------------------------------------------------------
card(48, 104, 330, 420, C["con"], "CONSTRUCTOR", "Curation")
for i, (lab, hint) in enumerate([("Crawl", "personalized-PageRank frontier"), ("Clean and gate", "noise · near-duplicates · metric nodes"),
                                 ("Extract", "typed claims with verbatim quotes"), ("Verify and grade", "second opinion · claimed → verified"),
                                 ("Resolve entities", "merge · part-of · subtype-of")]):
    pill(72, 180 + i * 56, 282, 46, lab, hint, C["con"], n=i + 1)
    if i:
        arrow(f"M213,{180 + i * 56 - 10} V{180 + i * 56 - 1}")
pill(72, 466, 282, 46, "Hugging Face adapter", "119 orgs · models · datasets · lineage", C["app"])

card(418, 164, 262, 300, C["kb"], "KNOWLEDGE BASE", "Versioned KB")
for i, (lab, hint) in enumerate([("Graph", "entities · typed edges"), ("Evidence", "quote · source · status"), ("Passages", "GraphRAG index")]):
    pill(442, 244 + i * 58, 214, 48, lab, hint, C["kb"])
t(549, 440, "one version per build · diffable", 11, 400, MUTED, "middle")
arrow("M378,314 H416")
tag(397, 300, "snapshot")

card(720, 104, 632, 420, C["rea"], "REASONER", "Inference · the agent")
t(744, 190, "CONDITIONS", 10.5, 700, MUTED, ls=0.12)
pill(744, 200, 250, 42, "Closed book", "memory only (baseline)", C["rea"])
pill(744, 250, 250, 42, "GraphRAG", "one-shot PPR + BM25 passages", C["rea"])
pill(744, 300, 250, 42, "Plain tools", "free tool loop over the graph", C["rea"])
pill(744, 350, 250, 50, "Agentic harness", "plan → research → read → notes → advise", C["rea"], strong=True)
pill(744, 408, 250, 42, "Oracle", "gold evidence · upper bound", C["rea"])
t(1018, 190, "AGENTIC HARNESS", 10.5, 700, MUTED, ls=0.12)
steps = [("Plan", "4-6 sub-questions"), ("Research", "multi-step graph tools"), ("Read evidence", "gate: must read sources"),
         ("Notes", "findings + edges + implication"), ("Advise", "built on findings")]
for i, (lab, hint) in enumerate(steps):
    pill(1018, 200 + i * 52, 310, 42, lab, hint, C["rea"], n=i + 1)
    if i:
        arrow(f"M1173,{200 + i * 52 - 10} V{200 + i * 52 - 1}")
t(744, 478, "Gates: evidence read · coverage reflection · synthesis check", 11.5, 600, C["rea"])
t(744, 498, "Harness: schema card · empty-result hints · truncation notices · findings-linked advice", 11, 400, MUTED)
arrow("M680,284 H718")
tag(699, 270, "tools")

# ---- row B: Applications · Examiner · Evaluator · Testbed ------------------------------------------------
Y0, HB = 568, 300
card(48, Y0, 300, HB, C["app"], "APPLICATIONS", "For people")
for k, (lab, hint) in enumerate([("Explorer", "pracha.me/connected-frontiers"), ("cf advise", "grounded guidance, cited"),
                                 ("Showcase", "same question, three ways"), ("Hugging Face release", "kg · bench · runs · labels")]):
    pill(72, 648 + k * 52, 252, 44, lab, hint, C["app"])

card(380, Y0, 300, HB, C["exa"], "EXAMINER", "Task curation")
pill(404, 648, 252, 56, "QA sessions", "keys computed on the graph · solver gate", C["exa"])
pill(404, 714, 252, 56, "Agency tasks", "8 personas · rich/thin · curated", C["exa"])
t(404, 808, "Families kept apart: Gemma curates,", 11, 400, MUTED)
t(404, 824, "others are tested and judge.", 11, 400, MUTED)

card(712, Y0, 312, HB, C["eva"], "EVALUATOR", "Measurement")
for k, (lab, hint) in enumerate([("Deterministic", "F1 · precision · recall · citations"), ("Truth (silver)", "4 judges re-read the cited page"),
                                 ("LLM judges", "persona + expert · both orders"), ("Judge unit tests", "perturbations must lower scores")]):
    pill(736, 648 + k * 52, 264, 44, lab, hint, C["eva"])

card(1056, Y0, 296, HB, C["lab"], "TESTBED", "Experiments")
for k, (lab, hint) in enumerate([("Experiments as YAML", "personas · models · conditions"), ("Answer cache", "re-judge without re-paying"),
                                 ("Ledger", "every result, with corrections"), ("Meta loop", "diagnose → propose → held-out")]):
    pill(1080, 648 + k * 52, 248, 44, lab, hint, C["lab"])

# ---- flows (short, non-crossing) ---------------------------------------------------------------------------------
flow([(530, 464), (530, 566)], C["exa"], "ax")
tag(530, 512, "graph algorithms", C["exa"])
flow([(470, 464), (470, 546), (198, 546), (198, 566)], C["app"], "ap")
tag(330, 546, "versions", C["app"])
flow([(640, 568), (640, 546), (800, 546), (800, 526)], C["exa"], "ax")
tag(720, 546, "tasks", C["exa"])
flow([(900, 524), (900, 566)], C["rea"], "ar")
tag(900, 546, "answers · trajectories", C["rea"])
flow([(1024, 718), (1054, 718)], C["eva"], "ae")
flow([(1204, 568), (1204, 526)], C["lab"], "al")
tag(1204, 546, "promoted harness", C["lab"])
flow([(1036, 104), (1036, 88), (213, 88), (213, 102)], C["rea"], "ar")
o.pop()
o.append('<path d="M1036,104 L1036,98 Q1036,88 1026,88 L223,88 Q213,88 213,98 L213,102" fill="none" stroke="' + C["rea"]
         + '" stroke-width="1.6" stroke-dasharray="6 5" marker-end="url(#ar)"/>')
tag(624, 88, "gaps → targeted crawl · planned", C["rea"])

t(48, 918, "Every stage cached and resumable · trust is a status on each edge, not a hard gate · results logged with corrections", 12, 400, MUTED)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Inter, system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif">
<title>Connected Frontiers architecture: Constructor, knowledge base, Reasoner with agentic harness, Examiner, Evaluator, Testbed, applications</title>
<defs>
  <filter id="sh" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="6" flood-color="#0F172A" flood-opacity="0.06"/></filter>
  <marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{LINE}"/></marker>
  <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{C['rea']}"/></marker>
  <marker id="ax" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{C['exa']}"/></marker>
  <marker id="ae" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{C['eva']}"/></marker>
  <marker id="ap" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{C['app']}"/></marker>
  <marker id="al" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{C['lab']}"/></marker>
</defs>
{chr(10).join(o)}
</svg>
'''
open(sys.argv[1] if len(sys.argv) > 1 else "docs/architecture.svg", "w").write(svg)
