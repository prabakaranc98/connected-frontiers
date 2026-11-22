"""Graph explorer: WebGL rendering (sigma.js + graphology) over a layout precomputed in Python.

Levels (breadcrumbs Map › Segment › Entity; URL hash #map / #seg=<id> / #<entity id>; browser back works)
- Map (default): one bubble per segment, links aggregated across segments by their main relation.
- Segment: only that segment's top members by PageRank, plus a card (players, problems, methods, links out).
- Entity: relation lens below, plus a card with connections grouped by relation and the sources behind them.
Other views
- All entities: force layout (precomputed) or layer swimlanes; segment bubbles with names.
- Focus (relation lens): neighbours grouped into labelled sectors by HOW they connect
  (outgoing relations right, incoming left); 2-hop nodes fan out behind their parent; hop depth N
  chosen from where 80% of the node's own personalized PageRank sits.
- Path finder: strongest evidence paths between two entities.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import networkx as nx

PALETTE = ["#3b6fd8", "#d9822b", "#2f9e5b", "#c2417a", "#7c5cd6", "#0f8b8d", "#b7950b", "#a0522d",
           "#5b8c2a", "#d64545", "#4f6d7a", "#8e6c8a", "#2a9d8f", "#e76f51", "#6a4c93", "#577590"]


def _positions(g: nx.Graph, cid: dict[str, int], n_comms: int, iters: int) -> dict:
    """Largest component: segment-anchored start + Fruchterman–Reingold, scaled to radius 1.
    Small components: packed on an outer ring, so they don't squash the main picture."""
    rnd = random.Random(7)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    main = g.subgraph(comps[0])
    k = max(1, n_comms)
    init = {}
    for n in main:
        a = 2 * math.pi * cid[n] / k
        init[n] = (math.cos(a) + rnd.gauss(0, 0.2), math.sin(a) + rnd.gauss(0, 0.2))
    pos = nx.spring_layout(main, pos=init, k=2.2 / math.sqrt(max(len(main), 1)), iterations=iters,
                           weight="weight", seed=7)
    cx = sum(p[0] for p in pos.values()) / len(pos)
    cy = sum(p[1] for p in pos.values()) / len(pos)
    rmax = max(math.hypot(p[0] - cx, p[1] - cy) for p in pos.values()) or 1.0
    pos = {n: ((p[0] - cx) / rmax, (p[1] - cy) / rmax) for n, p in pos.items()}
    rest = comps[1:]
    for i, comp in enumerate(rest):
        a = 2 * math.pi * i / max(len(rest), 1)
        ax, ay = 1.2 * math.cos(a), 1.2 * math.sin(a)
        sub = nx.spring_layout(g.subgraph(comp), seed=7) if len(comp) > 1 else {next(iter(comp)): (0, 0)}
        for n, p in sub.items():
            pos[n] = (ax + 0.04 * p[0], ay + 0.04 * p[1])
    return pos


def compute_layout(graph: dict, iters: int = 300) -> dict:
    """Add x, y, community to each entity; add a community summary to the graph."""
    g = nx.Graph()
    g.add_nodes_from(e["id"] for e in graph["entities"])
    for e in graph["edges"]:
        w = max(0.15, float(e.get("strength") or 0))
        prev = g.get_edge_data(e["head"], e["tail"], {}).get("weight", 0)
        g.add_edge(e["head"], e["tail"], weight=prev + w)
    comms = sorted(nx.community.louvain_communities(g, weight="weight", seed=7), key=len, reverse=True)
    cid = {n: i for i, c in enumerate(comms) for n in c}
    pos = _positions(g, cid, len(comms), iters)
    ents = {e["id"]: e for e in graph["entities"]}
    for e in graph["entities"]:
        x, y = pos[e["id"]]
        e["x"], e["y"], e["community"] = float(x), float(y), cid[e["id"]]
    graph["communities"] = [
        {"id": i, "size": len(c),
         "top": [ents[n]["name"] for n in sorted(c, key=lambda n: -(ents[n].get("pagerank") or 0))[:4]]}
        for i, c in enumerate(comms) if len(c) >= 3
    ]
    for c in graph["communities"]:
        c.setdefault("name", " · ".join(c["top"][:2]))
    return graph


def segment_map(graph: dict, max_segments: int = 30, min_size: int = 8) -> dict:
    """Overview level: one bubble per segment, links aggregated across segments and labelled by their
    most common relation; laid out on its own (spring layout of the meta-graph), so it never hairballs."""
    from collections import Counter, defaultdict
    comms = [c for c in graph.get("communities", []) if c["size"] >= min_size][:max_segments]
    keep = {c["id"] for c in comms}
    cid = {e["id"]: e.get("community") for e in graph["entities"]}
    n, rels = Counter(), defaultdict(Counter)
    for e in graph["edges"]:
        a, b = cid.get(e["head"]), cid.get(e["tail"])
        if e["status"] == "unsupported" or a == b or a not in keep or b not in keep:
            continue
        k = (min(a, b), max(a, b))
        n[k] += 1
        rels[k][e["relation"]] += 1
    links = [{"a": a, "b": b, "n": c, "rel": rels[(a, b)].most_common(1)[0][0]} for (a, b), c in n.most_common(80)]
    g = nx.Graph()
    g.add_nodes_from(keep)
    for x in links:
        g.add_edge(x["a"], x["b"], weight=math.log1p(x["n"]))
    pos: dict = {}
    if len(g):
        comps = sorted(nx.connected_components(g), key=len, reverse=True)
        main = g.subgraph(comps[0])
        pos = nx.spring_layout(main, k=2.5 / math.sqrt(max(len(main), 1)), iterations=400, weight="weight", seed=7)
        r = max((math.hypot(*p) for p in pos.values()), default=1.0) or 1.0
        pos = {k: (p[0] / r * 0.85, p[1] / r * 0.85) for k, p in pos.items()}
        rest = [n for c in comps[1:] for n in c]                # unconnected segments: outer ring
        for i, n_ in enumerate(rest):
            a = 2 * math.pi * i / max(len(rest), 1) + 0.3
            pos[n_] = (1.05 * math.cos(a), 1.05 * math.sin(a))
        size = {c["id"]: c["size"] for c in comms}
        smax = max(size.values())
        rad = {k: 0.05 + 0.11 * math.sqrt(size[k] / smax) for k in pos}
        pts = {k: list(v) for k, v in pos.items()}
        for _ in range(300):                                     # resolve bubble overlaps
            moved = False
            ks = list(pts)
            for i, a_ in enumerate(ks):
                for b_ in ks[i + 1:]:
                    dx, dy = pts[b_][0] - pts[a_][0], pts[b_][1] - pts[a_][1]
                    d = math.hypot(dx, dy) or 1e-6
                    need = rad[a_] + rad[b_] + 0.03
                    if d < need:
                        push = (need - d) / 2
                        ux, uy = dx / d, dy / d
                        pts[a_][0] -= ux * push
                        pts[a_][1] -= uy * push
                        pts[b_][0] += ux * push
                        pts[b_][1] += uy * push
                        moved = True
            if not moved:
                break
        r = max(math.hypot(*p) + rad[k] for k, p in pts.items()) or 1.0
        pos = {k: (p[0] / r, p[1] / r) for k, p in pts.items()}
    types = defaultdict(Counter)
    for e in graph["entities"]:
        if e.get("community") in keep:
            types[e["community"]][e["type"]] += 1
    return {"nodes": [{"id": c["id"], "name": c.get("name"), "size": c["size"], "top": c.get("top", []),
                       "types": dict(types[c["id"]].most_common(4)),
                       "x": float(pos[c["id"]][0]), "y": float(pos[c["id"]][1])} for c in comms],
            "links": links}


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connected Frontiers Explorer</title>
<script src="https://cdn.jsdelivr.net/npm/graphology@0.25.4/dist/graphology.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/sigma@3.0.2/dist/sigma.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/graphology-library@0.8.0/dist/graphology-library.min.js"></script>
<style>
:root{--bg:#fbfbfa;--panel:#ffffff;--ink:#1f2933;--muted:#5f6b7a;--line:#e3e6ea;--chip:#f2f4f7;--fade:#e4e7eb}
@media (prefers-color-scheme:dark){:root{--bg:#121519;--panel:#1a1e24;--ink:#e6e9ee;--muted:#9aa4b1;--line:#2b3139;--chip:#232830;--fade:#2a2f36}}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;font:13.5px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink);display:grid;grid-template-columns:300px 1fr 380px;height:100vh;overflow:hidden}
aside{background:var(--panel);border-right:1px solid var(--line);padding:14px 16px;overflow:auto}#right{border-left:1px solid var(--line);border-right:none}
h1{font-size:16px;margin:0 0 2px}h2{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin:16px 0 6px}
.muted{color:var(--muted);font-size:12px}#wrap{position:relative;width:100%;height:100vh}#sg{position:absolute;inset:0;background:var(--bg)}
#ov{position:absolute;inset:0;pointer-events:none;z-index:2}
label{display:flex;align-items:center;gap:7px;margin:2px 0;cursor:pointer}.sw{width:11px;height:11px;border-radius:3px;display:inline-block;flex:none}
input[type=search],input[type=text],select{width:100%;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font:inherit}
.stat{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}.stat div{background:var(--chip);border-radius:6px;padding:6px 8px;font-size:11.5px}.stat b{display:block;font-size:17px}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:600;color:#fff}
.card{border:1px solid var(--line);border-radius:8px;padding:8px;margin:7px 0;background:var(--bg)}.card q{display:block;font-style:italic;margin:4px 0}
.row{cursor:pointer;padding:4px 6px;border-radius:6px}.row:hover{background:var(--chip)}
.ctl{display:grid;grid-template-columns:84px 1fr;align-items:center;gap:6px;margin:5px 0}
.btn{margin-top:6px;padding:5px 10px;border:1px solid var(--line);border-radius:6px;background:var(--chip);color:var(--ink);font:inherit;cursor:pointer}
.bar{display:grid;grid-template-columns:44px 1fr 74px;gap:6px;align-items:center;font-size:11.5px;margin:2px 0}.bar i{display:block;height:8px;border-radius:4px;background:#9aa4b1}.bar.sel i{background:#2f9e5b}
.path{border:1px solid var(--line);border-radius:8px;padding:6px 8px;margin:6px 0;font-size:12px;cursor:pointer}.path:hover{background:var(--chip)}
a{color:#3b6fd8}ul{padding-left:18px;margin:4px 0}
#tip{position:absolute;z-index:5;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.12);display:none;max-width:340px}
.crumbs{position:absolute;z-index:4;left:12px;top:10px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:5px 10px;font-size:13px;max-width:calc(100% - 24px)}
.crumbs a{cursor:pointer;text-decoration:none}.crumbs span.sep{color:var(--muted);margin:0 6px}
.sec{font-size:11px;font-weight:700;color:var(--muted);margin:10px 0 3px;text-transform:uppercase;letter-spacing:.05em}
.hint{position:absolute;z-index:3;left:12px;bottom:10px;font-size:11.5px;color:var(--muted);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:4px 8px}
@media (max-width:900px){body{grid-template-columns:1fr;grid-template-rows:auto 65vh auto;height:auto;overflow:auto}#wrap{height:65vh}aside{border:none}}
</style></head><body>
<aside>
  <h1>Connected Frontiers</h1><div class="muted">__SUBTITLE__</div>__LINKS__
  <h2>Shown</h2><div class="stat"><div><b id="nN">–</b>entities</div><div><b id="nE">–</b>edges</div><div><b id="nC">–</b>segments</div></div>
  <h2>Search</h2><input type="search" id="q" list="names" placeholder="entity name… (Enter to focus)"><datalist id="names"></datalist>
  <h2>Map</h2>
  <div class="ctl"><span>Layout</span><select id="layout"><option value="force" selected>graph (force)</option><option value="lanes">layer swimlanes</option><option value="segments">segment map</option></select></div>
  <label><input type="checkbox" id="hulls"> segment outlines</label>
  <h2>Focus · relation lens</h2>
  <div id="focusInfo" class="muted">Click a node: neighbours are grouped by how they connect (outgoing → right, ← incoming left).</div>
  <div class="ctl"><span>Hops N</span><select id="hopN"><option value="auto" selected>auto (80% local PPR)</option><option value="1">1</option><option value="2">2</option><option value="3">3</option></select></div>
  <div class="ctl"><span>Fan-out</span><select id="fan"><option value="3">top 3 per node</option><option value="6" selected>top 6 per node</option><option value="12">top 12 per node</option><option value="999">all</option></select></div>
  <div class="ctl"><span>Direction</span><select id="dir"><option value="both">both</option><option value="out">outgoing →</option><option value="in">incoming ←</option></select></div>
  <label><input type="checkbox" id="cross"> show cross-links</label>
  <div id="hopBars"></div>
  <button id="clearFocus" class="btn">back to map (Esc)</button>
  <h2>Path finder</h2>
  <input type="text" id="pa" list="names" placeholder="from…" style="margin-bottom:5px"><input type="text" id="pb" list="names" placeholder="to…">
  <button id="findPath" class="btn">strongest paths</button> <button id="clearPath" class="btn">clear</button>
  <div id="paths"></div>
  <h2>Colour by</h2><select id="colorBy"><option value="type">entity type</option><option value="community">segment</option><option value="layer">ecosystem layer</option></select>
  <h2>Size by</h2><select id="sizeBy"><option value="ppr">PPR from seeds</option><option value="pagerank">global PageRank</option><option value="degree">degree</option></select>
  <h2>Minimum evidence</h2>
  <select id="minStatus"><option value="0">unsupported and up</option><option value="1" selected>claimed and up</option><option value="2">confirmed and up</option><option value="3">corroborated and up</option><option value="4">verified only</option></select>
  <h2>Entity types</h2><div id="types"></div>
  <h2>Legend</h2><div id="legend"></div>
</aside>
<div id="wrap"><div id="crumbs" class="crumbs"></div><div id="sg"></div><svg id="ov" width="100%" height="100%"></svg><div id="tip"></div>
  <div class="hint">scroll to zoom: more entities appear · click: explore in place, click again to walk · Esc / back: step back</div></div>
<aside id="right"><h2>Details</h2><div id="info" class="muted">Click a node or an edge.</div><h2>Influence from selection</h2><div id="infl" class="muted">Local personalized PageRank from the focused node.</div><h2>Top by PPR (seeds)</h2><div id="top"></div><h2>Segments</h2><div id="segs"></div></aside>
<script>
const DATA = __DATA__;
const SigmaCls = (window.Sigma && (window.Sigma.Sigma || window.Sigma.default)) || window.Sigma;
const GraphCls = graphology.Graph || graphology;
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const $ = id => document.getElementById(id);
const PALETTE = __PALETTE__;
const TYPE_COLORS = {org:"#3b6fd8",problem:"#d9822b",method:"#7c5cd6",benchmark:"#2f9e5b",model:"#c2417a",technology:"#6b7785",paper:"#0f8b8d",role:"#b7950b",skill:"#a0522d",dataset:"#5b8c2a",person:"#888"};
const LANES = ["compute","cloud","models","platform","tooling","application","adopter","research","talent","problems"];
const TYPE_LANE = {model:"models",method:"research",paper:"research",benchmark:"research",dataset:"research",technology:"tooling",role:"talent",skill:"talent",problem:"problems"};
const ST = ["unsupported","claimed","confirmed","corroborated","verified"];
const ST_COLORS = {unsupported:"#d64545",claimed:"#d9822b",confirmed:"#b7950b",corroborated:"#3b6fd8",verified:"#2f9e5b"};
const ents = Object.fromEntries(DATA.entities.map(e=>[e.id,e]));
const seeds = new Set(DATA.seeds);
const edgesById = Object.fromEntries(DATA.edges.map(e=>[e.id,e]));
const DIR = {}; DATA.edges.forEach(e=>{ (DIR[e.head+'>'+e.tail] ||= []).push(e) });
const esc = s => String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const q1 = s => String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'");
const badge = s => `<span class="badge" style="background:${ST_COLORS[s]}">${s}</span>`;
const laneOf = e => e.layer && LANES.includes(e.layer) ? e.layer : (e.type==='org' ? (e.org_kind==='customer'?'adopter':'application') : (TYPE_LANE[e.type]||'problems'));

const graph = new GraphCls({type:'directed', multi:false, allowSelfLoops:false});
DATA.entities.forEach(e=>graph.addNode(e.id,{x:e.x||Math.random(),y:e.y||Math.random(),label:e.name,etype:e.type,size:4,color:'#999'}));
DATA.edges.forEach(e=>{ if(!graph.hasNode(e.head)||!graph.hasNode(e.tail)) return;
  const k=graph.edge(e.head,e.tail);
  if(k===undefined) graph.addDirectedEdgeWithKey(e.id,e.head,e.tail,{size:0.6+2.2*(e.strength||0),color:ST_COLORS[e.status],rank:ST.indexOf(e.status),strength:e.strength||0,rel:e.relation});
  else if((e.strength||0)>graph.getEdgeAttribute(k,'strength')) graph.mergeEdgeAttributes(k,{size:0.6+2.2*(e.strength||0),color:ST_COLORS[e.status],rank:ST.indexOf(e.status),strength:e.strength||0,rel:e.relation}) });
const ORIG = {}; graph.forEachNode((n,a)=>{ORIG[n]={x:a.x,y:a.y}});
let BASE = ORIG;   // current global layout (force or lanes)

const state = {hover:null, visible:new Set(), hits:new Set(), min:1, on:new Set(DATA.entities.map(e=>e.type))};
const F = {node:null, dist:new Map(), ppr:new Map(), N:0, shown:new Set(), tree:new Set(), labels:new Set(), lensLabels:[], hidden:0, anim:null};
const P = {nodes:new Set(), edges:new Set()};
const SM = DATA.segment_map || {nodes:[], links:[]};
const V = {level:'map', seg:null, members:new Set()};      // map | seg | entity | all
const RANK = {}; [...DATA.entities].sort((a,b)=>(b.pagerank||0)-(a.pagerank||0)).forEach((e,i)=>RANK[e.id]=i);
const SEL = {node:null, nbrs:new Set(), trail:[]};
const EDGE_QUIET = 'rgba(120,132,148,0.26)';
const alpha = (hex,a) => { const h=hex.replace('#',''); return `rgba(${parseInt(h.slice(0,2),16)},${parseInt(h.slice(2,4),16)},${parseInt(h.slice(4,6),16)},${a})` };
let SHOWN = new Set();
function budget(){ const r=window.renderer?renderer.getCamera().ratio:1; return Math.round(350/Math.pow(Math.max(r,0.02),1.5)) }
function updateShown(){ const b=budget(); SHOWN=new Set();
  state.visible.forEach(n=>{ if(RANK[n]<b||seeds.has(n)||state.hits.has(n)) SHOWN.add(n) });
  if(SEL.node){ SHOWN.add(SEL.node); SEL.nbrs.forEach(v=>SHOWN.add(v)) }
  P.nodes.forEach(v=>SHOWN.add(v)) }
const segName = id => (DATA.communities||[]).find(c=>c.id===id)?.name || ('segment #'+id);

// ---------- styling & filters ----------
function colorOf(e,mode){ if(mode==='community') return PALETTE[e.community % PALETTE.length];
  if(mode==='layer'){ const l=laneOf(e); return PALETTE[LANES.indexOf(l) % PALETTE.length] }
  return TYPE_COLORS[e.type]||'#888' }
function restyle(){ const mode=$('colorBy').value, k=$('sizeBy').value;
  const mx=Math.max(1e-9,...DATA.entities.filter(e=>!seeds.has(e.id)).map(e=>e[k]||0));
  graph.forEachNode(n=>{const e=ents[n];graph.mergeNodeAttributes(n,{color:colorOf(e,mode),size:seeds.has(n)?9:2.2+9*Math.sqrt(Math.min(1,(e[k]||0)/mx))})});
  if(F.node) sizeFocus(); legend(mode); if(window.renderer) renderer.refresh() }
function legend(mode){ let items=[];
  if(mode==='type') items=Object.entries(TYPE_COLORS).filter(([t])=>DATA.entities.some(e=>e.type===t));
  else if(mode==='layer') items=LANES.map(l=>[l,PALETTE[LANES.indexOf(l)%PALETTE.length]]);
  else items=(DATA.communities||[]).slice(0,14).map(c=>[c.name,PALETTE[c.id%PALETTE.length]]);
  $('legend').innerHTML=items.map(([t,c])=>`<div><span class="sw" style="background:${c}"></span> ${esc(t)}</div>`).join('')+
   '<div style="margin-top:8px">'+ST.map(s=>`<div><span class="sw" style="background:${ST_COLORS[s]}"></span> edge: ${s}</div>`).join('')+'</div>' }
function recompute(){ state.on=new Set([...document.querySelectorAll('#types input:checked')].map(i=>i.value)); state.min=+$('minStatus').value;
  state.visible=new Set(); let ne=0;
  graph.forEachEdge((ed,a,s,t)=>{ if(a.rank>=state.min && state.on.has(ents[s].type) && state.on.has(ents[t].type)){state.visible.add(s);state.visible.add(t);ne++} });
  seeds.forEach(s=>{ if(state.on.has(ents[s]?.type)) state.visible.add(s) });
  $('nN').textContent=state.visible.size; $('nE').textContent=ne; $('nC').textContent=(DATA.communities||[]).length;
  updateShown(); if(window.renderer) renderer.refresh() }
const passes = e => ST.indexOf(e.status)>=state.min && state.on.has(ents[e.head].type) && state.on.has(ents[e.tail].type);

// ---------- adjacency, BFS, local PPR ----------
function adjOf(n){ const dir=$('dir').value, out=[];
  const add=(ed,nb)=>{ const a=graph.getEdgeAttributes(ed); if(a.rank<state.min || !state.on.has(ents[nb].type)) return; out.push([nb, Math.max(0.05,a.strength||0)]) };
  if(dir!=='in') graph.forEachOutEdge(n,(ed,a,s,t)=>add(ed,t));
  if(dir!=='out') graph.forEachInEdge(n,(ed,a,s,t)=>add(ed,s));
  return out }
function bfs(src,maxH=5){ const dist=new Map([[src,0]]); let fr=[src];
  for(let h=1;h<=maxH&&fr.length;h++){ const nx=[]; for(const u of fr) for(const [v] of adjOf(u)) if(!dist.has(v)){dist.set(v,h);nx.push(v)} fr=nx } return dist }
function localPPR(src,nodes,alpha=0.15,iters=40){ const adj=new Map(nodes.map(n=>[n,adjOf(n).filter(([v])=>F.dist.has(v))])); let r=new Map(nodes.map(n=>[n,n===src?1:0]));
  for(let it=0;it<iters;it++){ const nr=new Map(nodes.map(n=>[n,0])); let d=0;
    for(const u of nodes){ const ru=r.get(u); if(!ru) continue; const nb=adj.get(u), W=nb.reduce((s,[,w])=>s+w,0);
      if(!W){d+=ru;continue} for(const [v,w] of nb) nr.set(v,nr.get(v)+(1-alpha)*ru*w/W) }
    nr.set(src,nr.get(src)+alpha+(1-alpha)*d); r=nr } return r }
function bestLink(u,v){ // strongest edge between u and v in either direction (respecting filters)
  let best=null, dir=null;
  for(const e of (DIR[u+'>'+v]||[])) if(passes(e) && (!best||e.strength>best.strength)){best=e;dir='out'}
  for(const e of (DIR[v+'>'+u]||[])) if(passes(e) && (!best||e.strength>best.strength)){best=e;dir='in'}
  return best?{e:best,dir}:null }
function edgeKeysBetween(u,v){ return [graph.edge(u,v),graph.edge(v,u)].filter(k=>k!==undefined) }

// ---------- focus: relation lens ----------
function focusNode(n){
  if(!state.visible.has(n)){ $('minStatus').value='0'; recompute() }
  clearPath(true);
  F.node=n; F.dist=bfs(n); F.ppr=localPPR(n,[...F.dist.keys()]);
  const maxH=Math.max(0,...F.dist.values()), mass=Array(maxH+1).fill(0), cnt=Array(maxH+1).fill(0);
  F.dist.forEach((h,v)=>{mass[h]+=F.ppr.get(v)||0;cnt[h]++});
  const rest=mass.slice(1).reduce((a,b)=>a+b,0)||1; let cum=0, auto=Math.min(1,maxH);
  for(let h=1;h<=maxH;h++){cum+=mass[h]/rest; if(cum>=0.8){auto=h;break}}
  if(cnt[1]>40) auto=1;                       // a big first ring is already enough to read
  const ch=$('hopN').value; F.N=Math.min(3, ch==='auto'?auto:Math.min(+ch,Math.max(1,maxH)));
  lens();
  let c2=0; $('hopBars').innerHTML=mass.map((m,h)=>{ if(h===0) return ''; c2+=m/rest;
    return `<div class="bar ${h<=F.N?'sel':''}"><span>hop ${h}</span><i style="width:${Math.max(2,100*m/rest)}%"></i><span>${cnt[h]} · ${(100*c2).toFixed(0)}%</span></div>`}).join('');
  $('focusInfo').innerHTML=`<b>${esc(ents[n].name)}</b> · ${F.shown.size-1} shown within <b>N=${F.N}</b>${ch==='auto'?' (auto)':''}${F.hidden?` · ${F.hidden} more hidden by fan-out`:''}`;
  const ranked=[...F.dist.keys()].filter(v=>v!==n && F.dist.get(v)<=F.N).sort((a,b)=>(F.ppr.get(b)||0)-(F.ppr.get(a)||0));
  $('infl').innerHTML=ranked.slice(0,20).map((v,i)=>`<div class="row" onclick="go('${q1(v)}')">${i+1}. <span class="sw" style="background:${TYPE_COLORS[ents[v].type]}"></span> ${esc(ents[v].name)} <span class="muted">hop ${F.dist.get(v)} · ${(F.ppr.get(v)||0).toFixed(3)}</span></div>`).join('')||'<span class="muted">no neighbours at this evidence level</span>';
  showNode(n); sizeFocus(); renderer.refresh()
}
function lens(){
  const n=F.node, c={x:0,y:0}, R1=1.0, ROW=0.30, fan=+$('fan').value, target={}; target[n]={...c};
  F.shown=new Set([n]); F.tree=new Set(); F.labels=new Set([n]); F.lensLabels=[]; F.hidden=0;
  const pprOf=v=>F.ppr.get(v)||0;
  // group hop-1 neighbours by (direction, relation)
  const groups=new Map(), more=new Map(), cap1=fan>=999?1e9:2*fan;
  for(const [v,h] of F.dist){ if(h!==1) continue; const L=bestLink(n,v); if(!L) continue;
    const key=L.dir+'|'+L.e.relation; if(!groups.has(key)) groups.set(key,[]); groups.get(key).push(v) }
  for(const [k,g] of groups){ if(g.length>cap1){ g.sort((a,b)=>pprOf(b)-pprOf(a)); more.set(k,g.length-cap1); F.hidden+=g.length-cap1; groups.set(k,g.slice(0,cap1)) } }
  // Sectors: every group gets an arc proportional to its size; outgoing groups centred on the right,
  // incoming on the left. One ring, or two alternating rings when crowded (no radial 'rays').
  const outK=[...groups.keys()].filter(k=>k.startsWith('out')).sort((a,b)=>groups.get(b).length-groups.get(a).length);
  const inK=[...groups.keys()].filter(k=>k.startsWith('in')).sort((a,b)=>groups.get(b).length-groups.get(a).length);
  const keys=[...outK,...inK], total=keys.reduce((s,k)=>s+groups.get(k).length,0)||1, gap=0.10;
  const usable=2*Math.PI-gap*keys.length, perNode=usable/total, two=total>48;
  const outSpan=outK.reduce((s,k)=>s+groups.get(k).length*perNode+gap,0);
  let a0=-outSpan/2; const angleOf=new Map(); let maxR=R1+(two?0.28:0);
  keys.forEach(k=>{ const g=groups.get(k).sort((a,b)=>pprOf(b)-pprOf(a)), gs=g.length*perNode;
    g.forEach((v,i)=>{ const a=a0+gs*(g.length===1?0.5:(i+0.5)/g.length), r=R1+(two&&i%2?0.28:0);
      target[v]={x:r*Math.cos(a),y:r*Math.sin(a)}; angleOf.set(v,a); F.shown.add(v);
      edgeKeysBetween(n,v).forEach(x=>F.tree.add(x)); if(i<10) F.labels.add(v) });
    const rel=k.split('|')[1], am=a0+gs/2, lr=R1-0.36;
    F.lensLabels.push({x:lr*Math.cos(am),y:lr*Math.sin(am),text:(k.startsWith('in')?'← ':'')+rel.replace(/_/g,' ')+(k.startsWith('out')?' →':'')+` (${g.length}${more.get(k)?' +'+more.get(k)+' more':''})`});
    a0+=gs+gap });
  // deeper hops: children fan out behind their strongest parent
  let prevR=maxR;
  for(let h=2; h<=F.N; h++){
    const kids=new Map();
    for(const [v,hv] of F.dist){ if(hv!==h) continue; let best=null,bw=-1;
      for(const [u] of adjOf(v)) if(F.dist.get(u)===h-1 && F.shown.has(u) && pprOf(u)>bw){bw=pprOf(u);best=u}
      if(best===null) continue; if(!kids.has(best)) kids.set(best,[]); kids.get(best).push(v) }
    const rH=prevR+0.75; let ringMax=rH;
    for(const [p,list] of kids){ list.sort((a,b)=>pprOf(b)-pprOf(a)); const keep=list.slice(0,fan); F.hidden+=list.length-keep.length;
      const pa=angleOf.get(p)??0, step=Math.min(0.085, 0.9/Math.max(keep.length,1));
      keep.forEach((v,i)=>{ const a=pa+(i-(keep.length-1)/2)*step, r=rH+(i%2)*0.22;
        target[v]={x:r*Math.cos(a),y:r*Math.sin(a)}; angleOf.set(v,a); F.shown.add(v); ringMax=Math.max(ringMax,r);
        edgeKeysBetween(p,v).forEach(x=>F.tree.add(x)); if(i<2) F.labels.add(v) }) }
    prevR=ringMax;
  }
  const ext=prevR+0.45; renderer.setCustomBBox({x:[-ext,ext],y:[-ext,ext]});
  renderer.getCamera().animate({x:0.5,y:0.5,ratio:1},{duration:location.search.includes('noanim')?0:400});
  animateTo(target);
}
function sizeFocus(){ const mx=Math.max(1e-9,...[...F.shown].filter(v=>v!==F.node).map(v=>F.ppr.get(v)||0));
  F.shown.forEach(v=>graph.setNodeAttribute(v,'size',v===F.node?20:5+13*Math.sqrt((F.ppr.get(v)||0)/mx))) }
function animateTo(target,done){ if(F.anim) cancelAnimationFrame(F.anim);
  const start={}; Object.keys(target).forEach(n=>{const a=graph.getNodeAttributes(n);start[n]={x:a.x,y:a.y}});
  const t0=performance.now(), D=location.search.includes('noanim')?0:550;
  const step=t=>{ const k=D?Math.min(1,(t-t0)/D):1, e=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2;
    for(const n in target) graph.mergeNodeAttributes(n,{x:start[n].x+(target[n].x-start[n].x)*e,y:start[n].y+(target[n].y-start[n].y)*e});
    if(k<1) F.anim=requestAnimationFrame(step); else {F.anim=null; done&&done()} };
  F.anim=requestAnimationFrame(step) }
function clearFocus(){ if(V.level==='entity' && F.node) return go(F.node);
  resetFocus(); restyle(); renderer.setCustomBBox(null); renderer.getCamera().animate({x:0.5,y:0.5,ratio:1},{duration:400}); animateTo(BASE) }
function resetFocus(){ F.node=null; F.shown=new Set(); F.tree=new Set(); F.labels=new Set(); F.lensLabels=[];
  $('focusInfo').textContent='Click a node: neighbours are grouped by how they connect (outgoing → right, ← incoming left).';
  $('hopBars').innerHTML=''; $('infl').textContent='Local personalized PageRank from the focused node.' }

// ---------- levels: map › segment › entity ----------
function go(h){ if(decodeURIComponent(location.hash.slice(1))!==h) history.pushState(null,'','#'+h); route() }
function route(){ const h=decodeURIComponent(location.hash.slice(1));
  if(!h||h==='all'||h==='graph'){ $('layout').value='force'; return showAll() }
  if(h==='map') return showMap();
  if(h.startsWith('seg=')) return enterSeg(+h.slice(4));
  if(h==='lanes'){ $('layout').value='lanes'; return showAll() }
  if(h.startsWith('path=')){ const [a,b]=h.slice(5).split('|'); $('pa').value=a; $('pb').value=b; showAll(); return findPaths() }
  if(h.startsWith('lens=') && graph.hasNode(h.slice(5))){ const id=h.slice(5); V.level='entity'; V.from='all'; focusNode(id); return crumbs() }
  if(graph.hasNode(h)) return select(h);
  showAll() }
function setPositions(pos){ if(F.anim){ cancelAnimationFrame(F.anim); F.anim=null } graph.forEachNode(n=>graph.mergeNodeAttributes(n,pos[n])) }
function select(n){ const wasLens=!!F.node||V.level!=='all'; resetFocus(); V.level='all'; V.seg=null; V.members=new Set();
  if(!state.visible.has(n)){ $('minStatus').value='0'; recompute() }
  if(wasLens){ BASE=$('layout').value==='lanes'?lanesLayout():ORIG; setPositions(BASE); renderer.setCustomBBox(null) }
  const i=SEL.trail.indexOf(n); if(i>=0) SEL.trail=SEL.trail.slice(0,i+1); else SEL.trail.push(n); if(SEL.trail.length>8) SEL.trail=SEL.trail.slice(-8);
  SEL.node=n; const nb=[]; graph.forEachEdge(n,(ed,a,s0,t0)=>{ const o=s0===n?t0:s0; if(a.rank>=state.min && state.on.has(ents[o].type)) nb.push([o,a.strength||0]) });
  nb.sort((a,b)=>b[1]-a[1]); SEL.nbrs=new Set(nb.slice(0,60).map(x=>x[0]));
  updateShown(); showNode(n); crumbs(); renderer.refresh();
  // fit the camera to the node and its shown neighbours
  const pts=[n,...SEL.nbrs].map(v=>renderer.getNodeDisplayData(v)).filter(Boolean);
  if(pts.length){ const xs=pts.map(p=>p.x), ys=pts.map(p=>p.y), x0=Math.min(...xs), x1=Math.max(...xs), y0=Math.min(...ys), y1=Math.max(...ys);
    const ratio=Math.min(1, Math.max(0.06, 1.25*Math.max(x1-x0, y1-y0)));
    renderer.getCamera().animate({x:(x0+x1)/2, y:(y0+y1)/2, ratio},{duration:location.search.includes('noanim')?0:650}) } }
function clearSel(){ SEL.node=null; SEL.nbrs=new Set(); SEL.trail=[]; updateShown();
  $('info').innerHTML='<span class="muted">Click an entity to explore it in place. Zoom in to reveal more.</span>'; crumbs(); renderer.refresh() }
function crumbs(){ const parts=[V.level==='map'?'<b>Segment map</b>':`<a onclick="go('all')">Graph</a>`];
  if(V.level==='seg') parts.push(`<b>${esc(segName(V.seg))}</b>`);
  if(V.level==='all') SEL.trail.forEach((id,i)=>parts.push(i===SEL.trail.length-1?`<b>${esc(ents[id].name)}</b>`:`<a onclick="go('${q1(id)}')">${esc(ents[id].name)}</a>`));
  if(V.level==='entity' && F.node) parts.push(`<a onclick="go('${q1(F.node)}')">${esc(ents[F.node].name)}</a>`,'<b>relation lens</b>');
  $('crumbs').innerHTML=parts.join('<span class="sep">›</span>') }
function showMap(){ V.level='map'; V.seg=null; V.members=new Set(); state.hits=new Set(); resetFocus(); clearPath(true);
  if($('layout').value!=='segments') $('layout').value='segments'; renderer.setCustomBBox(null); crumbs();
  $('info').innerHTML=`<b>${SM.nodes.length} segments</b> <span class="muted">(of ${(DATA.communities||[]).length}; ≥ 8 members)</span><div class="muted" style="margin-top:4px">Bubble size = members. A line = edges between two segments, labelled by its most common relation. Click a bubble to open the segment.</div>`+
    SM.nodes.slice(0,30).map(c=>`<div class="row" onclick="go('seg=${c.id}')"><span class="sw" style="background:${PALETTE[c.id%PALETTE.length]}"></span> <b>${esc(c.name)}</b> · ${c.size}<br><span class="muted">${esc(c.top.join(', '))}</span></div>`).join('');
  renderer.refresh() }
function showAll(){ V.level='all'; V.seg=null; V.members=new Set(); resetFocus(); SEL.node=null; SEL.nbrs=new Set(); SEL.trail=[]; updateShown(); crumbs();
  $('info').innerHTML='<span class="muted">Click an entity to explore it in place. Zoom in to reveal more.</span>'; BASE=$('layout').value==='lanes'?lanesLayout():ORIG; renderer.setCustomBBox(null); animateTo(BASE); renderer.refresh() }
function enterSeg(id){ resetFocus(); clearPath(true); V.level='seg'; V.seg=id; state.hits=new Set();
  const mem=DATA.entities.filter(e=>e.community===id && state.visible.has(e.id)).sort((a,b)=>(b.pagerank||0)-(a.pagerank||0));
  const top=mem.slice(0,40); V.members=new Set(top.map(e=>e.id));
  const xs=top.map(e=>ORIG[e.id].x), ys=top.map(e=>ORIG[e.id].y);
  if(top.length){ const pad=0.08, x0=Math.min(...xs)-pad, x1=Math.max(...xs)+pad, y0=Math.min(...ys)-pad, y1=Math.max(...ys)+pad;
    renderer.setCustomBBox({x:[x0,x1],y:[y0,y1]}) }
  animateTo(ORIG); renderer.getCamera().animate({x:0.5,y:0.5,ratio:1},{duration:location.search.includes('noanim')?0:400});
  crumbs(); segCard(id, mem); renderer.refresh() }
function segCard(id, mem){ const row=e=>`<div class="row" onclick="go('${q1(e.id)}')"><span class="sw" style="background:${TYPE_COLORS[e.type]}"></span> ${esc(e.name)} <span class="muted">${(e.pagerank||0).toFixed(4)}</span></div>`;
  const by=t=>mem.filter(e=>e.type===t).slice(0,6);
  const out=SM.links.filter(l=>l.a===id||l.b===id).map(l=>({o:l.a===id?l.b:l.a,n:l.n,rel:l.rel})).slice(0,8);
  $('info').innerHTML=`<b style="font-size:15px">${esc(segName(id))}</b><div class="muted">${mem.length} members at this evidence level · showing the top ${Math.min(40,mem.length)} by PageRank</div>`+
    [['org','Main players'],['problem','Problems'],['method','Methods'],['model','Models'],['benchmark','Benchmarks'],['technology','Technology']]
      .map(([t,h])=>{const r=by(t); return r.length?`<div class="sec">${h}</div>`+r.map(row).join(''):''}).join('')+
    (out.length?'<div class="sec">Connected segments</div>'+out.map(x=>`<div class="row" onclick="go('seg=${x.o}')">${esc(segName(x.o))} <span class="muted">· ${x.n} edges · mostly ${esc(x.rel.replace(/_/g,' '))}</span></div>`).join(''):'') }

// ---------- global layouts ----------
function lanesLayout(){ const xs=Object.values(ORIG).map(p=>p.x), mn=Math.min(...xs), mx=Math.max(...xs), out={};
  const hash=s=>{let h=0;for(const c of s)h=(h*31+c.charCodeAt(0))|0;return (h>>>0)%1000/1000};
  graph.forEachNode(n=>{ const li=LANES.indexOf(laneOf(ents[n])); out[n]={x:-2+4*(ORIG[n].x-mn)/((mx-mn)||1), y:(LANES.length/2-li)*0.55+(hash(n)-0.5)*0.36} });
  return out }
function setLayout(){ const v=$('layout').value; go(v==='segments'?'map':(v==='lanes'?'lanes':'all')) }

// ---------- path finder ----------
function findPaths(){ const byName=s=>{s=s.trim().toLowerCase(); return DATA.entities.find(e=>e.name.toLowerCase()===s)||DATA.entities.find(e=>e.name.toLowerCase().includes(s))};
  const A=byName($('pa').value), B=byName($('pb').value);
  if(!A||!B){ $('paths').innerHTML='<span class="muted">pick two entities from the list</span>'; return }
  const cost=(u,v)=>{ const L=bestLink(u,v); return L?1+2*(1-(L.e.strength||0)):Infinity };
  const nbrs=u=>{ const s=new Set(); graph.forEachNeighbor(u,v=>s.add(v)); return [...s] };
  const dijkstra=(banned)=>{ const dist=new Map([[A.id,0]]), prev=new Map(), done=new Set(); const pq=[[0,A.id]];
    while(pq.length){ pq.sort((a,b)=>a[0]-b[0]); const [d,u]=pq.shift(); if(done.has(u)) continue; done.add(u); if(u===B.id) break;
      for(const v of nbrs(u)){ if(banned.has(u+'|'+v)||banned.has(v+'|'+u)) continue; const c=cost(u,v); if(!isFinite(c)) continue;
        const nd=d+c; if(nd<(dist.get(v)??Infinity)){dist.set(v,nd);prev.set(v,u);pq.push([nd,v])} } }
    if(!dist.has(B.id)) return null; const p=[B.id]; while(p[0]!==A.id) p.unshift(prev.get(p[0])); return {p,c:dist.get(B.id)} };
  const first=dijkstra(new Set()); if(!first){ $('paths').innerHTML='<span class="muted">no path at this evidence level</span>'; return }
  const found=[first], seen=new Set([first.p.join('>')]);
  for(let i=0;i<first.p.length-1 && found.length<6;i++){ const r=dijkstra(new Set([first.p[i]+'|'+first.p[i+1]])); if(r && !seen.has(r.p.join('>'))){seen.add(r.p.join('>'));found.push(r)} }
  found.sort((a,b)=>a.c-b.c); const top=found.slice(0,3);
  P.nodes=new Set(top.flatMap(r=>r.p)); P.edges=new Set(top.flatMap(r=>r.p.slice(1).flatMap((v,i)=>edgeKeysBetween(r.p[i],v))));
  $('paths').innerHTML=top.map((r,k)=>'<div class="path">'+`<b>#${k+1}</b> · ${r.p.length-1} hops<br>`+r.p.map((v,i)=>{ if(i===0) return esc(ents[v].name);
    const L=bestLink(r.p[i-1],v); const rel=L?(L.dir==='out'?` —${L.e.relation}→ `:` ←${L.e.relation}— `):' — ';
    return `<span class="muted">${esc(rel)}</span>${L?badge(L.e.status):''} ${esc(ents[v].name)}` }).join('')+'</div>').join('');
  if(V.level!=='all'){ V.level='all'; resetFocus(); crumbs(); setPositions(ORIG) } updateShown(); renderer.refresh() }
function clearPath(quiet){ P.nodes=new Set(); P.edges=new Set(); if(!quiet){ $('paths').innerHTML=''; renderer.refresh() } }

// ---------- renderer ----------
const renderer = new SigmaCls(graph, $('sg'), {
  renderEdgeLabels:false, enableEdgeEvents:true, defaultEdgeType:'arrow', zIndex:true,
  labelRenderedSizeThreshold:6, labelDensity:0.8, labelGridCellSize:60, labelFont:'system-ui, sans-serif', labelSize:12,
  labelColor:{color:css('--ink')}, defaultNodeColor:'#999', minCameraRatio:0.02, maxCameraRatio:4,
  nodeReducer:(n,a)=>{ const r={...a};
    if(V.level==='map'){ r.hidden=true; return r }
    if(V.level==='seg' && !F.node){ if(!V.members.has(n)){ r.hidden=true; return r }
      const f=state.hover; if(f && n!==f && !graph.areNeighbors(f,n)){ r.color=css('--fade'); r.label='' } else r.forceLabel=true; return r }
    if(F.node){ if(!F.shown.has(n)){r.hidden=true;return r}
      if(state.hover && state.hover!==n && !graph.areNeighbors(state.hover,n)){ r.color=css('--fade'); r.label='' }
      else if(F.labels.has(n)||state.hover===n||(state.hover&&graph.areNeighbors(state.hover,n))) r.forceLabel=true;
      if(n===F.node){ r.highlighted=true; r.zIndex=3 } return r }
    if(!SHOWN.has(n)){r.hidden=true;return r}
    if(SEL.node && !P.nodes.size && !state.hover){ if(n===SEL.node){ r.highlighted=true; r.forceLabel=true; r.zIndex=3; r.size=(a.size||4)+6 }
      else if(SEL.nbrs.has(n)){ r.forceLabel=true; r.zIndex=2 } else { r.color=css('--fade'); r.label=''; r.zIndex=0; r.size=Math.max(1.2,(a.size||3)*0.45) } return r }
    if(P.nodes.size){ if(!P.nodes.has(n)){ r.color=css('--fade'); r.label='' } else { r.forceLabel=true; r.zIndex=3 } return r }
    const f=state.hover;
    if(f && n!==f && !graph.areNeighbors(f,n)){ r.color=css('--fade'); r.label=''; r.zIndex=0 }
    else if(f){ r.forceLabel=true; r.zIndex=2 }
    if(seeds.has(n)){ r.forceLabel=r.forceLabel||!f; r.zIndex=Math.max(r.zIndex||0,1) }
    if(state.hits.has(n)){ r.highlighted=true; r.forceLabel=true }
    return r },
  edgeReducer:(ed,a)=>{ const r={...a}; const s=graph.source(ed), t=graph.target(ed);
    if(V.level==='map'){ r.hidden=true; return r }
    if(V.level==='seg' && !F.node){ if(!V.members.has(s)||!V.members.has(t)||a.rank<state.min){ r.hidden=true; return r }
      const f=state.hover; if(f && s!==f && t!==f) r.hidden=true; return r }
    if(a.rank<state.min || !state.on.has(ents[s].type) || !state.on.has(ents[t].type)){r.hidden=true;return r}
    if(F.node){ if(!F.shown.has(s)||!F.shown.has(t)){r.hidden=true;return r}
      if(!F.tree.has(ed)){ if(!$('cross').checked){r.hidden=true;return r} r.color=css('--fade') }
      if(state.hover && s!==state.hover && t!==state.hover) r.hidden=true; return r }
    if(!SHOWN.has(s)||!SHOWN.has(t)){r.hidden=true;return r}
    if(SEL.node && !P.nodes.size && !state.hover){ if(s===SEL.node||t===SEL.node){ r.color=alpha(a.color,0.7); r.zIndex=2 } else { r.color='rgba(120,132,148,0.10)'; r.size=0.3 } return r }
    if(!P.nodes.size && !state.hover) r.color=EDGE_QUIET;
    if(P.nodes.size){ if(!P.edges.has(ed)) r.hidden=true; else { r.size=(a.size||1)+2.5; r.zIndex=3 } return r }
    const f=state.hover; if(f && s!==f && t!==f) r.hidden=true; return r }
});
window.renderer = renderer;
let zT=null; renderer.getCamera().on('updated',()=>{ if(V.level!=='all'||F.node) return; clearTimeout(zT); zT=setTimeout(()=>{ const before=SHOWN.size; updateShown(); if(SHOWN.size!==before) renderer.refresh() },90) });

// ---------- overlay: segment bubbles, lens group labels, lane labels ----------
function hull(pts){ if(pts.length<3) return pts; pts=pts.slice().sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
  const cr=(o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]); const lo=[],up=[];
  for(const p of pts){ while(lo.length>=2&&cr(lo[lo.length-2],lo[lo.length-1],p)<=0) lo.pop(); lo.push(p) }
  for(const p of pts.slice().reverse()){ while(up.length>=2&&cr(up[up.length-2],up[up.length-1],p)<=0) up.pop(); up.push(p) }
  return lo.slice(0,-1).concat(up.slice(0,-1)) }
function overlay(){ const svg=$('ov'); let h='';
  const ink=css('--ink'), muted=css('--muted');
  if(V.level==='map'){ const W=svg.clientWidth||800, H=svg.clientHeight||600, S=0.40*Math.min(W,H), cx=W/2, cy=H/2+14;
    const P2=c=>[cx+c.x*S, cy-c.y*S], byId=Object.fromEntries(SM.nodes.map(c=>[c.id,c])), mxN=Math.max(1,...SM.links.map(l=>l.n)), mxS=Math.max(1,...SM.nodes.map(c=>c.size));
    const R=c=>12+40*Math.sqrt(c.size/mxS), hov=state.mapHover;
    for(const l of SM.links){ const A=byId[l.a], B=byId[l.b]; if(!A||!B) continue; const [x1,y1]=P2(A), [x2,y2]=P2(B), on=hov===l.a||hov===l.b;
      h+=`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${on?ink:muted}" stroke-opacity="${hov===undefined||hov===null?0.25:(on?0.8:0.06)}" stroke-width="${1+5*l.n/mxN}"/>`;
      if(on) h+=`<text x="${(x1+x2)/2}" y="${(y1+y2)/2}" text-anchor="middle" font-size="10.5" fill="${ink}" paint-order="stroke" stroke="${css('--bg')}" stroke-width="3">${esc(l.rel.replace(/_/g,' '))} · ${l.n}</text>` }
    for(const c of SM.nodes){ const [x,y]=P2(c), r=R(c), col=PALETTE[c.id%PALETTE.length], dim=hov!==undefined&&hov!==null&&hov!==c.id&&!SM.links.some(l=>(l.a===hov&&l.b===c.id)||(l.b===hov&&l.a===c.id));
      h+=`<g style="pointer-events:auto;cursor:pointer" opacity="${dim?0.25:1}" onclick="go('seg=${c.id}')" onmouseenter="state.mapHover=${c.id};overlay()" onmouseleave="state.mapHover=null;overlay()">
        <title>${esc(c.name)} · ${c.size} members\n${esc(c.top.join(', '))}\n${esc(Object.entries(c.types).map(([t,n])=>t+' '+n).join(' · '))}</title>
        <circle cx="${x}" cy="${y}" r="${r}" fill="${col}" fill-opacity="0.18" stroke="${col}" stroke-width="1.6"/>
        <text x="${x}" y="${y+3}" text-anchor="middle" font-size="${r>30?12:10.5}" font-weight="700" fill="${ink}" paint-order="stroke" stroke="${css('--bg')}" stroke-width="3">${esc(c.name)}</text>
        <text x="${x}" y="${y+16}" text-anchor="middle" font-size="10" fill="${muted}">${c.size}</text></g>` }
    svg.innerHTML=h; return }
  if(F.node){ for(const L of F.lensLabels){ const v=renderer.graphToViewport({x:L.x,y:L.y}); if(!isFinite(v.x)||!isFinite(v.y)) continue;
      h+=`<text x="${v.x}" y="${v.y}" text-anchor="middle" font-size="11" font-weight="700" fill="${muted}" style="text-transform:uppercase;letter-spacing:.05em">${esc(L.text)}</text>` } }
  else if($('layout').value==='lanes'){ LANES.forEach((l,i)=>{ const v=renderer.graphToViewport({x:-2.05,y:(LANES.length/2-i)*0.55});
      h+=`<text x="${Math.max(8,v.x-6)}" y="${v.y}" text-anchor="end" font-size="11" font-weight="700" fill="${muted}">${l.toUpperCase()}</text>` }) }
  if(V.level==='all' && !F.node && !P.nodes.size && $('hulls').checked && $('layout').value==='force'){
    const byC=new Map(); graph.forEachNode((n,a)=>{ if(!state.visible.has(n)) return; const c=ents[n].community; if(!byC.has(c)) byC.set(c,[]);
      const v=renderer.graphToViewport({x:a.x,y:a.y}); byC.get(c).push([v.x,v.y]) });
    (DATA.communities||[]).filter(c=>c.size>=6).slice(0,16).forEach(c=>{ const pts=byC.get(c.id)||[]; if(pts.length<4) return;
      const H=hull(pts), col=PALETTE[c.id%PALETTE.length]; const cx=pts.reduce((s,p)=>s+p[0],0)/pts.length, top=Math.min(...pts.map(p=>p[1]));
      h+=`<path d="M${H.map(p=>p.join(',')).join('L')}Z" fill="${col}" fill-opacity="0.06" stroke="${col}" stroke-opacity="0.35" stroke-width="1.2" stroke-linejoin="round"/>`;
      h+=`<text x="${cx}" y="${top-8}" text-anchor="middle" font-size="12" font-weight="700" fill="${col}">${esc(c.name)}</text>` }) }
  svg.innerHTML=h }
renderer.on('afterRender', overlay); window.addEventListener('resize', overlay);

// ---------- events ----------
renderer.on('enterNode',({node})=>{state.hover=node; renderer.refresh()});
renderer.on('leaveNode',()=>{state.hover=null; renderer.refresh()});
renderer.on('clickNode',({node})=>go(node));
renderer.on('clickEdge',({edge})=>{ $('info').innerHTML=edgeHtml(edge) });
renderer.on('enterEdge',({edge,event})=>{ const s=graph.source(edge), t=graph.target(edge); const list=[...(DIR[s+'>'+t]||[])];
  const tip=$('tip'); tip.innerHTML=list.map(e=>`${badge(e.status)} <b>${esc(ents[e.head].name)}</b> —${esc(e.relation)}→ <b>${esc(ents[e.tail].name)}</b> <span class="muted">strength ${e.strength}</span>`).join('<br>');
  tip.style.left=(event.x+14)+'px'; tip.style.top=(event.y+10)+'px'; tip.style.display='block' });
renderer.on('leaveEdge',()=>{ $('tip').style.display='none' });
renderer.on('doubleClickStage',()=>{ if(F.node) clearFocus() }); renderer.on('clickStage',()=>{ if(SEL.node && V.level==='all' && !F.node) go('all') });
document.addEventListener('keydown',ev=>{ if(ev.key!=='Escape') return; if(F.node) clearFocus(); else if(P.nodes.size) clearPath(); else if(SEL.trail.length>1) go(SEL.trail[SEL.trail.length-2]); else if(SEL.node||V.level!=='all') go('all') });
window.addEventListener('popstate', route);
$('clearFocus').addEventListener('click',clearFocus);
['hopN','dir','fan'].forEach(id=>$(id).addEventListener('change',()=>{ if(F.node) focusNode(F.node) }));
$('cross').addEventListener('change',()=>renderer.refresh());
$('hulls').addEventListener('change',()=>renderer.refresh());
$('layout').addEventListener('change',setLayout);
$('findPath').addEventListener('click',findPaths); $('clearPath').addEventListener('click',()=>clearPath());

function edgeHtml(id){ const e=edgesById[id]; if(!e) return '';
  return `<div><b>${esc(ents[e.head]?.name)}</b> —${esc(e.relation)}→ <b>${esc(ents[e.tail]?.name)}</b></div>
  <div style="margin:4px 0">${badge(e.status)} strength ${e.strength} · ${esc(e.claim_kind)}${e.contested?' · <b style="color:#d64545">contested</b>':''}${e.stale?' · stale':''}</div>
  <h2>Why this status</h2><ul>${(e.grade_reasons||[]).map(r=>`<li>${esc(r)}</li>`).join('')}</ul><h2>Evidence (${e.evidence.length})</h2>`+
  e.evidence.map(v=>`<div class="card"><span class="muted">${esc((v.observed_at||'').slice(0,10))} · ${esc(v.source_kind)} · ${esc(v.stance)} · verifier: ${v.entailed===null?'unchecked':(v.entailed?'entailed':'<b style="color:#d64545">not entailed</b>')}</span><q>${esc(v.quote)}</q><a href="${esc(v.source_url)}" target="_blank" rel="noopener">${esc(v.publisher)}</a></div>`).join('') }
function showNode(n){ const e=ents[n];
  const mine=DATA.edges.filter(x=>(x.head===n||x.tail===n)&&passes(x)).sort((a,b)=>b.strength-a.strength), groups=new Map();
  mine.forEach(x=>{ const k=(x.head===n?'→ ':'← ')+x.relation.replace(/_/g,' '); if(!groups.has(k)) groups.set(k,[]); groups.get(k).push(x) });
  const rows=[...groups.entries()].sort((a,b)=>b[1].length-a[1].length).map(([k,xs])=>`<details ${xs.length<=6?'open':''}><summary class="sec" style="cursor:pointer">${esc(k)} (${xs.length})</summary>`+
    xs.map(x=>{ const o=x.head===n?x.tail:x.head; return `<div class="row">${badge(x.status)} <a onclick="go('${q1(o)}')">${esc(ents[o]?.name)}</a> <span class="muted" style="cursor:pointer" onclick="$('info').innerHTML=edgeHtml('${q1(x.id)}')">evidence ›</span></div>` }).join('')+'</details>').join('');
  const src=new Map(); mine.forEach(x=>x.evidence.forEach(v=>{ const s=src.get(v.source_url)||{p:v.publisher,k:v.source_kind,n:0}; s.n++; src.set(v.source_url,s) }));
  const srcs=[...src.entries()].sort((a,b)=>b[1].n-a[1].n).slice(0,10).map(([u,s])=>`<div class="row"><a href="${esc(u)}" target="_blank" rel="noopener">${esc(s.p)}</a> <span class="muted">${esc(s.k)} · ${s.n} quote${s.n>1?'s':''} · ${esc(u.replace(/^https?:\/\/[^/]+/,'').slice(0,48))}</span></div>`).join('');
  $('info').innerHTML=`<b style="font-size:15px">${esc(e.name)}</b>
  <div style="margin:6px 0"><button class="btn" onclick="go('lens=${q1(n)}')">◎ relation lens</button> <button class="btn" onclick="$('pa').value=ents['${q1(n)}'].name;$('pb').focus()">⇢ path from here</button></div><span class="muted">${esc(e.type)}${e.org_kind?' · '+esc(e.org_kind):''}${e.layer?' · layer: '+esc(e.layer):''}${e.domain?' · '+esc(e.domain):''} · segment: ${esc((DATA.communities||[]).find(c=>c.id===e.community)?.name||'#'+e.community)}</span>
  <div class="muted" style="margin-top:4px">PPR ${(e.ppr||0).toFixed(4)} · PageRank ${(e.pagerank||0).toFixed(4)} · degree ${e.degree||0}</div>
  ${(e.aliases||[]).length>1?`<div class="muted">also: ${esc(e.aliases.filter(a=>a!==e.name).join(', '))}</div>`:''}
  <h2>Connections (${mine.length})</h2>${rows||'<span class="muted">none at this evidence level</span>'}
  <h2>Sources (${src.size} pages)</h2>${srcs||'<span class="muted">no sources</span>'}` }

// ---------- panels ----------
const types=[...new Set(DATA.entities.map(e=>e.type))].sort();
$('types').innerHTML=types.map(t=>`<label><input type="checkbox" checked value="${t}"><span class="sw" style="background:${TYPE_COLORS[t]||'#888'}"></span>${t} <span class="muted">(${DATA.entities.filter(e=>e.type===t).length})</span></label>`).join('');
$('names').innerHTML=DATA.entities.map(e=>`<option value="${esc(e.name)}">`).join('');
$('top').innerHTML=[...DATA.entities].sort((a,b)=>(b.ppr||0)-(a.ppr||0)).slice(0,15)
  .map((e,i)=>`<div class="row" onclick="go('${q1(e.id)}')">${i+1}. <span class="sw" style="background:${TYPE_COLORS[e.type]}"></span> ${esc(e.name)} <span class="muted">${(e.ppr||0).toFixed(3)}</span></div>`).join('');
$('segs').innerHTML=(DATA.communities||[]).slice(0,18)
  .map(c=>`<div class="row" onclick="showSeg(${c.id})"><span class="sw" style="background:${PALETTE[c.id%PALETTE.length]}"></span> <b>${esc(c.name)}</b> · ${c.size}<br><span class="muted">${esc(c.top.join(', '))}</span></div>`).join('');
function showSeg(id){ go('seg='+id) }
$('q').addEventListener('keydown',ev=>{ if(ev.key!=='Enter') return; const s=ev.target.value.toLowerCase().trim();
  const m=DATA.entities.filter(e=>e.name.toLowerCase().includes(s)); state.hits=new Set(m.map(e=>e.id));
  if(m.length) go(m.sort((a,b)=>(b.ppr||0)-(a.ppr||0))[0].id); else renderer.refresh() });
$('q').addEventListener('input',ev=>{ if(!ev.target.value){state.hits=new Set();renderer.refresh()} });
['colorBy','sizeBy'].forEach(id=>$(id).addEventListener('change',restyle));
const refilter=()=>{ recompute(); if(F.node) focusNode(F.node) };
$('minStatus').addEventListener('change',refilter); $('types').addEventListener('change',refilter);
restyle(); recompute();
// ForceAtlas2 (Barnes-Hut, LinLog, hubs dissuaded) from the precomputed positions: spreads hubs and
// neighbourhoods so clusters read as clusters. Animated settle; synchronous with ?noanim.
function runLayout(done){ const L=window.graphologyLibrary && graphologyLibrary.layoutForceAtlas2;
  if(!L){ done(); return }
  const settings={...L.inferSettings(graph), barnesHutOptimize:true, linLogMode:true, outboundAttractionDistribution:true,
                  adjustSizes:false, gravity:1, scalingRatio:6, slowDown:4};
  const finish=()=>{ graph.forEachNode((n,a)=>{ ORIG[n]={x:a.x,y:a.y} }); BASE=ORIG; done() };
  if(location.search.includes('noanim')){ L.assign(graph,{iterations:180,settings}); return finish() }
  let left=180; const tick=()=>{ L.assign(graph,{iterations:6,settings}); left-=6; if(left>0) requestAnimationFrame(tick); else finish() };
  requestAnimationFrame(tick) }
runLayout(()=>{ updateShown(); renderer.refresh(); route() });
</script></body></html>"""


REPO = "https://github.com/prabakaranc98/connected-frontiers"


def _links(static: bool) -> str:
    if not static:
        return '<div class="muted" style="margin-top:4px"><a href="/">crawl monitor →</a></div>'
    return (f'<div class="muted" style="margin-top:6px;line-height:1.5">A knowledge graph of the frontier-AI ecosystem, '
            f'built by a PageRank-guided crawler; every edge keeps its quote and source. '
            f'<b>Status</b> = evidence, not truth: <i>claimed</i> (one source) → <i>confirmed</i> (the other party) → '
            f'<i>corroborated</i> (independent sources) → <i>verified</i> (primary registry). '
            f'<a href="{REPO}" target="_blank" rel="noopener">code, method and evaluation →</a></div>')


def write_explorer(graph: dict, path: Path, subtitle: str = "", static: bool = False) -> Path:
    """static=True: the public build (no local crawl-monitor link; adds an about line and the repo link)."""
    if graph["entities"] and "x" not in graph["entities"][0]:
        compute_layout(graph)
    graph = {**graph, "segment_map": segment_map(graph)}
    data = json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
    html = (TEMPLATE.replace("__DATA__", data).replace("__SUBTITLE__", subtitle).replace("__LINKS__", _links(static))
            .replace("__PALETTE__", json.dumps(PALETTE)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    return path
