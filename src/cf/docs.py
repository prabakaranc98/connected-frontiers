"""Document layer for GraphRAG: pages → documents → chunks, linked to entities and edges.

- documents: one per fetched page (url, title, publisher, fetched_at, clean text)
- chunks:    ~300-word passages with overlap; chunk_id = <doc>:<n>
- links:     edge evidence → chunk (exact: quotes are verbatim, so we locate their offset)
             entity → chunks that mention it by name/alias (word-boundary match)
- search:    BM25 over chunks (lexical, no model download); graph-aware ranking in cf.agent.graphrag

Stored as JSONL under data/processed/docs/ (rebuilt by `cf docs`).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from cf import config
from cf.crawl.fetch import Fetcher, registrable

OUT = config.DATA / "processed" / "docs"
WORD = re.compile(r"\w+", re.UNICODE)
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "by", "at", "from", "as", "is", "are", "was", "were", "be", "been", "this", "that", "it", "its", "into", "our", "we", "you", "your", "their", "they"}


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def chunk_text(text: str, size: int = 300, overlap: int = 60) -> list[tuple[int, int]]:
    """Return (start, end) char spans of ~size-word chunks with overlap."""
    spans = [m.span() for m in re.finditer(r"\S+", text)]
    out, i = [], 0
    while i < len(spans):
        j = min(i + size, len(spans))
        out.append((spans[i][0], spans[j - 1][1]))
        if j == len(spans):
            break
        i = j - overlap
    return out


def build(graph_path: Path | None = None) -> dict:
    """Rebuild documents, chunks and links from the raw cache and the built graph."""
    graph = json.loads((graph_path or config.DATA / "processed" / "graph" / "graph.json").read_text())
    ents = {e["id"]: e for e in graph["entities"]}
    urls = sorted({ev["source_url"] for e in graph["edges"] for ev in e["evidence"] if "huggingface.co" not in ev["source_url"]})
    fetcher = Fetcher()
    ev_by_url: dict[str, list] = defaultdict(list)
    for e in graph["edges"]:
        for ev in e["evidence"]:
            ev_by_url[ev["source_url"]].append((e, ev))
    docs, chunks = [], []
    chunk_of_quote: dict[tuple[str, str], str] = {}
    for u in urls:
        p = fetcher.fetch(u)
        if p is None:
            continue
        doc_id = p.raw_sha256[:16]
        docs.append({"doc_id": doc_id, "url": u, "title": p.title, "publisher": registrable(u), "chars": len(p.text)})
        spans = chunk_text(p.text)
        norm_text = _norm(p.text)
        for n, (a, b) in enumerate(spans):
            chunks.append({"chunk_id": f"{doc_id}:{n}", "doc_id": doc_id, "url": u, "start": a, "end": b, "text": p.text[a:b]})
        # exact quote → chunk (quotes are verbatim; match on normalized text, then map back by ratio)
        for e, ev in ev_by_url.get(u, []):
            if True:
                pos = norm_text.find(_norm(ev["quote"]))
                if pos < 0 or not spans:
                    continue
                approx = int(pos * len(p.text) / max(len(norm_text), 1))
                idx = max((k for k, (a, _) in enumerate(spans) if a <= approx), default=0)
                chunk_of_quote[(e["id"], ev["quote"])] = f"{doc_id}:{idx}"

    # entity → chunks by name/alias mention (only names ≥ 3 chars, word boundaries)
    names: dict[str, list[str]] = defaultdict(list)
    for e in ents.values():
        for a in {e["name"], *e.get("aliases", [])}:
            a = a.strip()
            if len(a) >= 3 and "/" not in a:
                names[a.lower()].append(e["id"])
    pattern_cache: dict[str, re.Pattern] = {}
    mentions: dict[str, set[str]] = defaultdict(set)
    by_doc_names: dict[str, list[str]] = {}
    for c in chunks:
        low = c["text"].lower()
        cands = by_doc_names.get(c["doc_id"])
        if cands is None:
            full = " ".join(x["text"].lower() for x in chunks if x["doc_id"] == c["doc_id"])
            cands = [n for n in names if n in full]
            by_doc_names[c["doc_id"]] = cands
        for n in cands:
            if n in low:
                pat = pattern_cache.setdefault(n, re.compile(r"(?<!\w)" + re.escape(n) + r"(?!\w)"))
                if pat.search(low):
                    for eid in names[n]:
                        mentions[eid].add(c["chunk_id"])
    edge_by_id = {x["id"]: x for x in graph["edges"]}
    for (eid_edge, _q), cid in chunk_of_quote.items():
        e = edge_by_id.get(eid_edge)
        if e:
            mentions[e["head"]].add(cid)
            mentions[e["tail"]].add(cid)

    OUT.mkdir(parents=True, exist_ok=True)
    _write(OUT / "documents.jsonl", docs)
    _write(OUT / "chunks.jsonl", chunks)
    _write(OUT / "edge_chunks.jsonl", [{"edge_id": k[0], "quote": k[1], "chunk_id": v} for k, v in chunk_of_quote.items()])
    _write(OUT / "entity_chunks.jsonl", [{"entity_id": k, "chunks": sorted(v)} for k, v in mentions.items()])
    n_ev = sum(1 for e in graph["edges"] for ev in e["evidence"] if "huggingface.co" not in ev["source_url"])
    return {"documents": len(docs), "chunks": len(chunks), "evidence_linked": len(chunk_of_quote), "evidence_total": n_ev,
            "entities_with_docs": len(mentions), "entities_total": len(ents)}


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


class DocIndex:
    """Chunks + BM25 + entity↔chunk links, loaded from data/processed/docs."""

    def __init__(self, k1: float = 1.4, b: float = 0.75, version: str | None = None):
        from cf import kb
        base = kb.docs_path(version)
        self.chunks = {c["chunk_id"]: c for c in _read(base / "chunks.jsonl")}
        self.docs = {d["doc_id"]: d for d in _read(base / "documents.jsonl")}
        self.entity_chunks = {r["entity_id"]: r["chunks"] for r in _read(base / "entity_chunks.jsonl")}
        self.edge_chunks = defaultdict(list)
        for r in _read(base / "edge_chunks.jsonl"):
            self.edge_chunks[r["edge_id"]].append(r["chunk_id"])
        self.chunk_entities = defaultdict(set)
        for eid, cs in self.entity_chunks.items():
            for c in cs:
                self.chunk_entities[c].add(eid)
        self.k1, self.b = k1, b
        self.tf = {cid: Counter(w for w in WORD.findall(c["text"].lower()) if w not in STOP) for cid, c in self.chunks.items()}
        self.dl = {cid: sum(t.values()) for cid, t in self.tf.items()}
        self.avgdl = sum(self.dl.values()) / max(len(self.dl), 1)
        df = Counter(w for t in self.tf.values() for w in t)
        n = max(len(self.tf), 1)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}
        self.inv = defaultdict(list)
        for cid, t in self.tf.items():
            for w in t:
                self.inv[w].append(cid)

    def bm25(self, query: str, k: int = 20, restrict: set[str] | None = None) -> list[tuple[float, str]]:
        q = [w for w in WORD.findall(query.lower()) if w not in STOP]
        scores: Counter = Counter()
        for w in q:
            for cid in self.inv.get(w, []):
                if restrict is not None and cid not in restrict:
                    continue
                tf = self.tf[cid][w]
                scores[cid] += self.idf.get(w, 0) * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.dl[cid] / self.avgdl))
        return [(round(s, 3), cid) for cid, s in scores.most_common(k)]

    def passage(self, chunk_id: str, max_chars: int = 1200) -> dict:
        c = self.chunks.get(chunk_id)
        if not c:
            return {"error": f"unknown chunk {chunk_id}"}
        d = self.docs.get(c["doc_id"], {})
        return {"chunk_id": chunk_id, "url": c["url"], "title": d.get("title"), "publisher": d.get("publisher"),
                "text": c["text"][:max_chars], "entities": sorted(self.chunk_entities.get(chunk_id, []))[:20]}
