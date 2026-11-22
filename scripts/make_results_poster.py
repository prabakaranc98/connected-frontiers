"""Results poster (SVG + PNG) from the use-case runs: judge preferences, the retrieval → grounding → use funnel,
object retrieval by type, and real examples of what the graph changed (including a failure).

    uv run python scripts/make_results_poster.py USECASES_RUN_DIR [OBJECTS_RUN_DIR]

Every number is read from the run folders (pairwise.jsonl, stages.jsonl, bias_check.jsonl, runs.jsonl).
Writes docs/posters/grounding-results.svg and .png (PNG via headless Chrome when available).
"""

import json
import subprocess
import sys
from html import escape as E
from pathlib import Path

from cf.eval.stats import bootstrap

W, H = 1400, 1100
INK, MUTED, LINE, BG, CARD = "#0f172a", "#475569", "#e2e8f0", "#f8fafc", "#ffffff"
ACCENT, ACCENT2, GREY = "#2563eb", "#0d9488", "#94a3b8"
MAIN = "thinkingmachines/inkling-2-small"


def jl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().split("\n") if x.strip()] if p.exists() else []


def text(x, y, s, size=14, color=INK, weight=400, anchor="start"):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{E(str(s))}</text>'


def wrap(s: str, n: int) -> list[str]:
    out, cur = [], ""
    for w in s.split():
        if len(cur) + len(w) + 1 > n:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return out + ([cur] if cur else [])


def card(x, y, w, h, title, sub=""):
    s = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{CARD}" stroke="{LINE}"/>', text(x + 20, y + 32, title, 17, INK, 700)]
    if sub:
        s.append(text(x + 20, y + 52, sub, 12.5, MUTED))
    return s


def prefs_panel(x, y, w, h, run: Path):
    pw = jl(run / "pairwise.jsonl")
    bc = jl(run / "bias_check.jsonl")
    rows = [("memory-first vs memory", "Memory-first vs memory"), ("agentic vs memory", "Agentic vs memory"),
            ("small memory-first vs large memory", "Small (memory-first) vs 397B (memory)"),
            ("memory-first vs agentic", "Memory-first vs agentic"), ("agentic vs typical RAG", "Agentic vs typical GraphRAG")]
    series = [("GLM judge", ACCENT, lambda c: [p["p_x"] for p in pw if p["comparison"] == c])]
    if bc:
        series += [("Nemotron judge", ACCENT2, lambda c: [r["p_x"] for r in bc if r["comparison"] == c and r["check"] == "nemotron"]),
                   ("GLM, length-matched", GREY, lambda c: [r["p_x"] for r in bc if r["comparison"] == c and r["check"].startswith("length")])]
    s = card(x, y, w, h, "Which answer do judges prefer?", "P(first answer preferred) · both orders × persona and expert roles · 95% interval · 0.5 = no preference")
    x0, x1 = x + 300, x + w - 40
    sx = lambda v: x0 + (x1 - x0) * v
    top = y + 100
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        s.append(f'<line x1="{sx(v):.1f}" y1="{top - 6}" x2="{sx(v):.1f}" y2="{y + h - 40}" stroke="{LINE if v != 0.5 else MUTED}" '
                 f'stroke-dasharray="{"" if v != 0.5 else "4 4"}"/>')
        s.append(text(sx(v), y + h - 22, f"{v:.2f}", 11.5, MUTED, anchor="middle"))
    band = (h - 140) / len(rows)
    for i, (key, label) in enumerate(rows):
        cy = top + i * band + 10
        s.append(text(x + 20, cy + 14, label, 13.5, INK, 600))
        k = 0
        for name, col, get in series:
            vals = get(key)
            if not vals:
                continue
            m, lo, hi = bootstrap(vals)
            yy = cy + k * 13
            s.append(f'<line x1="{sx(lo):.1f}" y1="{yy + 5}" x2="{sx(hi):.1f}" y2="{yy + 5}" stroke="{col}" stroke-width="2"/>')
            s.append(f'<circle cx="{sx(m):.1f}" cy="{yy + 5}" r="5" fill="{col}"/>')
            if sx(hi) + 40 > x1:                                    # no room right of the interval: label on the left
                s.append(text(sx(lo) - 8, yy + 9, f"{m:.2f}", 11.5, col, 700, "end"))
            else:
                s.append(text(sx(hi) + 8, yy + 9, f"{m:.2f}", 11.5, col, 700))
            k += 1
    lx = x + 20
    for name, col, _ in series:
        s += [f'<circle cx="{lx + 5}" cy="{y + 70}" r="5" fill="{col}"/>', text(lx + 15, y + 74, name, 12, MUTED)]
        lx += 150
    return s


def funnel_panel(x, y, w, h, run: Path):
    st = [r for r in jl(run / "stages.jsonl") if r["model"] == MAIN]
    conds = [("closed_book", "Memory"), ("kg_rag", "Typical GraphRAG"), ("kg_agentic", "Agentic"), ("kg_enrich", "Memory-first")]
    stages = [("retrieved", "retrieved", "#bfdbfe"), ("grounded", "grounded", "#60a5fa"), ("used", "used in answer", ACCENT)]
    s = card(x, y, w, h, "Where the graph's facts go", "Share of the question's gold facts · Inkling-2-small · mean over tasks and 3 trials")
    base, top = y + h - 50, y + 80
    gw = (w - 60) / len(conds)
    for i, (c, label) in enumerate(conds):
        xs = [r for r in st if r["condition"] == c]
        gx = x + 30 + i * gw
        for j, (k, _, col) in enumerate(stages):
            vals = [r[k] for r in xs if r.get(k) is not None]
            v = sum(vals) / len(vals) if vals else 0
            bx, bw = gx + 10 + j * (gw - 30) / 3, (gw - 30) / 3 - 6
            bh = (base - top) * v
            s.append(f'<rect x="{bx:.1f}" y="{base - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" fill="{col}"/>')
            if vals:
                s.append(text(bx + bw / 2, base - bh - 6, f"{v:.2f}", 11.5, INK, 600, "middle"))
        s.append(text(gx + (gw - 10) / 2, base + 20, label, 13, INK, 600, "middle"))
    s.append(f'<line x1="{x + 30}" y1="{base}" x2="{x + w - 30}" y2="{base}" stroke="{MUTED}"/>')
    lx = x + w - 360
    for _, label, col in stages:
        s += [f'<rect x="{lx}" y="{y + 64}" width="12" height="12" rx="2" fill="{col}"/>', text(lx + 17, y + 75, label, 12, MUTED)]
        lx += 110
    return s


def objects_panel(x, y, w, h, run: Path | None):
    s = card(x, y, w, h, "Asking for objects: models, papers, methods, tools, benchmarks, datasets",
             "Share of gold objects of each type retrieved / named in the answer · Inkling-2-small · all trials")
    if not run:
        return s + [text(x + 20, y + 90, "object study pending", 13, MUTED)]
    st = [r for r in jl(run / "stages.jsonl") if r["model"] == MAIN]
    types = ["model", "paper", "method", "technology", "benchmark", "dataset", "org"]
    conds = [("kg_rag", "Typical GraphRAG"), ("kg_agentic", "Agentic"), ("kg_enrich", "Memory-first"), ("closed_book", "Memory")]
    cw = (w - 200) / len(types)
    s.append(text(x + 20, y + 84, "", 12))
    for j, t in enumerate(types):
        s.append(text(x + 190 + j * cw + cw / 2, y + 88, {"technology": "tech/tool", "benchmark": "bench"}.get(t, t), 12.5, MUTED, 600, "middle"))
    for i, (c, label) in enumerate(conds):
        yy = y + 112 + i * 34
        s.append(text(x + 20, yy + 4, label, 13, INK, 600))
        for j, t in enumerate(types):
            g = r_ = u_ = 0
            for r in st:
                if r["condition"] == c and t in (r.get("by_type") or {}):
                    g, r_, u_ = g + r["by_type"][t][0], r_ + r["by_type"][t][1], u_ + r["by_type"][t][2]
            cx = x + 190 + j * cw + cw / 2
            if g:
                u = u_ / g
                s.append(f'<rect x="{cx - cw / 2 + 6:.1f}" y="{yy - 14}" width="{cw - 12:.1f}" height="24" rx="5" '
                         f'fill="{ACCENT}" fill-opacity="{0.08 + 0.8 * u:.2f}"/>')
                s.append(text(cx, yy + 3, f"{r_ / g:.2f} / {u:.2f}", 12, INK if u < 0.65 else "#ffffff", 600, "middle"))
            else:
                s.append(text(cx, yy + 3, "–", 12, MUTED, anchor="middle"))
    return s


def examples_panel(x, y, w, h, run: Path):
    tasks = {t["id"]: t for t in jl(run / "tasks.jsonl")}
    runs = {r["task_id"]: r for r in jl(run / "runs.jsonl") if r["condition"] == "kg_enrich" and r["model"] == MAIN
            and r.get("trial", 0) == 0 and r.get("answer")}
    picks = [("U-vendor_choice-thin-1", "replaced"), ("U-method_adoption-thin-1", "replaced"),
             ("U-customer_stack-thin-1", "gap"), ("U-learn_method-thin-1", "flagged")]
    s = card(x, y, w, h, "What the graph changed in the memory draft (real edits)", "Memory-first records every change it makes to the model's own answer; the last one is a failure")
    yy = y + 84
    for k, (tid, kind) in enumerate(picks):
        r = runs.get(tid)
        if not r:
            continue
        ch = next((c for c in r.get("changes") or [] if c["kind"] == kind and (tid != "U-learn_method-thin-1" or "QAT" in c["what"])), None)
        if not ch:
            continue
        fail = tid == "U-learn_method-thin-1"
        col = "#b91c1c" if fail else ACCENT
        s.append(f'<rect x="{x + 20}" y="{yy - 14}" width="6" height="{58}" rx="3" fill="{col}"/>')
        s.append(text(x + 36, yy, f"{tasks[tid]['usecase'].replace('_', ' ')} · {tasks[tid]['anchor_name']} · {('FAILURE: ' if fail else '') + kind}",
                      12.5, col, 700))
        for i, line in enumerate(wrap(ch["what"], 92)[:3]):
            s.append(text(x + 36, yy + 18 + i * 16, line, 12.5, INK))
        yy += 74
    s.append(text(x + 36, y + h - 18, "QAT is well established; the graph just does not cover it. Missing ≠ false is still not fully learned.", 12, MUTED))
    return s


def objects_note(x, y):
    return [text(x + 20, y, "Papers are retrieved every time and named in no answer: the advice format has no reading-list slot.", 12, "#b91c1c", 600)]


def main(run_dir: str, obj_dir: str | None = None) -> None:
    run, obj = Path(run_dir), Path(obj_dir) if obj_dir else None
    tasks = jl(run / "tasks.jsonl")
    res = json.loads((run / "result.json").read_text())
    nobj = len(jl(obj / "tasks.jsonl")) if obj else 0
    s = [(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         'font-family="Inter, -apple-system, Segoe UI, Helvetica, Arial, sans-serif">'), f'<rect width="{W}" height="{H}" fill="{BG}"/>',
         text(40, 58, "Does grounding in a knowledge graph make guidance better?", 30, INK, 800),
         text(40, 88, f"Connected Frontiers · {len(tasks)} generated use-case tasks" + (f" + {nobj} object tasks" if nobj else "")
              + f" · KB {res['kb_version']} · small model Inkling-2-small vs Qwen-397B from memory", 15, MUTED),
         text(40, 114, "Robust: a small model that edits its own draft with the graph beats a 397B model from memory "
              "(0.98, also length-matched).", 15, ACCENT, 700),
         text(40, 134, "Not yet robust: memory-first vs memory (0.91, but 0.59 when answer length is matched).", 15, MUTED, 700)]
    s += prefs_panel(40, 160, 660, 400, run)
    s += funnel_panel(720, 160, 640, 400, run)
    s += objects_panel(40, 580, 660, 270, obj)
    if obj:
        s += objects_note(40, 832)
    s += examples_panel(720, 580, 640, 420, run)
    caveat = ("Caveats: judges are LLMs (GLM, Nemotron), not people; one trial judged per task; small task sets; "
              "answers from the graph are only as good as its mostly self-claimed edges.")
    s += card(40, 870, 660, 130, "How it was measured")
    for i, line in enumerate(wrap("Tasks are generated from a use-case catalogue (persona + anchor + question + gold facts computed "
                                  "from the graph), curated and rewritten by a separate model family, leak-checked. Each condition "
                                  "is scored at three stages against the gold, plus judge preferences in both orders.", 100)):
        s.append(text(60, 925 + i * 17, line, 12.5, INK))
    for i, line in enumerate(wrap(caveat, 180)):
        s.append(text(40, 1030 + i * 17, line, 12.5, MUTED))
    s.append(text(40, H - 40, "github.com/prabakaranc98/connected-frontiers · docs/AGENCY_EVAL.md · docs/RETRIEVAL.md", 12.5, MUTED))
    s.append("</svg>")
    out = Path("docs/posters")
    out.mkdir(parents=True, exist_ok=True)
    svg = out / "grounding-results.svg"
    svg.write_text("\n".join(s))
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(chrome).exists():
        subprocess.run([chrome, "--headless=new", f"--window-size={W},{H}", "--force-device-scale-factor=2", "--hide-scrollbars",
                        f"--screenshot={Path.cwd() / out / 'grounding-results.png'}", f"file://{Path.cwd() / svg}"],
                       check=False, capture_output=True, timeout=60)
    print(svg, (out / "grounding-results.png").exists())


if __name__ == "__main__":
    main(*sys.argv[1:])
