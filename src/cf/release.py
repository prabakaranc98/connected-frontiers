"""Build the Hugging Face collection locally (push is a separate, explicit step).

data/release/<kb_version>/
  kb/            entities · edges · evidence (quotes ≤ 400 chars + URL) · documents (metadata only)
                 · chunk_index (offsets, no text) · communities · hierarchy
  tasks/         use-case tasks with answer keys computed on this KB (multi-turn ready: `turns`)
  trajectories/  agent runs: every step (tool, args, ids touched = traversal), final answer,
                 citations, scores, cost, latency, model, condition, KB version
  labels/        silver labels (4-judge votes) and owner gold when reviewed
  README.md      dataset card (configs, schema, licensing, canary)

Page text is NOT redistributed: passages are referenced by URL + offsets (rebuild with `cf docs`).
"""

from __future__ import annotations

import glob
import json
import re
import shutil
from pathlib import Path

from cf import config, kb

CANARY = "CONNECTED-FRONTIERS-CANARY 7f3c9a1e-do-not-train-on-eval"


def _w(path: Path, rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def _r(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().split("\n") if x.strip()] if path.exists() else []


def build(version: str | None = None) -> dict:
    v = version or kb.current()
    src = kb.path(v)
    out = config.DATA / "release" / v
    if out.exists() and out.parent == config.DATA / "release":     # generated output: rebuild from scratch
        shutil.rmtree(out)
    g = json.loads((src / "graph.json").read_text())
    docs = src / "docs"
    edge_chunk = {(r["edge_id"], r["quote"]): r["chunk_id"] for r in _r(docs / "edge_chunks.jsonl")}
    counts = {}

    counts["kg/entities"] = _w(out / "kg" / "entities.jsonl", (
        {"kb_version": v, "id": e["id"], "type": e["type"], "name": e["name"], "aliases": e.get("aliases", []),
         "org_kind": e.get("org_kind"), "layer": e.get("layer"), "domain": e.get("domain"),
         "segment": e.get("community"), "ppr": e.get("ppr"), "pagerank": e.get("pagerank")} for e in g["entities"]))
    counts["kg/edges"] = _w(out / "kg" / "edges.jsonl", (
        {"kb_version": v, "edge_id": e["id"], "head": e["head"], "relation": e["relation"], "tail": e["tail"],
         "claim_kind": e["claim_kind"], "status": e["status"], "strength": e["strength"], "contested": e["contested"],
         "stale": e["stale"], "attrs": e.get("attrs", {}), "grade_reasons": e.get("grade_reasons", []),
         "n_publishers": len({x["publisher"] for x in e["evidence"]})} for e in g["edges"]))
    (out / "kg").mkdir(parents=True, exist_ok=True)
    with (out / "kg" / "triples.tsv").open("w") as f:
        for e in g["edges"]:
            if e["status"] != "unsupported":
                f.write(f"{e['head']}\t{e['relation']}\t{e['tail']}\n")
    counts["kg/triples.tsv"] = sum(1 for e in g["edges"] if e["status"] != "unsupported")
    counts["kg/evidence"] = _w(out / "kg" / "evidence.jsonl", (
        {"kb_version": v, "edge_id": e["id"], "url": x["source_url"], "publisher": x["publisher"],
         "source_kind": x["source_kind"], "stance": x["stance"], "entailed": x["entailed"], "quote": x["quote"][:400],
         "observed_at": x["observed_at"], "extractor": x["extractor_version"], "verifier": x.get("verifier_version"),
         "chunk_id": edge_chunk.get((e["id"], x["quote"]))} for e in g["edges"] for x in e["evidence"]))
    counts["kg/documents"] = _w(out / "kg" / "documents.jsonl",
                                ({"kb_version": v, **{k: d[k] for k in ("doc_id", "url", "title", "publisher", "chars")}}
                                 for d in _r(docs / "documents.jsonl")))
    ent_by_chunk: dict[str, list[str]] = {}
    for r in _r(docs / "entity_chunks.jsonl"):
        for c in r["chunks"]:
            ent_by_chunk.setdefault(c, []).append(r["entity_id"])
    counts["kg/chunk_index"] = _w(out / "kg" / "chunk_index.jsonl", (
        {"kb_version": v, "chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "url": c["url"], "start": c["start"],
         "end": c["end"], "entities": sorted(ent_by_chunk.get(c["chunk_id"], []))} for c in _r(docs / "chunks.jsonl")))
    counts["kg/segments"] = _w(out / "kg" / "segments.jsonl", ({"kb_version": v, **c} for c in g.get("communities", [])))
    counts["kg/hierarchy"] = _w(out / "kg" / "hierarchy.jsonl", ({"kb_version": v, **h} for h in g.get("hierarchy", [])))

    # tasks (single-turn today; `turns` holds multi-turn sessions)
    tasks = []
    for f in sorted(glob.glob(str(config.EVAL / "gold" / "tasks_*.jsonl"))):
        for t in _r(Path(f)):
            if t.get("kb_version") != v:            # answer keys are only valid on the KB they were computed on
                continue
            tasks.append({"task_id": t["id"], "task_set": Path(f).stem, "kb_version": t.get("kb_version", v),
                          "use_case": t["use_case"], "turns": t.get("turns") or [{"role": "user", "content": t["brief"]}],
                          "answer_key": t["key"],
                          "oracle_edge_ids": [m.group(1) for line in t.get("oracle_edges", [])
                                              if (m := re.match(r"\[([^\]]+)\]", line))],
                          "canary": CANARY})
    counts["bench/tasks"] = _w(out / "bench" / "tasks.jsonl", tasks)

    # multi-turn sessions: one key per turn, gold evidence, and the solver-gate record (only accepted ones)
    sess = []
    for f in sorted(glob.glob(str(config.EVAL / "gold" / "sessions_*.jsonl"))):
        if "rejected" in f:
            continue
        for x in _r(Path(f)):
            if x.get("kb_version") != v:
                continue
            sess.append({"session_id": x["id"], "session_set": Path(f).stem, "kb_version": v, "template": x["template"],
                         "persona": x.get("persona"), "anchors": x["anchors"],
                         "turns": [{"role": "user", "content": m, "answer_key": t["key"]}
                                   for m, t in zip(x["messages"], x["turns"], strict=True)],
                         "gold_edge_ids": x["gold_edge_ids"], "facts": x.get("facts", []),
                         "writer": x.get("writer"), "gate": x.get("gate"), "canary": CANARY})
    counts["bench/sessions"] = _w(out / "bench" / "sessions.jsonl", sess)

    # trajectories: every benchmark run with its steps (traversal) and scores
    traj = []
    for f in sorted(glob.glob(str(config.EVAL / "results" / "bench_*.jsonl"))):
        for r in _r(Path(f)):
            if r.get("kb_version") != v:
                continue
            o = r.get("output") or {}
            traj.append({"run_file": Path(f).name, "run_id": r.get("run_id"), "kb_version": r.get("kb_version", v),
                         "task_id": r["task_id"], "use_case": r["use_case"], "model": r["model"], "condition": r["condition"],
                         "steps": r.get("tool_calls", []), "n_tool_calls": r.get("n_tool_calls"),
                         "final_answer": o.get("answer"), "items": o.get("items", []),
                         "error": o.get("error") or ("parse_error" if o.get("parse_error") else None),
                         "scores": r.get("score"), "cost_usd": r.get("cost_usd"), "latency_s": r.get("latency_s")})
    counts["runs/trajectories"] = _w(out / "runs" / "trajectories.jsonl", traj)
    sruns = [{"run_file": Path(f).name, **{k: r[k] for k in ("session_id", "template", "model", "condition", "kb_version",
              "run_id", "turns", "steps", "turn_scores", "mean_score", "all_turns_pass", "cost_usd", "latency_s")}}
             for f in sorted(glob.glob(str(config.EVAL / "results" / "sessions_*.jsonl")))
             for r in _r(Path(f)) if r.get("kb_version") == v]
    counts["runs/session_trajectories"] = _w(out / "runs" / "session_trajectories.jsonl", sruns)

    # agency testbed: persona tasks, agent trajectories, judge labels (only ledger-valid experiment runs)
    atasks, aruns, ajudg = agency_rows(v)
    counts["bench/agency_tasks"] = _w(out / "bench" / "agency_tasks.jsonl", atasks)
    counts["runs/agency_trajectories"] = _w(out / "runs" / "agency_trajectories.jsonl", aruns)
    counts["labels/agency_judgments"] = _w(out / "labels" / "agency_judgments.jsonl", ajudg)

    labels = []
    for f in sorted(glob.glob(str(config.EVAL / "gold" / "silver_*_v*.jsonl"))):
        for r in _r(Path(f)):
            kind = "verification" if "triple" in r else "entity_resolution"     # by record shape, not file name
            if kind == "verification":
                t = r["triple"]
                labels.append({"label_set": Path(f).stem, "kind": kind, "item_id": r["id"], "url": r["url"],
                               "claim": {k: t[k] for k in ("head", "relation", "tail", "claim_kind")}, "quote": t["quote"][:400],
                               "edge_id": r.get("edge_id"), "kb_status": r.get("status"),
                               "votes": r.get("votes", {}), "silver": r.get("silver"), "pipeline": r.get("prod_entailed")})
            else:
                labels.append({"label_set": Path(f).stem, "kind": kind, "item_id": r["id"], "a": r["name_a"], "b": r["name_b"],
                               "type": r["type_a"], "votes": r.get("votes", {}), "silver": r.get("silver"), "pipeline": r.get("verdict")})
    counts["labels/labels"] = _w(out / "labels" / "labels.jsonl", labels)
    for part in ("kg", "bench", "runs", "labels"):
        (out / part / "README.md").write_text(_card(v, part, {k: n for k, n in counts.items() if k.startswith(part)}))
    return {"version": v, "out": str(out), "counts": counts,
            "datasets": {p: f"connected-frontiers-{p}" for p in ("kg", "bench", "runs", "labels")}}


def valid_experiment_dirs() -> list[Path]:
    """Experiment run folders recorded in the ledger and not invalidated by a later correction record."""
    ledger = _r(config.EVAL / "experiments.jsonl") if (config.EVAL / "experiments.jsonl").exists() else []
    bad = {r["correction_of"] for r in ledger if r.get("correction_of") and r.get("valid") is False}
    return [Path(r["dir"]) for r in ledger
            if r.get("level") == "agency" and r.get("dir") and not r.get("correction_of")
            and r["ts"] not in bad and Path(r["dir"]).exists()]


def agency_rows(v: str) -> tuple[list, list, list]:
    tasks, runs, judg, seen_t, seen_r = [], [], [], set(), set()
    for d in valid_experiment_dirs():
        exp = f"{d.parent.name}/{d.name}"
        for t in _r(d / "tasks.jsonl"):
            if t.get("kb_version") == v and t["id"] not in seen_t:
                seen_t.add(t["id"])
                tasks.append(t)
        for r in _r(d / "runs.jsonl"):
            key = (r["task_id"], r["model"], r["condition"], r.get("run_id"))
            if r.get("kb_version") == v and key not in seen_r:
                seen_r.add(key)
                runs.append({"experiment": exp, **{k: r.get(k) for k in (
                    "task_id", "persona", "stratum", "question", "model", "condition", "kb_version", "run_id", "plan",
                    "notes", "gates", "answer", "steps", "error", "metrics", "cost_usd", "latency_s")}})
        if (d / "tasks.jsonl").exists() and any(t.get("kb_version") == v for t in _r(d / "tasks.jsonl")):
            judg += [{"experiment": exp, "kind": "score", **r} for r in _r(d / "scores.jsonl")]
            judg += [{"experiment": exp, "kind": "pairwise", **r} for r in _r(d / "pairwise.jsonl")]
    return tasks, runs, judg


PURPOSE = {
    "kg": "The curated knowledge graph: entities, typed edges with evidence status, citations, document index "
          "(GraphRAG), segments, hierarchy, and `triples.tsv` for KG-embedding tools. One revision tag per KB version.",
    "bench": "Task benchmark pinned to a KB version: use-case tasks (and multi-turn sessions) with computed answer keys "
             "and gold evidence ids (edges / passages), so both retrieval and answers can be scored; and persona agency tasks "
             "(learn / research / build / adopt / deploy) curated by a separate model family.",
    "runs": "Agent trajectories: every step (tool, args, thought, ids touched = traversal), final answer, citations, "
            "scores, cost and latency, per model x condition x task; agency trajectories add the plan, findings with "
            "cited edge ids, and the advice built from them.",
    "labels": "Silver labels from a 4-judge ensemble (verification and entity resolution) and owner gold labels; "
              "persona and expert LLM-judge scores and pairwise preferences (both orders) for agency runs.",
}


def _card(v: str, part: str, counts: dict) -> str:
    files = {"kg": [("entities", "entities.jsonl"), ("edges", "edges.jsonl"), ("evidence", "evidence.jsonl"),
                    ("documents", "documents.jsonl"), ("chunk_index", "chunk_index.jsonl"), ("segments", "segments.jsonl"),
                    ("hierarchy", "hierarchy.jsonl")],
             "bench": [("tasks", "tasks.jsonl"), ("sessions", "sessions.jsonl"), ("agency_tasks", "agency_tasks.jsonl")],
             "runs": [("trajectories", "trajectories.jsonl"), ("session_trajectories", "session_trajectories.jsonl"),
                      ("agency_trajectories", "agency_trajectories.jsonl")],
             "labels": [("labels", "labels.jsonl"), ("agency_judgments", "agency_judgments.jsonl")]}[part]
    configs = "\n".join(f"- config_name: {n}\n  data_files: {f}" for n, f in files)
    rows = "\n".join(f"| {k} | {n:,} |" for k, n in counts.items())
    return f"""---
license: cc-by-4.0
pretty_name: Connected Frontiers {part} ({v})
tags: [knowledge-graph, graph-rag, agents, evaluation, ai-ecosystem]
configs:
{configs}
---

# connected-frontiers-{part} · {v}

{PURPOSE[part]}

Part of the **Connected Frontiers** collection (kg · bench · runs · labels). Code, loaders and eval
scripts: the GitHub repository (`cf kb pull <version>` installs the KB locally).

| File | Rows |
|---|---|
{rows}

**Licensing.** Annotations CC-BY-4.0 (proposed). Page text is not redistributed: quotes are ≤ 400
chars plus URL, and passages are referenced by URL and offsets. **Canary:** `{CANARY}`.
"""
