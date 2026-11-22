"""Case-study poster for engineers: student · research engineer · forward-deployed engineer (KB v20261121-1821).

    python scripts/make_case_poster_engineers.py docs/case-study/poster-engineers.svg

Every finding is an answer Inkling-2-small gave with harness h3 on a held-out session (score 1.0, all
citations valid), and every quote is the stored evidence for the cited edge.
"""

import sys
from html import escape as E

W, H = 1080, 1350
INK, MUTED, LINE, BG = "#0F172A", "#475569", "#94A3B8", "#F8FAFC"
BLUE, ORANGE, VIOLET, GREEN = "#2563EB", "#EA580C", "#7C3AED", "#059669"
o: list[str] = []


def t(x, y, s, size=15, weight=400, fill=MUTED, anchor="start", style="", ls=0.0):
    extra = (f' font-style="{style}"' if style else "") + (f' letter-spacing="{ls}em"' if ls else "")
    o.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{extra}>{E(s)}</text>')


def card(y, h, color):
    o.append(f'<rect x="60" y="{y}" width="960" height="{h}" rx="18" fill="#FFFFFF" stroke="#E2E8F0" filter="url(#sh)"/>')
    o.append(f'<rect x="60" y="{y + 24}" width="5" height="{h - 48}" rx="2.5" fill="{color}"/>')


def chip(x, y, label, color):
    w = 7.2 * len(label) + 20
    o.append(f'<rect x="{x}" y="{y - 15}" width="{w}" height="22" rx="11" fill="{color}" fill-opacity="0.12"/>')
    t(x + w / 2, y + 1, label, 12, 700, color, "middle")
    return w


def evidence(x, y, edge, status, scolor, source):
    t(x, y, edge, 14.5, 600, INK)
    w = 8.4 * len(edge) + 22
    chip(x + w, y, status, scolor)
    t(x, y + 22, source, 13.5, 400, MUTED, style="italic")



o.append(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
t(60, 78, "CASE STUDY · CONNECTED FRONTIERS · FOR ENGINEERS", 14, 700, BLUE, ls=0.14)
t(60, 128, "Three engineering questions, answered from a graph", 38, 700, INK)
t(60, 164, "A small open model (Inkling-2-small) walked the knowledge graph with tools and cited every edge it used.", 17, 400, MUTED)
t(60, 188, "Each edge keeps its source quote and an evidence status: claimed, confirmed, corroborated or verified.", 17, 400, MUTED)

def bars(x, y, items, color):
    for i, (label, n) in enumerate(items):
        yy = y + i * 26
        t(x, yy + 4, label, 12.5, 600, INK)
        o.append(f'<rect x="{x + 112}" y="{yy - 9}" width="{n * 34}" height="16" rx="4" fill="{color}" fill-opacity="0.8"/>')
        t(x + 120 + n * 34, yy + 4, str(n), 12.5, 700, MUTED)

# ---- card 1: student -------------------------------------------------------------------------------------
y = 222
card(y, 330, GREEN)
t(96, y + 44, "STUDENT · WHAT AI WORK LOOKS LIKE INSIDE A PRODUCT COMPANY", 13, 700, GREEN, ls=0.12)
t(96, y + 72, "“Which roles is Figma hiring for around AI?”", 16.5, 400, MUTED, style="italic")
t(96, y + 114, "Figma lists 7 AI roles across research,", 24, 700, INK)
t(96, y + 144, "evaluation, design, engineering, product, sales.", 24, 700, INK)
evidence(96, y + 190, "Figma —hires_for→ Researcher, AI Evaluations", "claimed", ORANGE, "figma.com careers page")
evidence(96, y + 246, "Figma —hires_for→ Product Designer, AI Models", "claimed", ORANGE, "figma.com careers page · also: AI Applied Scientist, Software Engineer - AI Platforms")
t(96, y + 304, "Why it matters: AI work here spans evaluation, design and platform, not only research.", 15, 600, GREEN)
t(800, y + 172, "ROLES BY FUNCTION", 11, 700, MUTED, ls=0.1)
bars(800, y + 194, [("Research", 2), ("Engineering", 2), ("Product, design", 2), ("Sales", 1)], GREEN)

# ---- card 2: research engineer ---------------------------------------------------------------------------
y = 572
card(y, 330, VIOLET)
t(96, y + 44, "RESEARCH ENGINEER · LEARN A METHOD FROM PRACTICE", 13, 700, VIOLET, ls=0.12)
t(96, y + 72, "“What is fine-tuning related to, and which organisations use it in practice?”", 16.5, 400, MUTED, style="italic")
t(96, y + 114, "Four variants of fine-tuning in the graph, and", 24, 700, INK)
t(96, y + 144, "14 organisations using it, each with a source.", 24, 700, INK)
evidence(96, y + 190, "Notion —uses_method→ fine-tuning", "claimed", ORANGE,
         "fireworks.ai: “By partnering with Fireworks to fine-tune models, we reduced latency…”")
evidence(96, y + 246, "Thinking Machines Lab —uses_method→ fine-tuning", "claimed", ORANGE,
         "thinkingmachines.ai: “tools that enable everyone to fine-tune models” · missed: reinforcement fine-tuning")
t(96, y + 304, "Why it matters: sourced variants and real users beat a survey as a reading list.", 15, 600, VIOLET)
rx, ry = 895, y + 176
o.append(f'<rect x="{rx - 56}" y="{ry - 18}" width="112" height="28" rx="8" fill="{VIOLET}" fill-opacity="0.12" stroke="{VIOLET}" stroke-width="1.4"/>')
t(rx, ry + 1, "fine-tuning", 13, 700, VIOLET, "middle")
for i, name in enumerate(["SFT", "full", "full-parameter", "language-model"]):
    cx, cy = rx - 58 + (i % 2) * 116, ry + 46 + (i // 2) * 32
    o.append(f'<path d="M{rx} {ry + 10} L{cx} {cy - 13}" stroke="{LINE}" stroke-width="1.2" fill="none"/>')
    o.append(f'<rect x="{cx - 54}" y="{cy - 13}" width="108" height="24" rx="12" fill="#FFFFFF" stroke="{VIOLET}" stroke-width="1.1"/>')
    t(cx, cy + 4, name, 11.5, 700, INK, "middle")
t(rx, ry + 112, "+ 14 organisations use it", 12.5, 700, MUTED, "middle")

# ---- card 3: forward-deployed engineer -------------------------------------------------------------------
y = 922
card(y, 330, BLUE)
t(96, y + 44, "FORWARD-DEPLOYED ENGINEER · KNOW THE CUSTOMER’S STACK", 13, 700, BLUE, ls=0.12)
t(96, y + 72, "“Who works on autonomous driving, and which methods and technologies do they rely on?”", 16.5, 400, MUTED, style="italic")
t(96, y + 114, "Woven runs PyTorch with Hydra configs on", 24, 700, INK)
t(96, y + 144, "on-prem DGX plus AWS, tracked in W&B.", 24, 700, INK)
evidence(96, y + 190, "Woven —uses_tech→ DGX, AWS EC2, SageMaker", "claimed", ORANGE,
         "wandb.ai: “on-prem (DGX) … cloud (AWS EC2 and SageMaker) infrastructure”")
evidence(96, y + 246, "Woven —uses_method→ autolabeling", "claimed", ORANGE,
         "wandb.ai: “Autolabeling and dataset queries during the data curation workflow”")
t(96, y + 304, "Why it matters: knowing a customer’s tools, data workflow and infrastructure split before day one.", 15, 600, BLUE)
layers = [("Tracking", "Weights & Biases"), ("Framework", "PyTorch + Hydra"), ("Data", "autolabeling"), ("Compute", "DGX + AWS")]
for i, (k, v) in enumerate(layers):
    yy = y + 164 + i * 32
    o.append(f'<rect x="790" y="{yy}" width="210" height="26" rx="6" fill="{BLUE}" fill-opacity="{0.06 + 0.05 * i}" stroke="{BLUE}" stroke-opacity="0.4"/>')
    t(800, yy + 17, k.upper(), 10.5, 700, BLUE, ls=0.08)
    t(990, yy + 17, v, 12, 600, INK, "end")

t(60, 1290, "On 14 held-out sessions: 0.94 answer F1 with the graph, 0.10 from memory · Inkling-2-small · harness h3", 14.5, 700, INK)
t(60, 1314, "Findings are what the graph holds, not audited facts.   Explore: pracha.me/connected-frontiers   ·   Code: github.com/prabakaranc98/connected-frontiers", 13, 400, MUTED)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Inter, system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif">
<title>Three engineering questions answered from the Connected Frontiers graph: student, research engineer, forward-deployed engineer</title>
<defs><filter id="sh" x="-5%" y="-5%" width="110%" height="115%"><feDropShadow dx="0" dy="2" stdDeviation="7" flood-color="#0F172A" flood-opacity="0.07"/></filter></defs>
{chr(10).join(o)}
</svg>
'''
out = sys.argv[1] if len(sys.argv) > 1 else "docs/case-study/poster-engineers.svg"
import pathlib
pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(out).write_text(svg)
print(out)
