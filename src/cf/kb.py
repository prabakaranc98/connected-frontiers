"""Versioned knowledge bases: every build becomes an immutable snapshot with a manifest.

data/kb/<version>/
  manifest.json     version, parent, created_at, git commit, counts, models, prompt hashes, seeds hash,
                    crawl stats, build timings
  graph.json        entities, edges (with evidence), communities, hierarchy
  docs/             documents.jsonl, chunks.jsonl, edge_chunks.jsonl, entity_chunks.jsonl (GraphRAG index)
  report.md|json    quality / cost report of this build
  er_report.json    entity-resolution decisions
data/kb/CURRENT     the version agents use by default (override with CF_KB=<version>)

Tasks, agent runs and releases record the KB version they were built on.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from cf import config

KB_ROOT = config.DATA / "kb"
GRAPH_DIR = config.DATA / "processed" / "graph"
DOCS_DIR = config.DATA / "processed" / "docs"


def _sha_text(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def _git_commit() -> str | None:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=config.ROOT, capture_output=True,
                               text=True, check=False).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def current() -> str | None:
    env = os.environ.get("CF_KB")
    if env:
        return env
    f = KB_ROOT / "CURRENT"
    return f.read_text().strip() if f.exists() else None


def path(version: str | None = None) -> Path | None:
    v = version or current()
    return KB_ROOT / v if v else None


def graph_path(version: str | None = None) -> Path:
    p = path(version)
    return p / "graph.json" if p and (p / "graph.json").exists() else GRAPH_DIR / "graph.json"


def docs_path(version: str | None = None) -> Path:
    p = path(version)
    return p / "docs" if p and (p / "docs").exists() else DOCS_DIR


def snapshot(note: str = "") -> dict:
    """Freeze the latest build (graph + docs index + reports) as a new KB version."""
    from cf.extract.llm import EXTRACT_SYSTEM, VERIFY_SYSTEM
    from cf.llm.client import role_chain

    g = json.loads((GRAPH_DIR / "graph.json").read_text())
    summary = json.loads((GRAPH_DIR / "summary.json").read_text()) if (GRAPH_DIR / "summary.json").exists() else {}
    version = datetime.now(UTC).strftime("v%Y%m%d-%H%M")
    dst = KB_ROOT / version
    dst.mkdir(parents=True, exist_ok=False)
    for name in ("graph.json", "report.md", "report.json", "er_report.json", "summary.json", "pages.json"):
        if (GRAPH_DIR / name).exists():
            shutil.copy2(GRAPH_DIR / name, dst / name)
    if DOCS_DIR.exists():
        shutil.copytree(DOCS_DIR, dst / "docs")
    crawl_state = config.DATA / "interim" / "frontier_state.json"
    crawl = json.loads(crawl_state.read_text()).get("stats", {}) if crawl_state.exists() else {}
    docs_rows = {f.stem: sum(1 for _ in f.open()) for f in (dst / "docs").glob("*.jsonl")} if (dst / "docs").exists() else {}
    manifest = {
        "version": version, "parent": current(), "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(), "note": note,
        "counts": {"entities": len(g["entities"]), "edges": len(g["edges"]),
                   "verified_edges": sum(1 for e in g["edges"] if e["status"] == "verified"),
                   "segments": len(g.get("communities", [])), "hierarchy_links": len(g.get("hierarchy", [])),
                   "pages": summary.get("pages"), **{f"docs_{k}": v for k, v in docs_rows.items()}},
        "models": {r: role_chain(r) for r in ("extract", "verify", "verify_escalate", "er_judge", "reason")},
        "prompts": {"extract": _sha_text(EXTRACT_SYSTEM), "verify": _sha_text(VERIFY_SYSTEM)},
        "seeds_sha": _sha_text((config.CONFIGS / "seeds.yaml").read_text()),
        "crawl": {k: crawl.get(k) for k in ("noise", "generic_dropped", "errors") if k in crawl}
                 | {"batches": len(crawl.get("history", []))},
        "build": summary.get("timings"),
    }
    (dst / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (KB_ROOT / "CURRENT").write_text(version)
    return manifest


def list_versions() -> list[dict]:
    out = []
    for d in sorted(KB_ROOT.glob("v*")):
        m = json.loads((d / "manifest.json").read_text()) if (d / "manifest.json").exists() else {}
        out.append({"version": d.name, "created_at": m.get("created_at"), "parent": m.get("parent"),
                    **(m.get("counts") or {}), "note": m.get("note"), "current": d.name == current()})
    return out


def diff(a: str, b: str) -> dict:
    ga, gb = (json.loads((KB_ROOT / v / "graph.json").read_text()) for v in (a, b))
    ea, eb = {e["id"] for e in ga["entities"]}, {e["id"] for e in gb["entities"]}
    xa, xb = {e["id"]: e for e in ga["edges"]}, {e["id"]: e for e in gb["edges"]}
    upgraded = [k for k in xa.keys() & xb.keys() if xa[k]["status"] != xb[k]["status"]]
    names = {e["id"]: e["name"] for e in gb["entities"]} | {e["id"]: e["name"] for e in ga["entities"]}
    return {"entities_added": len(eb - ea), "entities_removed": len(ea - eb),
            "edges_added": len(xb.keys() - xa.keys()), "edges_removed": len(xa.keys() - xb.keys()),
            "edges_status_changed": len(upgraded),
            "sample_new_entities": [names[i] for i in sorted(eb - ea)[:15]],
            "sample_status_changes": [f"{names.get(xb[k]['head'], '?')} —{xb[k]['relation']}→ {names.get(xb[k]['tail'], '?')}: "
                                      f"{xa[k]['status']} → {xb[k]['status']}" for k in upgraded[:10]]}
