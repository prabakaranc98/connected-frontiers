"""v0 resolver: normalized name -> stable id. Baseline to beat with fuzzy + embeddings + LLM."""

from __future__ import annotations

import re

SUFFIXES = r"\b(inc|incorporated|corp|corporation|llc|ltd|co|company|technologies|labs?)\b\.?"


def slug(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[’']s\b", "", s)
    s = re.sub(SUFFIXES, " ", s)
    s = re.sub(r"[^a-z0-9.+]+", "-", s).strip("-")
    return s or "unknown"


def entity_id(etype: str, name: str) -> str:
    return f"{etype}:{slug(name)}"
