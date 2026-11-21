"""Local crawl dashboard: http://127.0.0.1:8765 (stdlib only, localhost only).

GET /api/status   live crawler state (crawl_live.json) + true totals (KB pages, fetched pages)
                  + alive check + batch history + recent page / LLM events + supervisor log
GET /             dashboard that polls /api/status every 3 s and updates in place (no reloads)
GET /explorer     the graph explorer for the CURRENT KB (data/processed/graph/explorer.html)
"""

from __future__ import annotations

import glob
import json
import os
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cf import config

INTERIM = config.DATA / "interim"
_cache: dict = {"t": 0, "fetched_ok": 0}


def _tail(path: str, n: int = 15) -> list[dict]:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 80_000))
            lines = f.read().decode("utf-8", "ignore").splitlines()[-n:]
        return [json.loads(x) for x in lines if x.startswith("{")][::-1]
    except (OSError, ValueError):
        return []


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def status() -> dict:
    live = {}
    try:
        live = json.loads((INTERIM / "crawl_live.json").read_text())
    except (OSError, ValueError):
        pass
    if time.time() - _cache["t"] > 3:                        # recount totals at most every 3 s
        try:
            urls = set()
            with open(config.DATA / "raw" / "index.jsonl") as f:
                for line in f:
                    r = json.loads(line)
                    if r.get("status") == "ok":
                        urls.add(r["url"])
            _cache.update(t=time.time(), fetched_ok=len(urls),
                          kb_pages=len(glob.glob(str(INTERIM / "extract" / "*.json"))))
        except (OSError, ValueError):
            pass
    state = {}
    try:
        state = json.loads((INTERIM / "frontier_state.json").read_text())
    except (OSError, ValueError):
        pass
    sup_log = []
    try:
        sup_log = (INTERIM / "supervisor.log").read_text().splitlines()[-8:][::-1]
    except OSError:
        pass
    sup_pid = (INTERIM / "supervisor.pid").read_text().strip() if (INTERIM / "supervisor.pid").exists() else None
    run = live.get("trace_run")
    tr = INTERIM / "traces" / run if run else None
    # live per-page progress: extraction-cache files written since this run started (run id = start time)
    if run:
        try:
            start = datetime.strptime(run[:15], "%Y%m%d-%H%M%S").replace(tzinfo=UTC).timestamp()
            new_pages = sum(1 for f in (INTERIM / "extract").glob("*.json") if f.stat().st_mtime >= start)
            live = {**live, "run_pages": max(live.get("run_pages", 0), new_pages)}
        except (ValueError, OSError):
            pass
    fresh = bool(live) and time.time() - live.get("ts", 0) < 30
    return {"now": time.time(), "alive": _alive(live.get("pid")) and fresh, "stale_s": round(time.time() - live.get("ts", 0)) if live else None,
            "supervisor": {"pid": sup_pid, "alive": _alive(sup_pid), "log": sup_log},
            "totals": {"kb_pages": _cache.get("kb_pages"), "fetched_ok": _cache.get("fetched_ok")},
            "live": live, "history": (state.get("stats") or {}).get("history", []),
            "pages_feed": _tail(str(tr / "pages.jsonl")) if tr else [],
            "llm_feed": [{"ts": r.get("ts"), "call": r.get("call"), "model": r.get("model"), "latency_s": r.get("latency_s"),
                          "tokens": (r.get("usage") or {}).get("total_tokens"), "cost": (r.get("usage") or {}).get("cost"),
                          "finish": (r.get("response") or {}).get("finish"), "error": (r.get("error") or "")[:80]}
                         for r in _tail(str(tr / "llm.jsonl"))] if tr else []}


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crawl monitor</title><style>
:root{--bg:#fbfbfa;--ink:#1f2933;--muted:#5f6b7a;--line:#e3e6ea;--chip:#f2f4f7}
@media (prefers-color-scheme:dark){:root{--bg:#14171b;--ink:#e6e9ee;--muted:#9aa4b1;--line:#2c323a;--chip:#232830}}
body{margin:0;padding:20px 16px;font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--ink)}.wrap{max-width:1180px;margin:0 auto}
h1{font-size:20px;margin:0}.muted{color:var(--muted);font-size:12.5px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}.k{background:var(--chip);border-radius:10px;padding:10px 12px}.k b{display:block;font-size:22px}
.bar{position:relative;height:24px;background:var(--chip);border-radius:8px;margin:8px 0;overflow:hidden}.fill{height:100%;transition:width .6s}.bar span{position:absolute;left:10px;top:3px;font-weight:600;font-size:13px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:900px){.cols{grid-template-columns:1fr}}
.card{border:1px solid var(--line);border-radius:10px;padding:10px 12px;overflow:hidden}table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left}
.chip{display:inline-block;background:var(--chip);border-radius:12px;padding:2px 9px;margin:2px 3px;font-size:12px}.phase{font-weight:600;color:#2f9e5b;margin:8px 0}
svg{width:100%;height:80px}
</style></head><body><div class="wrap">
<h1>Connected Frontiers · crawl monitor <a href="/explorer" style="font-size:13px;font-weight:500;margin-left:10px">open explorer →</a></h1>
<div class="muted" id="hdr">connecting…</div>
<div class="phase" id="phase"></div>
<div class="bar"><div class="fill" id="pbar" style="background:#2f9e5b;width:0"></div><span id="ptxt"></span></div>
<div class="bar"><div class="fill" id="sbar" style="background:#d9822b;width:0"></div><span id="stxt"></span></div>
<div class="grid" id="kpis"></div>
<div class="cols"><div class="card"><b>Entities per batch</b><svg id="c1"></svg></div><div class="card"><b>New edges per batch</b><svg id="c2"></svg></div></div>
<h3>Noise gates</h3><div id="noise"></div>
<div class="cols" style="margin-top:12px"><div class="card"><b>Live · pages</b><table id="pf"></table></div><div class="card"><b>Live · LLM calls</b><table id="lf"></table></div></div>
<h3>Supervisor</h3><div class="card"><table id="sup"></table></div>
</div><script>
const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const col={extracted:'#2f9e5b',thin:'#b7950b',near_duplicate:'#b7950b',skipped_url:'#9aa4b1',fetch_failed:'#d64545',llm_failed:'#d64545'};
function spark(id,vals,color){const s=$(id),w=s.clientWidth||500,h=80;if(vals.length<2){s.innerHTML='';return}const lo=Math.min(...vals),hi=Math.max(...vals),sp=(hi-lo)||1;
 s.innerHTML=`<polyline fill="none" stroke="${color}" stroke-width="2" points="${vals.map((v,i)=>`${5+i*(w-10)/(vals.length-1)},${h-6-(v-lo)*(h-16)/sp}`).join(' ')}"/><text x="4" y="11" font-size="10" fill="currentColor" opacity=".6">${lo.toLocaleString()} → ${hi.toLocaleString()}</text>`}
async function tick(){try{const d=await (await fetch('/api/status',{cache:'no-store'})).json(),L=d.live||{};
 $('hdr').innerHTML=`<span class="dot" style="background:${d.alive?'#2f9e5b':'#d64545'}"></span>${d.alive?'crawler running':'crawler not running'+(d.stale_s!=null?` (last heartbeat ${d.stale_s}s ago)`:'')} · supervisor ${d.supervisor.alive?'<b>on</b> (auto-resume)':'off'} · policy ${esc(L.policy)} · ${new Date().toLocaleTimeString()}`;
 $('phase').textContent=L.phase?`▶ ${L.phase}${L.of?` (${L.n}/${L.of})`:''}`:'';
 const run=L.run_pages||0,bud=L.budget||1;$('pbar').style.width=Math.min(100,100*run/bud)+'%';$('ptxt').textContent=`this run: ${run} / ${bud} new pages`;
 $('sbar').style.width=Math.min(100,100*(L.run_spend_usd||0)/(L.max_usd||1))+'%';$('stxt').textContent=`run spend $${(L.run_spend_usd||0).toFixed(3)} / $${L.max_usd||'–'} guard`;
 const rate=L.minutes?run/L.minutes:0,eta=rate?(bud-run)/rate:null;
 const k=[['KB pages (extracted+verified)',d.totals.kb_pages],['pages fetched (all time)',d.totals.fetched_ok],['entities',L.entities],['edges',L.edges],['domains known',L.domains_known],['URLs queued',L.queued_urls],['pages/min (this run)',rate.toFixed(1)],['ETA',eta?Math.round(eta)+' min':'–'],['errors this run',L.errors||0]];
 $('kpis').innerHTML=k.map(([a,b])=>`<div class="k"><b>${(b??'–').toLocaleString?.()??b}</b>${a}</div>`).join('');
 spark('c1',d.history.map(r=>r.entities),'#3b6fd8');spark('c2',d.history.map(r=>r.new_edges),'#d9822b');
 $('noise').innerHTML=Object.entries(L.noise||{}).map(([a,b])=>`<span class="chip">${esc(a)}: <b>${b}</b></span>`).join('');
 $('pf').innerHTML='<tr><th>time</th><th>domain</th><th>gate</th><th>triples</th><th>✓/✗</th><th>new</th></tr>'+d.pages_feed.map(r=>`<tr><td>${esc((r.ts||'').slice(11,19))}</td><td>${esc(r.domain)}</td><td style="color:${col[r.gate]||'inherit'}">${esc(r.gate)}</td><td>${r.triples??''}</td><td>${r.verified??''}${r.rejected!=null?' / '+r.rejected:''}</td><td>${r.new_edges??''}</td></tr>`).join('');
 $('lf').innerHTML='<tr><th>time</th><th>call</th><th>model</th><th>s</th><th>tok</th><th>finish</th></tr>'+d.llm_feed.map(r=>`<tr><td>${esc((r.ts||'').slice(11,19))}</td><td>${esc(r.call)}</td><td>${esc((r.model||'').split('/').pop())}</td><td>${r.latency_s??''}</td><td>${r.tokens??''}</td><td style="color:${r.error?'#d64545':'inherit'}">${esc(r.error||r.finish||'')}</td></tr>`).join('');
 $('sup').innerHTML=(d.supervisor.log||[]).map(l=>`<tr><td>${esc(l)}</td></tr>`).join('')||'<tr><td class="muted">no supervisor log yet</td></tr>';
}catch(e){$('hdr').textContent='dashboard server unreachable: start it with `cf serve`'}}
tick();setInterval(tick,3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/status"):
            body, ctype = json.dumps(status(), default=str).encode(), "application/json"
        elif self.path.split("?")[0].split("#")[0] == "/explorer":
            f = config.DATA / "processed" / "graph" / "explorer.html"
            if not f.exists():
                self.send_error(404, "explorer not built yet: run `cf build`")
                return
            body, ctype = f.read_bytes(), "text/html; charset=utf-8"
        elif self.path in ("/", "/index.html"):
            body, ctype = PAGE.encode(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):   # quiet
        pass


def serve(port: int = 8765) -> None:
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
