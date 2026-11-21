"""Rule-based scoring for v0 use-case tasks (no LLM judge yet, so no judge bias).

Per run:
  key_score       – the use case's main metric (recall, precision@3, label accuracy, nDCG@5)
  citation_valid  – share of cited edge ids that exist in the KG and touch the item they support
  grounded_items  – share of output items that resolve to a KG entity
"""

from __future__ import annotations

import math

from cf.agent.kg import KG

STRONG, CLAIM, NONE = {"verified", "corroborated"}, {"confirmed", "claimed", "self-claimed", "self_claimed"}, {"unsupported"}


def _bucket(label: str) -> str:
    lab = (label or "").strip().lower().replace(" ", "-")
    if lab in STRONG:
        return "strong"
    if lab in NONE:
        return "none"
    if lab in {x.replace("_", "-") for x in CLAIM}:
        return "claim"
    return "?"


def _resolve(kg: KG, name: str, etype: str | None = None) -> str | None:
    m = kg.match(name or "", k=1, etype=etype)
    return m[0][1] if m and m[0][0] >= 0.75 else None


def _citations(kg: KG, items: list[dict], ids: list[str | None]) -> tuple[int, int]:
    ok = tot = 0
    for it, eid in zip(items, ids, strict=True):
        for c in it.get("edge_ids") or []:
            tot += 1
            e = kg.edges.get(str(c).strip("[] "))
            if e and (eid is None or eid in (e["head"], e["tail"])):
                ok += 1
    return ok, tot


def score(kg: KG, task: dict, run: dict) -> dict:
    out = run.get("output") or {}
    items = [it for it in out.get("items") or [] if isinstance(it, dict)]
    uc, key = task["use_case"], task["key"]
    resolved = [_resolve(kg, it.get("name", "")) for it in items]
    s: dict = {"n_items": len(items), "grounded_items": round(sum(1 for r in resolved if r) / max(len(items), 1), 3)}

    if uc == "U1_landscape":
        got = {r for r in resolved if r}
        s["key_score"] = round(len(got & set(key["players"])) / len(key["players"]), 3)           # recall of key players
        s["in_segment_precision"] = round(len(got & set(key["segment_ids"])) / max(len(got), 1), 3)
    elif uc == "U2_shortlist":
        top = [r for r in resolved if r][:3]
        s["key_score"] = round(sum(1 for r in top if r in key["orgs"]) / 3, 3)                    # precision@3
    elif uc == "U5_claim_audit":
        gold = key["labels"]
        pred = {}
        for it in items:
            digits = "".join(ch for ch in str(it.get("name", "")) if ch.isdigit())
            if digits:
                pred[int(digits) - 1] = it.get("label", "")
        right = sum(1 for i, g in enumerate(gold) if _bucket(pred.get(i, "")) == _bucket(g))
        s["key_score"] = round(right / len(gold), 3)                                               # 3-bucket accuracy
        s["exact_label_acc"] = round(sum(1 for i, g in enumerate(gold)
                                         if (pred.get(i, "") or "").lower().replace(" ", "-").replace("self-claimed", "claimed") == g)
                                     / len(gold), 3)
        resolved = [None] * len(items)
    elif uc == "U6_targeting":
        ranked = key["ranked_orgs"]
        rel = {o: (len(ranked) - i) / len(ranked) for i, o in enumerate(ranked)}
        top = [r for r in resolved if r][:5]
        dcg = sum(rel.get(r, 0) / math.log2(i + 2) for i, r in enumerate(top))
        idcg = sum(sorted(rel.values(), reverse=True)[i] / math.log2(i + 2) for i in range(min(5, len(rel))))
        s["key_score"] = round(dcg / idcg, 3) if idcg else 0.0                                     # nDCG@5
    ok, tot = _citations(kg, items, resolved)
    s["citations"] = tot
    s["citation_valid"] = round(ok / tot, 3) if tot else None
    return s
