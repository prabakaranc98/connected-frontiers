"""Hugging Face Hub adapter: org → offers → model; model → builds_on (derivation) → model;
model → trained_on → dataset. From the public Hub API, cached on disk, no LLM.

Trust note: Hub metadata (base_model, datasets) is declared by the uploader on an independent
registry. It is a primary record of what the publisher declares, strong for lineage, but not a
third-party audit. Graded `verified` with source_kind=independent_primary and the reason noted.
"""

from __future__ import annotations

import hashlib
import json
import re
import time

import httpx

from cf import config

API = "https://huggingface.co/api"
CACHE = config.DATA / "raw" / "hf"
DERIVATION = {"finetune": "fine_tune", "quantized": "quantize", "merge": "merge", "adapter": "adapter"}


def _get(path: str, params: dict | None = None):
    key = hashlib.sha256((path + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()[:24]
    f = CACHE / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text())
    headers = {"User-Agent": config.env("CF_USER_AGENT", "connected-frontiers-research-crawler/0.1")}
    r = None
    for attempt in range(6):                     # the Hub rate-limits bursts: back off instead of reading 429 as "nothing"
        try:
            r = httpx.get(API + path, params=params, headers=headers, timeout=25)
        except httpx.HTTPError:
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(60, 2 ** attempt * 3))
            continue
        break
    if r is None:
        return None
    time.sleep(0.3)
    CACHE.mkdir(parents=True, exist_ok=True)
    if r.status_code in (401, 404):                      # cache "does not exist" too (handle guesses mostly miss)
        f.write_text("null")
        return None
    if r.status_code != 200:
        return None
    f.write_text(r.text)
    return r.json()


def _short(repo: str) -> str:
    return repo.split("/", 1)[-1]


def rows_for_org(org_name: str, hf_org: str, k: int) -> list[dict]:
    rows: list[dict] = []
    models = _get("/models", {"author": hf_org, "sort": "downloads", "limit": k}) or []
    for m in models:
        repo = m["id"]
        info = _get(f"/models/{repo}") or {}
        url = f"https://huggingface.co/{repo}"
        rows.append({"head": org_name, "head_type": "org", "relation": "offers", "tail": _short(repo),
                     "tail_type": "model", "tail_alias": repo, "url": url,
                     "quote": f"{repo} is published by the {hf_org} organisation on the Hugging Face Hub",
                     "claim_kind": "relational", "attrs": {}})
        for tag in info.get("tags", []):
            parts = tag.split(":", 2)
            if parts[0] == "base_model" and len(parts) == 3:
                kind, base = parts[1], parts[2]
                if base == repo:
                    continue
                rows.append({"head": _short(repo), "head_type": "model", "head_alias": repo, "relation": "builds_on",
                             "tail": _short(base), "tail_type": "model", "tail_alias": base, "url": url,
                             "quote": f"model card metadata: {tag}", "claim_kind": "descriptive",
                             "attrs": {"derivation": DERIVATION.get(kind, kind)}})
            elif parts[0] == "dataset" and len(parts) == 2:
                rows.append({"head": _short(repo), "head_type": "model", "head_alias": repo, "relation": "trained_on",
                             "tail": parts[1].split("/")[-1], "tail_type": "dataset", "tail_alias": parts[1], "url": url,
                             "quote": f"model card metadata: {tag}", "claim_kind": "descriptive", "attrs": {}})
    return rows


def dataset_rows(org_name: str, hf_org: str, k: int) -> list[dict]:
    rows = []
    for d in _get("/datasets", {"author": hf_org, "sort": "downloads", "limit": k}) or []:
        repo = d["id"]
        rows.append({"head": org_name, "head_type": "org", "relation": "offers", "tail": _short(repo), "tail_type": "dataset",
                     "tail_alias": repo, "url": f"https://huggingface.co/datasets/{repo}",
                     "quote": f"dataset {repo} is published by the {hf_org} organisation on the Hugging Face Hub",
                     "claim_kind": "relational", "attrs": {}})
    return rows


# ---- auto-mapping KB orgs → Hub orgs (strict; ambiguous cases go to review, never guessed) ----------
MAP_FILE = config.DATA / "processed" / "hf_org_map.json"
_SUFFIX = re.compile(r"(?:\s+|-)(ai|labs?|inc\.?|corp(oration)?|research|technologies|team)$", re.IGNORECASE)


def _norm(name: str) -> str:
    n = (name or "").strip()
    for _ in range(2):
        n = _SUFFIX.sub("", n)
    return re.sub(r"[^a-z0-9]", "", n.casefold())


def _keys(name: str) -> set[str]:
    """Normalized forms: with and without a trailing 'AI' / 'Labs' / 'Research' … ('Nous Research' ~ 'NousResearch')."""
    full = re.sub(r"[^a-z0-9]", "", (name or "").casefold())
    return {k for k in (full, _norm(name)) if len(k) >= 3}


def map_org(name: str) -> dict:
    """→ {status: mapped|ambiguous|none, hf_org?, candidates}. Accept only an exact normalized full-name
    (or handle) match with published repos; prefer Hub-verified orgs, then clear dominance (≥ 5× repos)."""
    target = _keys(name)
    if not target:
        return {"status": "none", "candidates": []}
    seen: dict[str, dict] = {}
    for q in dict.fromkeys([name, _SUFFIX.sub("", name).strip()]):
        for o in (_get("/quicksearch", {"q": q, "type": "org", "limit": 8}) or {}).get("orgs", []):
            seen.setdefault(o["name"], o)
    words = re.findall(r"[A-Za-z0-9]+", name)                # search can miss the canonical handle: try it directly
    for h in dict.fromkeys(["".join(words), "-".join(words).lower(), "".join(words).lower()]):
        if h and h not in seen and (_get(f"/organizations/{h}/overview") or {}).get("name"):
            seen[h] = {"name": h}
    cands, canon = [], set()
    for handle, o in seen.items():
        ov = _get(f"/organizations/{handle}/overview") or {}
        handle = ov.get("name") or handle
        if handle.casefold() in canon:                       # Hub handles are case-insensitive
            continue
        canon.add(handle.casefold())
        by_name = bool(target & _keys(ov.get("fullname") or o.get("fullname") or ""))
        by_handle = re.sub(r"[^a-z0-9]", "", handle.casefold()) in target     # Hub side: full handle, never stripped
        one_word = len(re.findall(r"[A-Za-z0-9]+", name)) == 1
        established = int(ov.get("numModels") or 0) + int(ov.get("numDatasets") or 0) >= 20
        exact = handle.casefold() == re.sub(r"[^A-Za-z0-9]", "", name).casefold()
        if one_word and not ov.get("isVerified") and not (exact and established):   # keeps Qwen, drops 'alignment'
            continue
        if not (by_handle or (by_name and ov.get("isVerified"))):    # unverified orgs must match by handle
            continue
        repos = int(ov.get("numModels") or 0) + int(ov.get("numDatasets") or 0)
        if repos:
            cands.append({"hf_org": handle, "fullname": ov.get("fullname"), "verified": bool(ov.get("isVerified")),
                          "models": ov.get("numModels", 0), "datasets": ov.get("numDatasets", 0), "repos": repos})
    if not cands:
        return {"status": "none", "candidates": []}
    ver = [c for c in cands if c["verified"]]
    pool = ver if len(ver) == 1 else (ver or cands)
    pool = sorted(pool, key=lambda c: -c["repos"])
    if len(pool) == 1 or pool[0]["repos"] >= 5 * max(pool[1]["repos"], 1):
        return {"status": "mapped", "hf_org": pool[0]["hf_org"], "candidates": cands,
                "why": "single verified match" if len(ver) == 1 else ("single match" if len(cands) == 1 else "dominant match")}
    return {"status": "ambiguous", "candidates": cands}


def auto_map(entities: dict, limit: int | None = None) -> dict:
    """Map AI-relevant KB orgs (and orgs already offering models/datasets) to Hub orgs. Cached by the API cache."""
    from cf.crawl.frontier import AI_KINDS, AI_LAYERS
    orgs = [e for e in entities.values() if e["type"] == "org"
            and (e.get("org_kind") in AI_KINDS or e.get("layer") in AI_LAYERS)]
    orgs = sorted(orgs, key=lambda e: -(e.get("ppr") or 0))[:limit] if limit else orgs
    exclude = set(config.load_yaml("adapters.yaml").get("huggingface", {}).get("exclude") or [])
    out = {"mapped": {}, "ambiguous": {}, "excluded": sorted(exclude), "checked": 0}
    for e in orgs:
        if e["name"] in exclude:
            continue
        r = map_org(e["name"])
        out["checked"] += 1
        if r["status"] == "mapped":
            out["mapped"][e["name"]] = {"hf_org": r["hf_org"], "why": r["why"]}
        elif r["status"] == "ambiguous":
            out["ambiguous"][e["name"]] = r["candidates"]
    MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    MAP_FILE.write_text(json.dumps(out, indent=1))
    return out


def all_rows(entities: dict | None = None) -> list[dict]:
    """Manual mapping (configs/adapters.yaml) always wins; auto-mapped orgs are added when entities are given."""
    cfg = config.load_yaml("adapters.yaml").get("huggingface", {})
    if not cfg.get("enabled"):
        return []
    mapping = dict(cfg.get("orgs") or {})
    if entities is not None and cfg.get("auto_map", True):
        auto = auto_map(entities)
        taken = set(mapping.values())
        for name, m in auto["mapped"].items():
            if name not in mapping and m["hf_org"] not in taken:
                mapping[name] = m["hf_org"]
                taken.add(m["hf_org"])
    rows: list[dict] = []
    k, kd = int(cfg.get("models_per_org", 12)), int(cfg.get("datasets_per_org", 6))
    for org_name, hf_org in mapping.items():
        rows += rows_for_org(org_name, hf_org, k) + dataset_rows(org_name, hf_org, kd)
    return rows
