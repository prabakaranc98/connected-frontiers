"""Case-study poster: what a small model found by walking the graph (KB v20261121-1821).

    python scripts/make_case_poster.py docs/case-study/poster.svg

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
# ---- header -----------------------------------------------------------------------------------------
t(60, 78, "CASE STUDY · CONNECTED FRONTIERS", 14, 700, BLUE, ls=0.14)
t(60, 128, "What a small model found by walking the graph", 40, 700, INK)
t(60, 164, "Inkling-2-small answered multi-turn questions with graph tools. Every answer cites the edges it used;", 17, 400, MUTED)
t(60, 188, "each edge keeps its source quote and an evidence status: claimed, confirmed, corroborated or verified.", 17, 400, MUTED)

# ---- card A: investor view ------------------------------------------------------------------------------
y = 222
card(y, 330, BLUE)
t(96, y + 44, "INVESTOR VIEW · TRACTION CLAIMS", 13, 700, BLUE, ls=0.12)
t(96, y + 72, "“Which customers does OpenRouter say it serves, and how well is each claim evidenced?”", 16.5, 400, MUTED, style="italic")
t(96, y + 114, "All 12 customer claims come from OpenRouter’s own site,", 24, 700, INK)
t(96, y + 144, "and 8 of the 12 rest on nothing more than a logo.", 24, 700, INK)
evidence(96, y + 190, "OpenRouter —serves→ Prime Intellect", "claimed", ORANGE,
         "openrouter.ai: “grew 100x on OpenRouter and cut its cost per token by 60%”")
evidence(96, y + 246, "OpenRouter —serves→ Lovable", "claimed", ORANGE,
         "openrouter.ai: “Lovable logo” · also claimed by Baseten, Cerebras, Cloudflare, Fireworks AI")
t(96, y + 304, "Why it matters: a logo wall and a confirmed customer are different kinds of evidence.", 15, 600, BLUE)
# 12 claims: 4 case studies, 8 logos
gx, gy = 800, y + 182
for i in range(12):
    cx, cy = gx + (i % 6) * 32, gy + (i // 6) * 32
    case = i < 4
    o.append(f'<rect x="{cx}" y="{cy}" width="24" height="24" rx="5" fill="{BLUE if case else "none"}" '
             f'fill-opacity="{0.85 if case else 1}" stroke="{BLUE}" stroke-width="1.5"/>')
t(800, gy + 86, "■ 4 case studies with numbers", 13, 600, INK)
t(800, gy + 106, "□ 8 logo-only claims", 13, 600, MUTED)

# ---- card B: founder view -------------------------------------------------------------------------------
y = 572
card(y, 330, ORANGE)
t(96, y + 44, "FOUNDER VIEW · AN UNMEASURED CATEGORY", 13, 700, ORANGE, ls=0.12)
t(96, y + 72, "“Which companies work on AI customer-service agents, and which benchmarks do they report?”", 16.5, 400, MUTED, style="italic")
t(96, y + 114, "Three companies work on it: Sierra, Decagon and Ada.", 24, 700, INK)
t(96, y + 144, "None of them reports a benchmark in the graph.", 24, 700, INK)
evidence(96, y + 190, "Sierra —works_on→ AI customer-service agents", "claimed", ORANGE,
         "braintrust.dev: “a standalone platform for building branded customer-experience agents”")
evidence(96, y + 246, "Decagon AI, Ada —works_on→ the same problem", "claimed", ORANGE,
         "the same source for all three: an evaluation vendor’s page, not the companies’ own")
t(96, y + 304, "Why it matters: products without a shared public benchmark point to an opening in evaluation.", 15, 600, ORANGE)
# mini graph: three orgs -> problem -> benchmarks 0
bx = 790
for i, name in enumerate(["Sierra", "Decagon AI", "Ada"]):
    yy = y + 168 + i * 34
    o.append(f'<rect x="{bx}" y="{yy - 15}" width="96" height="24" rx="12" fill="{ORANGE}" fill-opacity="0.12"/>')
    t(bx + 48, yy + 2, name, 12.5, 700, ORANGE, "middle")
    o.append(f'<path d="M{bx + 96} {yy - 3} L{bx + 128} {y + 201}" stroke="{LINE}" stroke-width="1.4" fill="none"/>')
o.append(f'<rect x="{bx + 128}" y="{y + 186}" width="68" height="30" rx="8" fill="#FFFFFF" stroke="{INK}" stroke-width="1.4"/>')
t(bx + 162, y + 205, "CX agents", 11.5, 700, INK, "middle")
o.append(f'<path d="M{bx + 162} {y + 216} V{y + 250}" stroke="{LINE}" stroke-width="1.4" stroke-dasharray="4 4"/>')
o.append(f'<rect x="{bx + 112}" y="{y + 250}" width="100" height="28" rx="8" fill="none" stroke="{LINE}" stroke-dasharray="4 4"/>')
t(bx + 162, y + 268, "benchmarks: 0", 12, 700, MUTED, "middle")

# ---- card C: learner view -------------------------------------------------------------------------------
y = 922
card(y, 330, VIOLET)
t(96, y + 44, "LEARNER VIEW · THREE HOPS OF LINEAGE", 13, 700, VIOLET, ls=0.12)
t(96, y + 72, "“What is MuZero built on, who offers that base, and what else is built on it?”", 16.5, 400, MUTED, style="italic")
t(96, y + 114, "MuZero builds on AlphaGo, which Google DeepMind offers;", 24, 700, INK)
t(96, y + 144, "AlphaZero and AlphaDev build on the same base.", 24, 700, INK)
evidence(96, y + 190, "MuZero —builds_on→ AlphaGo", "claimed", ORANGE,
         "deepmind.google: “AlphaZero, MuZero, and AlphaDev — are building upon AlphaGo’s legacy”")
evidence(96, y + 246, "Google DeepMind —offers→ AlphaGo", "corroborated", BLUE,
         "two independent publishers agree")
t(96, y + 304, "Why it matters: three linked questions, answered in one conversation, each step cited.", 15, 600, VIOLET)
# mini tree
rx, ry = 840, y + 176
o.append(f'<rect x="{rx - 52}" y="{ry - 18}" width="104" height="28" rx="8" fill="{VIOLET}" fill-opacity="0.12" stroke="{VIOLET}" stroke-width="1.4"/>')
t(rx, ry + 1, "AlphaGo", 13, 700, VIOLET, "middle")
t(rx, ry - 30, "Google DeepMind", 12, 700, MUTED, "middle")
o.append(f'<path d="M{rx} {ry - 26} V{ry - 18}" stroke="{LINE}" stroke-width="1.4"/>')
for i, name in enumerate(["MuZero", "AlphaZero", "AlphaDev"]):
    cx = rx - 100 + i * 100
    o.append(f'<path d="M{rx} {ry + 10} L{cx} {ry + 58}" stroke="{LINE}" stroke-width="1.4" fill="none"/>')
    o.append(f'<rect x="{cx - 44}" y="{ry + 58}" width="88" height="26" rx="13" fill="#FFFFFF" stroke="{VIOLET}" stroke-width="1.2"/>')
    t(cx, ry + 76, name, 12, 700, INK, "middle")

# ---- footer -------------------------------------------------------------------------------------------
t(60, 1290, "On 14 held-out sessions: 0.94 answer F1 with the graph, 0.10 from memory · Inkling-2-small · harness h3", 14.5, 700, INK)
t(60, 1314, "Findings are what the graph holds, not audited facts.   Explore: pracha.me/connected-frontiers   ·   Code: github.com/prabakaranc98/connected-frontiers", 13, 400, MUTED)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Inter, system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif">
<title>What a small model found by walking the graph: three case studies from Connected Frontiers</title>
<defs><filter id="sh" x="-5%" y="-5%" width="110%" height="115%"><feDropShadow dx="0" dy="2" stdDeviation="7" flood-color="#0F172A" flood-opacity="0.07"/></filter></defs>
{chr(10).join(o)}
</svg>
'''
out = sys.argv[1] if len(sys.argv) > 1 else "docs/case-study/poster.svg"
import pathlib
pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(out).write_text(svg)
print(out)
