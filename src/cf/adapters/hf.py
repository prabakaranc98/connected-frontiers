"""Hugging Face Hub adapter: org → offers → model; model → builds_on (derivation) → model;
model → trained_on → dataset. From the public Hub API, cached on disk, no LLM.

Trust note: Hub metadata (base_model, datasets) is declared by the uploader on an independent
registry. It is a primary record of what the publisher declares, strong for lineage, but not a
third-party audit. Graded `verified` with source_kind=independent_primary and the reason noted.
"""

from __future__ import annotations

import hashlib
import json
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
    r = httpx.get(API + path, params=params, headers=headers, timeout=25)
    time.sleep(0.3)
    if r.status_code != 200:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
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


def all_rows() -> list[dict]:
    cfg = config.load_yaml("adapters.yaml").get("huggingface", {})
    if not cfg.get("enabled"):
        return []
    rows: list[dict] = []
    for org_name, hf_org in (cfg.get("orgs") or {}).items():
        rows += rows_for_org(org_name, hf_org, int(cfg.get("models_per_org", 12)))
    return rows
