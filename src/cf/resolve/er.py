"""Entity resolution v1: merge mentions that name the same thing.

Pipeline (cheap → expensive, so the LLM sees only unclear pairs):
1. normalize: casefold, strip possessives/suffixes ("Harvey's", "Inc"), unify punctuation
2. block by entity type (never merge a method with a benchmark)
3. candidate pairs, each with a rule-based reason:
   - same normalized key                  -> auto-merge
   - acronym ↔ expansion ("RL" ↔ "Reinforcement Learning", "LAB" ↔ "Legal Agent Benchmark")
   - containment ("Legal Agent Benchmark" ⊂ "Harvey's Legal Agent Benchmark")
   - fuzzy similarity (rapidfuzz token_set_ratio)
4. LLM adjudication for non-automatic pairs (typed contract, with example quotes as context)
5. union-find over accepted pairs -> canonical id + aliases; a merge report for audit

False merges are worse than missed merges (EVAL.md), so automatic merges are kept conservative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import combinations
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cf.llm.client import LLM

STOP = {"the", "a", "an", "of", "for", "and", "with", "on", "in", "at", "to"}
ORG_SUFFIX = r"\b(inc|incorporated|corp|corporation|llc|ltd|co|company|technologies|labs?|ai)\b"


def normalize(name: str, etype: str) -> str:
    s = name.casefold().replace("&", " and ")
    s = re.sub(r"[’']s\b", "", s)                 # possessive
    s = re.sub(r"\(.*?\)", " ", s)                      # parentheticals
    s = re.sub(r"[-_/.,:]+", " ", s)
    if etype == "org":
        s = re.sub(ORG_SUFFIX, " ", s)
    return re.sub(r"\s+", " ", s).strip()


LEGAL_SUFFIX = r"\b(inc|incorporated|corp|corporation|llc|ltd|gmbh|plc)\b\.?"


def strict_key(name: str) -> str:
    """The ONLY key allowed to auto-merge: casefold + punctuation + legal suffixes. Keeps
    parentheticals and words like 'AI', 'Research', 'Labs' (they often mark a sub-unit)."""
    s = name.casefold().replace("&", " and ")
    s = re.sub(r"[\u2019']s\b", "", s)
    s = re.sub(LEGAL_SUFFIX, " ", s)
    s = re.sub(r"[-_/.,:()\[\]]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def acronym(name: str) -> str:
    words = [w for w in re.split(r"[\s\-_/]+", name) if w and w.casefold() not in STOP]
    return "".join(w[0] for w in words).casefold()


def is_acronym_of(short: str, long: str) -> bool:
    s = re.sub(r"[^A-Za-z0-9]", "", short)
    return 2 <= len(s) <= 6 and s.isupper() and len(long.split()) >= 2 and s.casefold() == acronym(long)


def similarity(a: str, b: str) -> float:
    try:   # token_SORT (not token_set): a word subset ("NVIDIA" vs "NVIDIA Research") is NOT identical
        from rapidfuzz.fuzz import token_sort_ratio
        return token_sort_ratio(a, b) / 100
    except ImportError:  # optional dependency
        return SequenceMatcher(None, a, b).ratio()


@dataclass
class Candidate:
    a: str
    b: str
    reason: str
    score: float
    auto: bool


@dataclass
class MergeReport:
    auto: list[Candidate] = field(default_factory=list)
    llm_accepted: list[Candidate] = field(default_factory=list)
    llm_rejected: list[Candidate] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)   # canonical id -> merged ids
    hierarchy: list[dict] = field(default_factory=list)          # child -> parent (part_of / subtype_of)
    decisions: list[dict] = field(default_factory=list)          # every candidate + verdict (for audit / silver labels)


def _blocked_pairs(ents: list[dict], norm: dict[str, str], max_block: int = 150):
    """Pairs that share a token or an acronym key. Very common tokens (> max_block members) don't
    form blocks; they would compare everything with everything and say little."""
    index: dict[str, list[int]] = {}
    for i, e in enumerate(ents):
        keys = set(norm[e["id"]].split())
        keys.add("acr:" + re.sub(r"[^a-z0-9]", "", e["name"].casefold()))   # short form as written
        if len(e["name"].split()) >= 2:
            keys.add("acr:" + acronym(e["name"]))                             # long form's initials
        for k in keys:
            index.setdefault(k, []).append(i)
    seen: set[tuple[int, int]] = set()
    for members in index.values():
        if len(members) > max_block:
            continue
        for i, j in combinations(members, 2):
            if (i, j) not in seen:
                seen.add((i, j))
                yield ents[i], ents[j]


def candidates(entities: dict[str, dict], fuzzy_min: float = 0.88) -> list[Candidate]:
    by_type: dict[str, list[dict]] = {}
    for e in entities.values():
        by_type.setdefault(e["type"], []).append(e)
    norm = {e["id"]: normalize(e["name"], e["type"]) for e in entities.values()}
    out: list[Candidate] = []
    for etype, ents in by_type.items():
        for x, y in _blocked_pairs(ents, norm):
            nx_, ny = norm[x["id"]], norm[y["id"]]
            if not nx_ or not ny:
                continue
            exact = strict_key(x["name"]) == strict_key(y["name"])
            if etype == "org" and x.get("domain") and y.get("domain"):
                if x["domain"] == y["domain"]:
                    # Sub-units share the parent's domain (Stanford HAI, NVIDIA Research): auto-merge
                    # only on the strict key; everything else goes to the judge (same/part/different).
                    sim = similarity(nx_, ny)
                    out.append(Candidate(x["id"], y["id"], f"same domain {sim:.2f}", sim, exact))
                continue                     # two orgs with different known domains: never merge
            if exact:
                out.append(Candidate(x["id"], y["id"], "strict key", 1.0, True))
            elif nx_ == ny:                  # equal only after loose normalization ("Google" ~ "Google AI")
                out.append(Candidate(x["id"], y["id"], "loose normalized", 0.95, False))
            elif is_acronym_of(x["name"], y["name"]) or is_acronym_of(y["name"], x["name"]):
                out.append(Candidate(x["id"], y["id"], "acronym", 0.9, False))
            elif min(len(nx_), len(ny)) >= 4 and (f" {nx_} " in f" {ny} " or f" {ny} " in f" {nx_} "):
                out.append(Candidate(x["id"], y["id"], "containment", 0.8, False))
            else:
                sim = similarity(nx_, ny)
                if sim >= fuzzy_min:
                    out.append(Candidate(x["id"], y["id"], f"fuzzy {sim:.2f}", sim, False))
    return out


# ---- LLM adjudication (typed) ------------------------------------------------------------
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Judgement(_Strict):
    i: int
    verdict: Literal["same", "part_or_subtype", "different"]
    parent: Literal["A", "B", "none"]          # for part_or_subtype: which one is the general/whole


class JudgementOut(_Strict):
    results: list[Judgement]


ADJ_SYSTEM = """You compare two names from an AI-ecosystem knowledge graph. Each pair has the entity type and example
quotes where each name appeared. Answer with one verdict:
- same: the same real-world thing (abbreviation, possessive form, spelling variant).
  e.g. "RL" vs "Reinforcement learning"; "Legal Agent Benchmark" vs "Harvey's Legal Agent Benchmark".
- part_or_subtype: one is a part, sub-unit, specialisation or member of the other. Set parent to the
  general/whole one. e.g. "SFT" vs "fine-tuning" (parent = fine-tuning); "NSF Directorate for TIP" vs "NSF"
  (parent = NSF); "fully asynchronous RL" vs "RL" (parent = RL).
- different: otherwise, including versions and siblings ("GPT-5.4" vs "GPT-5.5", "Google" vs "Google DeepMind"
  are different; a company and its product are different).
When unsure, answer different. For same/different set parent = none. One result per pair, same i."""


def adjudicate(pairs: list[Candidate], entities: dict[str, dict], quotes: dict[str, list[str]],
               model: str, batch: int = 25, reasoning_max_tokens: int | None = 0) -> list[Judgement]:
    llm = LLM(model)
    verdicts: list[Judgement] = []
    for start in range(0, len(pairs), batch):
        chunk = pairs[start:start + batch]
        lines = []
        for i, c in enumerate(chunk):
            a, b = entities[c.a], entities[c.b]
            qa = " | ".join(q[:120] for q in quotes.get(c.a, [])[:2])
            qb = " | ".join(q[:120] for q in quotes.get(c.b, [])[:2])
            lines.append(f'{i}. type={a["type"]}\n   A: "{a["name"]}"  quotes: {qa}\n'
                         f'   B: "{b["name"]}"  quotes: {qb}')
        out = llm.parse(ADJ_SYSTEM, "\n".join(lines), JudgementOut, "er_adjudicate",
                        max_tokens=3000, reasoning_max_tokens=reasoning_max_tokens)
        by_i = {r.i: r for r in out.results}
        verdicts += [by_i.get(i, Judgement(i=i, verdict="different", parent="none"))
                     for i in range(len(chunk))]
    return verdicts


# ---- union-find ----------------------------------------------------------------------------
def merge_groups(ids: list[str], accepted: list[Candidate]) -> dict[str, str]:
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for c in accepted:
        ra, rb = find(c.a), find(c.b)
        if ra != rb:
            parent[rb] = ra
    return {i: find(i) for i in ids}


def resolve(entities: dict[str, dict], quotes: dict[str, list[str]], model: str | None,
            degree: dict[str, int] | None = None) -> tuple[dict[str, str], MergeReport]:
    """Returns (id -> canonical id, report). Canonical = the most connected, then longest name."""
    rep = MergeReport()
    cands = candidates(entities)
    rep.auto = [c for c in cands if c.auto]
    unclear = [c for c in cands if not c.auto]
    rep.decisions = [{"a": c.a, "b": c.b, "reason": c.reason, "decided_by": "rule", "verdict": "same", "parent": "none"}
                     for c in rep.auto]
    if unclear and model:
        for c, j in zip(unclear, adjudicate(unclear, entities, quotes, model), strict=True):
            rep.decisions.append({"a": c.a, "b": c.b, "reason": c.reason, "decided_by": "llm",
                                  "verdict": j.verdict, "parent": j.parent})
            if j.verdict == "same":
                rep.llm_accepted.append(c)
            elif j.verdict == "part_or_subtype" and j.parent in ("A", "B"):
                child, parent = (c.b, c.a) if j.parent == "A" else (c.a, c.b)
                kind = "part_of" if entities[child]["type"] == "org" else "subtype_of"
                rep.hierarchy.append({"child": child, "parent": parent, "kind": kind, "reason": c.reason})
            else:
                rep.llm_rejected.append(c)
    roots = merge_groups(list(entities), rep.auto + rep.llm_accepted)

    degree = degree or {}
    groups: dict[str, list[str]] = {}
    for i, r in roots.items():
        groups.setdefault(r, []).append(i)
    mapping: dict[str, str] = {}
    for members in groups.values():
        canon = max(members, key=lambda m: (degree.get(m, 0), len(entities[m]["name"])))
        for m in members:
            mapping[m] = canon
        if len(members) > 1:
            rep.groups[canon] = sorted(members)
    return mapping, rep
