"""Silver label sets by ensemble vote, and the production components measured against them.

- Judges: several models from different families label the same items independently.
- Production components (the pipeline's verifier and ER judge) are NOT judges; they are evaluated.
- Majority (>= 3 of 4) → silver label. Splits → dispute queue for the owner (eval/gold/owner_review_*.md).

Silver is not gold: LLM judges share biases. The owner's review of disputes and a small random
spot-check estimate silver accuracy itself.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from rich.console import Console

from cf import config
from cf.crawl.fetch import Fetcher
from cf.extract.llm import Verifier, XTriple
from cf.llm.client import LLM
from cf.resolve.er import Candidate, adjudicate

GOLD = config.EVAL / "gold"
console = Console()

# Recent, small, different families (owner preference: no gpt-oss). Production verifier (DeepSeek) is NOT a judge.
JUDGES = [("qwen/qwen3.5-35b-a3b", 0), ("thinkingmachines/inkling-2-small", 800),
          ("nvidia/nemotron-3.5-lightning", 0), ("mistralai/mistral-small-2603", 0)]


# ---- helpers ------------------------------------------------------------------------------
def fleiss_kappa(rows: list[list[str]], categories: list[str]) -> float:
    """rows = per item, the list of labels from each rater (same number of raters per item)."""
    rows = [r for r in rows if len(r) == len(rows[0])] if rows else []
    if not rows:
        return float("nan")
    n = len(rows[0])
    p_j = {c: sum(r.count(c) for r in rows) / (len(rows) * n) for c in categories}
    P_i = [(sum(r.count(c) ** 2 for c in categories) - n) / (n * (n - 1)) for r in rows]
    P_bar, P_e = sum(P_i) / len(P_i), sum(v * v for v in p_j.values())
    return round((P_bar - P_e) / (1 - P_e), 3) if P_e < 1 else 1.0


def _majority(votes: list[str], need: int) -> str | None:
    if not votes:
        return None
    label, n = Counter(votes).most_common(1)[0]
    return label if n >= need else None


# ---- verification silver set ---------------------------------------------------------------
def sample_verify_items(n: int, seed: int = 7) -> list[dict]:
    from cf.cache import EXTRACT, LEGACY, VERIFY
    items = []
    ex_by_key = {f.stem: json.loads(f.read_text()) for f in EXTRACT.glob("*.json")} if EXTRACT.exists() else {}
    for f in (VERIFY.glob("*.json") if VERIFY.exists() else []):
        v = json.loads(f.read_text()); e = ex_by_key.get(v["extract_key"])
        if not e:
            continue
        for t, vd in zip(e["triples"], v["verdicts"], strict=True):
            if vd is not None:
                items.append({"url": e["url"], "triple": t, "prod_entailed": vd["entailed"], "prod_stance": vd["stance"]})
    if not items and LEGACY.exists():          # before the cache split
        for f in LEGACY.glob("*.json"):
            d = json.loads(f.read_text())
            for t, vd in zip(d["triples"], d["verdicts"], strict=True):
                if vd is not None:
                    items.append({"url": d["url"], "triple": t, "prod_entailed": vd["entailed"], "prod_stance": vd["stance"]})
    rnd = random.Random(seed)
    rnd.shuffle(items)
    by_rel: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_rel[it["triple"]["relation"]].append(it)
    out: list[dict] = []
    while len(out) < n and any(by_rel.values()):        # round-robin over relations = stratified
        for rel in list(by_rel):
            if by_rel[rel] and len(out) < n:
                out.append(by_rel[rel].pop())
    for i, it in enumerate(out):
        it["id"] = f"v{i:04d}"
    return out


def judge_verify(items: list[dict], judges=JUDGES) -> None:
    fetcher = Fetcher()
    by_url: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_url[it["url"]].append(it)
    pages = {u: fetcher.fetch(u) for u in by_url}

    def run(job):
        (model, r), url = job
        page, group = pages[url], by_url[url]
        if page is None:
            return
        try:
            verdicts = Verifier(model, r).verify([XTriple(**g["triple"]) for g in group], page)
        except RuntimeError as e:
            console.print(f"[red]{model} failed on {url}: {str(e)[:80]}[/]")
            return
        for g, v in zip(group, verdicts, strict=True):
            g.setdefault("votes", {})[model] = None if v is None else bool(v.entailed)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(run, [(j, u) for j in judges for u in by_url]))


def summarize_verify(items: list[dict], judges=JUDGES) -> dict:
    names = [m for m, _ in judges]
    rows, scored = [], []
    for it in items:
        votes = [it.get("votes", {}).get(m) for m in names]
        labels = ["yes" if v else "no" for v in votes if v is not None]
        it["silver"] = _majority(labels, need=3)
        it["agreement"] = f"{max(Counter(labels).values()) if labels else 0}/{len(labels)}"
        if len(labels) == len(names):
            rows.append(labels)
        if it["silver"] is not None:
            scored.append(it)
    tp = sum(1 for it in scored if it["prod_entailed"] and it["silver"] == "yes")
    fp = sum(1 for it in scored if it["prod_entailed"] and it["silver"] == "no")
    fn = sum(1 for it in scored if not it["prod_entailed"] and it["silver"] == "yes")
    tn = sum(1 for it in scored if not it["prod_entailed"] and it["silver"] == "no")
    per_judge = {}
    for m in names:   # leave-one-out: agreement of each judge with the majority of the OTHER judges
        agree = tot = 0
        for it in items:
            others = ["yes" if it["votes"].get(o) else "no" for o in names
                      if o != m and it.get("votes", {}).get(o) is not None]
            maj, mine = _majority(others, need=2), it.get("votes", {}).get(m)
            if maj is not None and mine is not None:
                tot += 1
                agree += ("yes" if mine else "no") == maj
        per_judge[m] = round(agree / tot, 3) if tot else None
    n_s = len(scored)
    return {
        "items": len(items), "silver_labelled": n_s, "disputed": len(items) - n_s,
        "fleiss_kappa_judges": fleiss_kappa(rows, ["yes", "no"]),
        "silver_entailed_share": round(sum(1 for it in scored if it["silver"] == "yes") / max(n_s, 1), 3),
        "production_verifier": {
            "accuracy": round((tp + tn) / max(n_s, 1), 3),
            "precision_entailed": round(tp / max(tp + fp, 1), 3), "recall_entailed": round(tp / max(tp + fn, 1), 3),
            "false_support_rate": round(fp / max(fp + tn, 1), 3), "false_reject_rate": round(fn / max(fn + tp, 1), 3),
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}},
        "judge_agreement_with_others": per_judge,
    }


# ---- ER silver set -----------------------------------------------------------------------------
def sample_er_items(n: int, seed: int = 7) -> list[dict]:
    rep = json.loads((config.DATA / "processed" / "graph" / "er_report.json").read_text())
    decisions = rep.get("decisions", [])
    rnd = random.Random(seed)
    rnd.shuffle(decisions)
    strata: dict[str, list[dict]] = defaultdict(list)
    for d in decisions:
        strata[f'{d["decided_by"]}:{d["verdict"]}'].append(d)
    out: list[dict] = []
    while len(out) < n and any(strata.values()):
        for k in list(strata):
            if strata[k] and len(out) < n:
                out.append(strata[k].pop())
    for i, d in enumerate(out):
        d["id"] = f"e{i:04d}"
    return out


def judge_er(items: list[dict], judges=JUDGES) -> None:
    ents = {}
    quotes = {}
    cands = []
    for d in items:
        for side in ("a", "b"):
            ents[d[side]] = {"name": d[f"name_{side}"], "type": d[f"type_{side}"]}
            quotes[d[side]] = d.get(f"quotes_{side}", [])
        cands.append(Candidate(d["a"], d["b"], d["reason"], 0.0, False))

    def run(judge):
        model, r = judge
        try:
            js = adjudicate(cands, ents, quotes, model, reasoning_max_tokens=r)
        except RuntimeError as e:
            console.print(f"[red]{model} failed on ER: {str(e)[:80]}[/]")
            return
        for d, j in zip(items, js, strict=True):
            d.setdefault("votes", {})[model] = j.verdict

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, judges))


def summarize_er(items: list[dict], judges=JUDGES) -> dict:
    names = [m for m, _ in judges]
    cats = ["same", "part_or_subtype", "different"]
    rows, scored = [], []
    for d in items:
        labels = [d.get("votes", {}).get(m) for m in names]
        labels = [x for x in labels if x]
        d["silver"] = _majority(labels, need=3)
        if len(labels) == len(names):
            rows.append(labels)
        if d["silver"]:
            scored.append(d)
    correct = sum(1 for d in scored if d["verdict"] == d["silver"])
    false_merge = sum(1 for d in scored if d["verdict"] == "same" and d["silver"] != "same")
    merges = sum(1 for d in scored if d["verdict"] == "same")
    conf = Counter((d["verdict"], d["silver"]) for d in scored)
    return {"items": len(items), "silver_labelled": len(scored), "disputed": len(items) - len(scored),
            "fleiss_kappa_judges": fleiss_kappa(rows, cats),
            "production_er": {"accuracy": round(correct / max(len(scored), 1), 3),
                              "false_merge_rate": round(false_merge / max(merges, 1), 3),
                              "confusion(prod,silver)": {f"{a}->{b}": c for (a, b), c in conf.items()}}}


# ---- orchestration -------------------------------------------------------------------------------
def run(n_verify: int = 200, n_er: int = 120, version: str = "v1") -> dict:
    GOLD.mkdir(parents=True, exist_ok=True)
    spend0 = LLM.spent_usd
    v_items = sample_verify_items(n_verify)
    console.print(f"verification items: {len(v_items)} → judging with {len(JUDGES)} models…")
    judge_verify(v_items)
    v_sum = summarize_verify(v_items)
    e_items = sample_er_items(n_er)
    console.print(f"ER items: {len(e_items)} → judging…")
    judge_er(e_items)
    e_sum = summarize_er(e_items)
    with (GOLD / f"silver_verify_{version}.jsonl").open("w") as f:
        for it in v_items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    with (GOLD / f"silver_er_{version}.jsonl").open("w") as f:
        for d in e_items:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    summary = {"version": version, "judges": [m for m, _ in JUDGES], "verification": v_sum, "entity_resolution": e_sum,
               "spend_usd": round(LLM.spent_usd - spend0, 4)}
    (GOLD / f"silver_summary_{version}.json").write_text(json.dumps(summary, indent=1))
    _owner_review(v_items, e_items, version)
    return summary


def _owner_review(v_items: list[dict], e_items: list[dict], version: str) -> None:
    lines = [f"# Owner review queue: silver {version}", "",
             "Items where the judges split. Write your label in the last column (yes/no for verification;",
             "same/part_or_subtype/different for ER). These become gold.", "",
             "## Verification (does the quote, in source context, state the claim?)", "",
             "| id | claim | quote | source | votes | your label |", "|---|---|---|---|---|---|"]
    for it in v_items:
        if it["silver"] is None:
            t = it["triple"]
            votes = ", ".join(f"{m.split('/')[1][:12]}={'Y' if v else 'N'}" for m, v in it.get("votes", {}).items() if v is not None)
            lines.append(f"| {it['id']} | {t['head']} —{t['relation']}→ {t['tail']} | {t['quote'][:120].replace('|', '/')} | {it['url']} | {votes} | |")
    lines += ["", "## Entity resolution", "", "| id | A | B | type | votes | pipeline said | your label |", "|---|---|---|---|---|---|---|"]
    for d in e_items:
        if d["silver"] is None:
            votes = ", ".join(f"{m.split('/')[1][:12]}={v}" for m, v in d.get("votes", {}).items())
            lines.append(f"| {d['id']} | {d['name_a']} | {d['name_b']} | {d['type_a']} | {votes} | {d['verdict']} | |")
    (GOLD / f"owner_review_{version}.md").write_text("\n".join(lines) + "\n")


# ---- KB-level calibration: does the status ladder mean something? ---------------------------------
STRATA = {"unsupported": 25, "claimed": 30, "confirmed": 30, "corroborated": 30, "verified": 30}


def sample_edge_items(kb_version: str | None = None, strata: dict = STRATA, seed: int = 7) -> tuple[list[dict], dict]:
    """Edges of a KB version, stratified by status; each judged on its first page citation.
    Adapter-verified edges (structured API facts, no page quote) are counted, not judged."""
    from cf import kb
    g = json.loads(kb.graph_path(kb_version).read_text())
    names = {e["id"]: e for e in g["entities"]}
    rnd = random.Random(seed)
    by: dict[str, list] = defaultdict(list)
    adapter = 0
    for e in g["edges"]:
        page_ev = [x for x in e["evidence"] if not x["extractor_version"].startswith("adapter")]
        if not page_ev:
            adapter += 1
            continue
        by[e["status"]].append((e, page_ev[0]))
    out = []
    for st, n in strata.items():
        pool = by.get(st, [])
        rnd.shuffle(pool)
        for e, ev in pool[:n]:
            h, t = names[e["head"]], names[e["tail"]]
            out.append({"id": f"k{len(out):04d}", "edge_id": e["id"], "status": st, "url": ev["source_url"],
                        "triple": {"head": h["name"], "head_type": h["type"], "relation": e["relation"], "tail": t["name"],
                                   "tail_type": t["type"], "quote": ev["quote"], "claim_kind": e["claim_kind"]},
                        "prod_entailed": bool(ev["entailed"]), "prod_stance": ev["stance"]})
    return out, {"adapter_verified_edges_not_judged": adapter, "pool_sizes": {k: len(v) for k, v in by.items()}}


def run_kb(kb_version: str | None = None, n_er: int = 80, version: str = "kb") -> dict:
    """Scorecard layer 1 on one KB version: status calibration, verifier vs silver, ER vs silver."""
    from cf import kb
    v = kb_version or kb.current()
    spend0 = LLM.spent_usd
    items, meta = sample_edge_items(v)
    console.print(f"edge items: {len(items)} (stratified by status) → judging with {len(JUDGES)} models…")
    judge_verify(items)
    v_sum = summarize_verify(items)
    per_status = {}
    for st in STRATA:
        lab = [it["silver"] for it in items if it["status"] == st and it.get("silver")]
        per_status[st] = {"judged": len(lab), "silver_supported": round(sum(x == "yes" for x in lab) / len(lab), 3) if lab else None}
    e_items = sample_er_items(n_er)
    console.print(f"ER items: {len(e_items)} → judging…")
    judge_er(e_items)
    e_sum = summarize_er(e_items)
    tag = f"{version}_{v}"
    for name, rows in (("silver_edges", items), ("silver_er", e_items)):
        with (GOLD / f"{name}_{tag}.jsonl").open("w") as f:
            for it in rows:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    summary = {"kb_version": v, "judges": [m for m, _ in JUDGES], "status_calibration": per_status, **meta,
               "verification": v_sum, "entity_resolution": e_sum, "spend_usd": round(LLM.spent_usd - spend0, 4)}
    (GOLD / f"silver_summary_{tag}.json").write_text(json.dumps(summary, indent=1))
    _owner_review(items, e_items, tag)
    return summary
