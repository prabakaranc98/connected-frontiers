"""Swappable component interfaces. Each v0 baseline and v1+ variant implements one of these,
so the eval harness can hold everything fixed except the part under test (EVAL.md)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cf.graph.schema import Edge, Entity


@dataclass
class Page:
    url: str
    raw_sha256: str
    text: str
    links: list[str]
    title: str = ""


@dataclass
class Mention:
    surface: str
    type_hint: str | None
    page_url: str


@dataclass
class Triple:
    head: Mention
    relation: str
    tail: Mention
    quote: str


class SourceFinder(Protocol):          # cf.crawl.sources
    def find(self, entity: Entity) -> list[str]: ...


class Fetcher(Protocol):               # cf.crawl.fetch (+ clean)
    def fetch(self, url: str) -> Page | None: ...


class Extractor(Protocol):             # cf.extract
    version: str
    def extract(self, page: Page) -> list[Triple]: ...


class Resolver(Protocol):              # cf.resolve
    def resolve(self, mention: Mention) -> Entity: ...


class FrontierPolicy(Protocol):        # cf.rank (bfs | degree | pagerank | ppr_push | ...)
    name: str
    def push(self, entity_id: str) -> None: ...
    def update(self, new_edges: list[Edge]) -> None: ...
    def pop(self) -> str | None: ...
    def should_stop(self) -> bool: ...


class Reasoner(Protocol):              # cf.reason (R0..R3)
    name: str
    def answer(self, question: str) -> tuple[str, list[str]]: ...   # (answer, cited edge ids)
