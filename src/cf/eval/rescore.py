"""Re-score changed components against a frozen silver set (cheap: only changed decisions are re-run)."""

from __future__ import annotations

import json
from collections import defaultdict

from cf import config
from cf.crawl.fetch import Fetcher
from cf.extract.llm import EscalatingVerifier, Verdict, Verifier, XTriple
from cf.llm.client import AUTO, LLM, role_chain
from cf.resolve.er import Candidate, adjudicate, strict_key

GOLD = config.EVAL / "gold"


def _vmetrics(rows: list[tuple[bool, str]]) -> dict:
    tp = sum(1 for p, s in rows if p and s == "yes")
    fp = sum(1 for p, s in rows if p and s == "no")
    fn = sum(1 for p, s in rows if not p and s == "yes")
    tn = sum(1 for p, s in rows if not p and s == "no")
    n = len(rows) or 1
    return {"accuracy": round((tp + tn) / n, 3), "false_support_rate": round(fp / max(fp + tn, 1), 3),
            "false_reject_rate": round(fn / max(fn + tp, 1), 3), "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}}


def verification(version: str = "v1") -> dict:
    items = [json.loads(line) for line in (GOLD / f"silver_verify_{version}.jsonl").read_text().split("\n") if line.strip()]
    items = [it for it in items if it.get("silver")]
    esc_cfg = config.load_yaml("models.yaml").get("escalation", {})
    primary = Verifier(role_chain("verify")[0], AUTO)
    secondary = Verifier(role_chain("verify_escalate")[0], AUTO)
    ev = EscalatingVerifier(primary, secondary, set(esc_cfg.get("risky_relations", [])), esc_cfg.get("min_quote_words", 5))
    fetcher, by_url = Fetcher(), defaultdict(list)
    for it in items:
        by_url[it["url"]].append(it)
    spend0 = LLM.spent_usd
    after: dict[str, bool] = {}
    for url, group in by_url.items():
        page = fetcher.fetch(url)
        triples = [XTriple(**g["triple"]) for g in group]
        first = [Verdict(i=i, entailed=bool(g["prod_entailed"]), stance=g["prod_stance"]) for i, g in enumerate(group)]
        final = ev.combine(triples, page, first) if page else first
        for g, v in zip(group, final, strict=True):
            after[g["id"]] = bool(v and v.entailed)
    before = _vmetrics([(bool(it["prod_entailed"]), it["silver"]) for it in items])
    now = _vmetrics([(after[it["id"]], it["silver"]) for it in items])
    return {"items": len(items), "before": before, "after_escalation": now, "escalated": ev.escalated,
            "overturned": ev.overturned, "secondary": secondary.llm.model, "spend_usd": round(LLM.spent_usd - spend0, 4)}


def entity_resolution(version: str = "v1") -> dict:
    items = [json.loads(line) for line in (GOLD / f"silver_er_{version}.jsonl").read_text().split("\n") if line.strip()]
    items = [d for d in items if d.get("silver")]
    judge = role_chain("er_judge")[0]
    spend0 = LLM.spent_usd
    to_judge = [d for d in items if strict_key(d["name_a"]) != strict_key(d["name_b"])]
    ents = {d[s]: {"name": d[f"name_{s}"], "type": d[f"type_{s}"]} for d in to_judge for s in ("a", "b")}
    quotes = {d[s]: d.get(f"quotes_{s}", []) for d in to_judge for s in ("a", "b")}
    js = adjudicate([Candidate(d["a"], d["b"], d["reason"], 0, False) for d in to_judge], ents, quotes, judge,
                    reasoning_max_tokens=AUTO) if to_judge else []
    new = {d["id"]: j.verdict for d, j in zip(to_judge, js, strict=True)}
    for d in items:
        new.setdefault(d["id"], "same")          # strict-key pairs auto-merge

    def m(pred):
        merges = [d for d in items if pred(d) == "same"]
        return {"accuracy": round(sum(1 for d in items if pred(d) == d["silver"]) / len(items), 3),
                "false_merge_rate": round(sum(1 for d in merges if d["silver"] != "same") / max(len(merges), 1), 3),
                "merges": len(merges)}
    return {"items": len(items), "before": m(lambda d: d["verdict"]), "after_rule_fix": m(lambda d: new[d["id"]]),
            "spend_usd": round(LLM.spent_usd - spend0, 4)}
