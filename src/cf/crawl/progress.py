"""Live crawl progress page: rewritten after every batch, auto-refreshes in the browser.

Open data/interim/crawl_progress.html once; it reloads itself every 10 s while the crawl runs.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime

from cf import config

PAGE = config.DATA / "interim" / "crawl_progress.html"


def _spark(values: list[float], w: int = 520, h: int = 90, color: str = "#3b6fd8") -> str:
    if len(values) < 2:
        return f'<svg width="{w}" height="{h}"></svg>'
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pts = " ".join(f"{i * (w - 10) / (len(values) - 1) + 5:.1f},{h - 8 - (v - lo) * (h - 20) / span:.1f}"
                   for i, v in enumerate(values))
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><polyline fill="none" stroke="{color}" '
            f'stroke-width="2.2" points="{pts}"/><text x="6" y="12" font-size="11" fill="currentColor" opacity=".6">'
            f'{lo:,.0f} → {hi:,.0f}</text></svg>')


def _bar(frac: float, label: str, color: str) -> str:
    frac = max(0.0, min(1.0, frac))
    return (f'<div class="bar"><div class="fill" style="width:{100 * frac:.1f}%;background:{color}"></div>'
            f'<span>{html.escape(label)}</span></div>')


def _tail(path, n: int = 14) -> list[dict]:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 64_000))
            lines = f.read().decode("utf-8", "ignore").splitlines()[-n:]
        return [json.loads(x) for x in lines if x.strip().startswith("{")][::-1]
    except (OSError, ValueError):
        return []


def _feeds(trace_dir) -> tuple[str, str]:
    if trace_dir is None:
        return "", ""
    gate_color = {"extracted": "#2f9e5b", "thin": "#b7950b", "near_duplicate": "#b7950b", "skipped_url": "#9aa4b1",
                  "fetch_failed": "#d64545", "llm_failed": "#d64545"}
    pages = "".join(
        f"<tr><td>{r.get('ts', '')[11:19]}</td><td>{html.escape(r.get('domain', ''))}</td>"
        f"<td style='color:{gate_color.get(r.get('gate'), 'inherit')}'>{r.get('gate')}</td><td>{r.get('triples', '')}</td>"
        f"<td>{r.get('verified', '')}{' / ' + str(r.get('rejected')) if 'rejected' in r else ''}</td><td>{r.get('new_edges', '')}</td></tr>"
        for r in _tail(trace_dir / "pages.jsonl"))
    llm = "".join(
        f"<tr><td>{r.get('ts', '')[11:19]}</td><td>{html.escape(r.get('call', ''))}</td>"
        f"<td>{html.escape((r.get('model') or '').split('/')[-1])}</td><td>{r.get('latency_s', '')}</td>"
        f"<td>{(r.get('usage') or {}).get('total_tokens', '')}</td><td>{(r.get('usage') or {}).get('cost', '') or ''}</td>"
        f"<td{' class=err' if r.get('error') else ''}>{html.escape(str((r.get('response') or {}).get('finish') or ('error' if r.get('error') else '')))}</td></tr>"
        for r in _tail(config.DATA / "interim" / "traces" / trace_dir.name / "llm.jsonl"))
    return pages, llm


def write(history: list[dict], budget: int, max_usd: float, noise: dict, generic: dict, policy: str,
          errors: int, last_error: str | None, finished: bool, domains_crawled: int, queued: int,
          phase: str | None = None, live: dict | None = None, trace_dir=None) -> None:
    last = dict(history[-1]) if history else {"pages": 0, "entities": 0, "edges": 0, "spend": 0, "minutes": 0,
                                               "domains_known": 0, "new_edges": 0}
    if live:                                   # streaming values from the running process
        last.update({k: v for k, v in live.items() if v is not None})
    pages_feed, llm_feed = _feeds(trace_dir)
    pages, spend, minutes = last["pages"], last["spend"], last["minutes"]
    rate = pages / minutes if minutes else 0
    eta = (budget - pages) / rate if rate else None
    state = "finished ✓" if finished else ("stopped: " + last_error if last_error and not finished and "interrupted" in (last_error or "") else "running…")
    refresh = "" if finished else '<meta http-equiv="refresh" content="5">'
    rows = "".join(f"<tr><td>{i + 1}</td><td>{r['pages']}</td><td>{r['entities']:,}</td><td>{r['edges']:,}</td>"
                   f"<td>{r['new_edges']}</td><td>{r['domains_known']}</td><td>${r['spend']}</td><td>{r['minutes']}</td></tr>"
                   for i, r in list(enumerate(history))[-12:][::-1])
    chips = "".join(f'<span class="chip">{html.escape(k)}: <b>{v}</b></span>' for k, v in {**noise, **generic}.items())
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(f"""<!doctype html><html><head><meta charset="utf-8">{refresh}
<title>Crawl progress</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#fbfbfa;--ink:#1f2933;--muted:#5f6b7a;--line:#e3e6ea;--chip:#f2f4f7}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171b;--ink:#e6e9ee;--muted:#9aa4b1;--line:#2c323a;--chip:#232830}}}}
body{{margin:0;padding:24px 16px;font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--ink)}}
.wrap{{max-width:1080px;margin:0 auto}}h1{{font-size:20px;margin:0 0 4px}}.muted{{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:16px 0}}
.k{{background:var(--chip);border-radius:10px;padding:10px 12px}}.k b{{display:block;font-size:22px}}
.bar{{position:relative;height:26px;background:var(--chip);border-radius:8px;margin:8px 0;overflow:hidden}}
.fill{{height:100%;transition:width .5s}}.bar span{{position:absolute;left:10px;top:4px;font-weight:600;font-size:13px}}
.charts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}
.card{{border:1px solid var(--line);border-radius:10px;padding:10px 12px;overflow:hidden}}
.chip{{display:inline-block;background:var(--chip);border-radius:12px;padding:3px 10px;margin:3px 4px 3px 0;font-size:12px}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}td,th{{padding:5px 6px;border-bottom:1px solid var(--line);text-align:right}}
th{{color:var(--muted);font-weight:600}}td:first-child,th:first-child{{text-align:left}}
.err{{color:#d64545}}.phase{{margin:10px 0 2px;font-weight:600;color:#2f9e5b}}svg{{max-width:100%;color:var(--ink)}}
</style></head><body><div class="wrap">
<h1>Connected Frontiers · crawl progress</h1>
<div class="muted">policy <b>{policy}</b> · {html.escape(state)} · updated {datetime.now(UTC).strftime('%H:%M:%S')} UTC · live · refresh 5 s</div>
<div class="phase">▶ {html.escape(phase or "")}</div>
{_bar(pages / max(budget, 1), f"pages {pages:,} / {budget:,}", "#2f9e5b")}
{_bar(spend / max(max_usd, 1e-9), f"spend ${spend:.2f} / ${max_usd:.2f} guard", "#d9822b")}
<div class="grid">
 <div class="k"><b>{last['entities']:,}</b>entities</div><div class="k"><b>{last['edges']:,}</b>edges</div>
 <div class="k"><b>{last['domains_known']}</b>domains known</div><div class="k"><b>{domains_crawled}</b>domains crawled</div>
 <div class="k"><b>{queued:,}</b>URLs queued</div><div class="k"><b>{rate:.1f}</b>pages / min</div>
 <div class="k"><b>{minutes:.0f} min</b>elapsed</div><div class="k"><b>{f"{eta:.0f} min" if eta else "–"}</b>ETA</div>
</div>
<div class="charts">
 <div class="card"><b>Entities</b><br>{_spark([r['entities'] for r in history])}</div>
 <div class="card"><b>Edges</b><br>{_spark([r['edges'] for r in history], color="#7c5cd6")}</div>
 <div class="card"><b>Domains known</b><br>{_spark([r['domains_known'] for r in history], color="#0f8b8d")}</div>
 <div class="card"><b>New edges per batch</b><br>{_spark([r['new_edges'] for r in history], color="#d9822b")}</div>
</div>
<h3>Noise gates (dropped)</h3><div>{chips or '<span class="muted">none yet</span>'}</div>
{f'<p class="err">errors: {errors} · last: {html.escape(last_error or "")}</p>' if errors or (last_error and "budget" in last_error) else ''}
<div class="charts">
<div class="card"><b>Live · pages</b><table><tr><th>time</th><th>domain</th><th>gate</th><th>triples</th><th>✓ / ✗</th><th>new edges</th></tr>{pages_feed}</table></div>
<div class="card"><b>Live · LLM calls</b><table><tr><th>time</th><th>call</th><th>model</th><th>s</th><th>tokens</th><th>$</th><th>finish</th></tr>{llm_feed}</table></div>
</div>
<h3>Recent batches</h3>
<table><tr><th>#</th><th>pages</th><th>entities</th><th>edges</th><th>new edges</th><th>domains</th><th>spend</th><th>min</th></tr>{rows}</table>
<p class="muted">Status from the terminal: <code>cf crawl --status</code> · resume after a stop: <code>cf crawl --resume</code></p>
</div></body></html>""")


def snapshot_json() -> dict:
    return json.loads((config.DATA / "interim" / "frontier_state.json").read_text())
