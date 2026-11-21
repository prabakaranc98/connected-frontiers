"""Generate docs/architecture.svg: three roles around one versioned knowledge base.

    python scripts/make_architecture_svg.py docs/architecture.svg

Layout is on an 8 px grid; every element states one thing (a label and at most one hint).
"""

import sys
from html import escape as E

W, H = 1400, 868
INK, MUTED, LINE, BG = "#0F172A", "#64748B", "#94A3B8", "#F8FAFC"
ROLE = {"con": "#2563EB", "rea": "#EA580C", "exa": "#7C3AED", "kb": "#059669", "out": "#475569"}
o: list[str] = []
_clip = [0]


def t(x, y, s, size=12, weight=400, fill=MUTED, anchor="start", ls=0.0):
    o.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"'
             f'{f" letter-spacing={chr(34)}{ls}em{chr(34)}" if ls else ""}>{E(s)}</text>')


def card(x, y, w, h, accent=None):
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="#FFFFFF" stroke="#E2E8F0" filter="url(#shadow)"/>')
    if accent:                                   # accent clipped to the card's rounded top
        _clip[0] += 1
        o.append(f'<clipPath id="c{_clip[0]}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16"/></clipPath>')
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="4" fill="{accent}" clip-path="url(#c{_clip[0]})"/>')


def header(x, y, role, tag, color):
    o.append(f'<circle cx="{x + 5}" cy="{y - 4}" r="5" fill="{color}"/>')
    t(x + 18, y, role, 11.5, 700, color, ls=0.14)
    t(x, y + 26, tag, 19, 700, INK)


def step(x, y, w, h, n, label, hint, color, dashed=False, badge=True):
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{color}" fill-opacity="0.06" '
             f'stroke="{color}" stroke-opacity="0.35"{dash}/>')
    tx = x + 16
    if badge:
        o.append(f'<circle cx="{x + 22}" cy="{y + h / 2}" r="11" fill="{color}"/>')
        t(x + 22, y + h / 2 + 4, str(n), 11, 700, "#FFFFFF", "middle")
        tx = x + 44
    t(tx, y + h / 2 - 3, label, 14, 600, INK)
    t(tx, y + h / 2 + 14, hint, 12, 400, MUTED)
    if dashed:
        t(x + w - 12, y + 18, "planned", 10.5, 700, color, "end", 0.08)


def arrow(d, color=LINE, dashed=False, marker="arr"):
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    o.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.6"{dash} marker-end="url(#{marker})"/>')


def tag(x, y, s, color=MUTED):
    w = 7 * len(s) + 18
    o.append(f'<rect x="{x - w / 2}" y="{y - 11}" width="{w}" height="22" rx="11" fill="#FFFFFF" stroke="#E2E8F0"/>')
    t(x, y + 4, s, 11, 600, color, "middle")


# ---- canvas and title -----------------------------------------------------------------------------
o.append(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
t(48, 50, "Connected Frontiers", 24, 700, INK)
t(48, 74, "Three roles around one versioned knowledge base", 14, 400, MUTED)

# ---- planned feedback loop (drawn first, under the cards) ----------------------------------------
arrow("M1087,120 V100 H213 V118", ROLE["rea"], dashed=True, marker="arrO")
tag(650, 100, "gaps → targeted crawl · planned", ROLE["rea"])

# ---- CONSTRUCTOR ------------------------------------------------------------------------------------
card(48, 120, 330, 560, ROLE["con"])
header(72, 156, "CONSTRUCTOR", "Curation", ROLE["con"])
steps = [("Crawl", "PPR-prioritised frontier"), ("Clean & gate", "noise · duplicates · metrics"),
         ("Extract", "typed triples with quotes"), ("Verify", "quote-checked · second opinion"),
         ("Grade & resolve", "claimed → verified · merges")]
for i, (lab, hint) in enumerate(steps):
    y = 200 + i * 76
    step(72, y, 282, 64, i + 1, lab, hint, ROLE["con"])
    if i:
        arrow(f"M213,{y - 12} V{y - 2}")
step(72, 600, 282, 56, 0, "Structured adapters", "Hugging Face Hub lineage", ROLE["out"], badge=False)

# ---- KNOWLEDGE BASE (hero) --------------------------------------------------------------------------
card(450, 240, 300, 312, ROLE["kb"])
cx = 600                                                    # database glyph
for dy in (0, 9, 18):
    o.append(f'<ellipse cx="{cx}" cy="{282 + dy}" rx="18" ry="6" fill="#FFFFFF" stroke="{ROLE["kb"]}" stroke-width="1.6"/>')
o.append(f'<path d="M{cx - 18},282 V300 M{cx + 18},282 V300" stroke="{ROLE["kb"]}" stroke-width="1.6"/>')
t(cx, 334, "Knowledge Base", 19, 700, INK, "middle")
t(cx, 354, "versioned snapshot · vN", 12, 400, MUTED, "middle")
for i, (lab, hint) in enumerate([("Graph", "entities · typed edges"), ("Evidence", "quotes · status · strength"),
                                 ("Passages", "GraphRAG index")]):
    step(474, 372 + i * 52, 252, 44, 0, lab, hint, ROLE["kb"], badge=False)
t(cx, 540, "diffable · pinned by every task", 11.5, 400, MUTED, "middle")

arrow("M378,400 H448")
tag(414, 400, "snapshot")

# ---- REASONER ---------------------------------------------------------------------------------------
card(822, 120, 530, 330, ROLE["rea"])
header(846, 156, "REASONER", "Inference", ROLE["rea"])
modes = [("Closed book", "memory only", False), ("GraphRAG", "seeds → PPR → passages", False),
         ("KG tools", "step-by-step graph walk", False), ("Graph query", "one typed path query", True),
         ("Oracle", "gold subgraph · upper bound", False)]
for i, (lab, hint, d) in enumerate(modes):
    step(846, 216 + i * 44, 250, 38, 0, lab, hint, ROLE["rea"], dashed=d, badge=False)
t(846, 206, "RETRIEVAL MODE", 10.5, 700, MUTED, ls=0.12)
card(1124, 246, 204, 156)
t(1144, 276, "Cited answer", 15, 700, INK)
for i, s in enumerate(["edge-id citations", "status-aware wording", "abstains when absent", "per turn, multi-turn"]):
    o.append(f'<circle cx="{1150}" cy="{300 + i * 24}" r="7" fill="{ROLE["rea"]}" fill-opacity="0.15"/>')
    o.append(f'<path d="M1146.5,{300 + i * 24} l2.5,2.5 l4.5,-5" fill="none" stroke="{ROLE["rea"]}" stroke-width="1.6"/>')
    t(1164, 304 + i * 24, s, 12, 400, INK)
arrow("M1096,324 H1122")

arrow("M750,300 H820")
tag(786, 300, "retrieve")

# ---- EXAMINER ---------------------------------------------------------------------------------------
card(822, 490, 530, 190, ROLE["exa"])
header(846, 526, "EXAMINER", "Task builder", ROLE["exa"])
ex = [("Generate", "graph keys"), ("Write", "LLM turns"), ("Check", "ids · no leaks"), ("Gate", "solver ≥ 0.6")]
for i, (lab, hint) in enumerate(ex):
    x = 846 + i * 122
    o.append(f'<rect x="{x}" y="572" width="110" height="72" rx="10" fill="{ROLE["exa"]}" fill-opacity="0.06" '
             f'stroke="{ROLE["exa"]}" stroke-opacity="0.35"/>')
    o.append(f'<circle cx="{x + 18}" cy="592" r="9" fill="{ROLE["exa"]}"/>')
    t(x + 18, 596, str(i + 1), 10, 700, "#FFFFFF", "middle")
    t(x + 14, 620, lab, 14, 600, INK)
    t(x + 14, 636, hint, 11.5, 400, MUTED)
    if i:
        arrow(f"M{x - 12},608 H{x - 2}")

arrow("M750,500 H786 V585 H820")
tag(786, 540, "compute keys")
arrow("M960,490 V452", ROLE["exa"], marker="arrV")
tag(1012, 471, "sessions", ROLE["exa"])
arrow("M1240,452 V488", ROLE["rea"], marker="arrO")
tag(1170, 471, "trajectories → scores", ROLE["rea"])

# ---- OUTPUTS ----------------------------------------------------------------------------------------
o.append(f'<path d="M600,552 V704 M213,704 H1087 M1087,680 V704" fill="none" stroke="{LINE}" stroke-width="1.6"/>')
for x in (213, 600, 1087):
    arrow(f"M{x},704 V718")
outs = [(48, 330, "Explorer", "Map › Segment › Entity"), (450, 300, "Observability", "traces · live monitor · silver labels"),
        (822, 530, "Hugging Face release", "kg · bench · runs · labels — private until approved")]
for x, w, lab, hint in outs:
    card(x, 720, w, 84)
    o.append(f'<rect x="{x + 20}" y="742" width="4" height="40" rx="2" fill="{ROLE["out"]}"/>')
    t(x + 38, 758, lab, 15, 700, INK)
    t(x + 38, 778, hint, 12, 400, MUTED)

t(48, 842, "Every stage is cached and resumable · dashed = planned", 12, 400, MUTED)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Inter, system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif">
<title>Connected Frontiers architecture: Constructor, Examiner and Reasoner around a versioned knowledge base</title>
<defs>
  <filter id="shadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="6" flood-color="#0F172A" flood-opacity="0.06"/></filter>
  <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{LINE}"/></marker>
  <marker id="arrO" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{ROLE['rea']}"/></marker>
  <marker id="arrV" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{ROLE['exa']}"/></marker>
</defs>
{chr(10).join(o)}
</svg>
'''
open(sys.argv[1] if len(sys.argv) > 1 else "docs/architecture.svg", "w").write(svg)
