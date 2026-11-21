"""In-memory graph builder: merges entities and edges across pages, then grades evidence.

The scout keeps everything in memory and dumps JSON. SQLite comes at M1.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cf import config
from cf.crawl.fetch import registrable
from cf.extract.llm import NONE, Extraction, Verdict, XEntity
from cf.graph import grading
from cf.graph.schema import Edge, Evidence, SourceKind, Stance
from cf.interfaces import Page
from cf.resolve.simple import entity_id, slug


class GraphBuilder:
    def __init__(self, evidence_cfg: dict | None = None):
        self.cfg = evidence_cfg or config.load_yaml("evidence.yaml")
        self.primary = set(self.cfg.get("independent_primary_domains") or [])
        self.press = set(self.cfg.get("press_domains") or [])
        self.entities: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], Edge] = {}
        self.seeds: list[str] = []

    # ---- entities -----------------------------------------------------------------------
    def register_seed(self, name: str, domain: str, org_kind: str, layer: str | None = None) -> str:
        eid = self._entity(name, "org", org_kind=org_kind, layer=layer, domain=domain)
        self.seeds.append(eid)
        return eid

    def _entity(self, name: str, etype: str, org_kind: str | None = None,
                layer: str | None = None, domain: str | None = None) -> str:
        eid = entity_id(etype, name)
        e = self.entities.setdefault(eid, {"id": eid, "type": etype, "name": name.strip(),
                                           "aliases": [], "org_kind": None, "layer": None,
                                           "domain": None, "pages": 0})
        if name.strip() not in e["aliases"]:
            e["aliases"].append(name.strip())
        if org_kind and org_kind != NONE and not e["org_kind"]:
            e["org_kind"] = org_kind
        if layer and layer != NONE and not e["layer"]:
            e["layer"] = layer
        if domain and not e["domain"]:
            e["domain"] = domain
        return eid

    # ---- pages --------------------------------------------------------------------------
    def add_page(self, page: Page, ext: Extraction, verdicts: list[Verdict | None],
                 extractor_version: str, verifier_version: str) -> int:
        publisher = registrable(page.url)
        link_domains = {registrable(u) for u in page.links} | {publisher}
        now = datetime.now(UTC)

        for ent in ext.entities:
            dom = registrable(ent.domain) if ent.domain else ""
            dom = dom if dom in link_domains else self._domain_from_links(ent, link_domains)
            self._entity(ent.name, ent.type, ent.org_kind, ent.layer, dom or None)

        added = 0
        for t, v in zip(ext.triples, verdicts, strict=True):
            hid = self._entity(t.head, t.head_type)
            tid = self._entity(t.tail, t.tail_type)
            if hid == tid:
                continue
            ev = Evidence(source_url=page.url, publisher=publisher, quote=t.quote[:400],
                          observed_at=now, extractor_version=extractor_version,
                          stance=Stance(v.stance) if v else Stance.SUPPORTS,
                          entailed=v.entailed if v else None, verifier_version=verifier_version)
            key = (hid, t.relation, tid)
            if key in self.edges:
                old = self.edges[key]
                if not any(str(x.source_url) == page.url and x.quote == ev.quote for x in old.evidence):
                    old.evidence.append(ev)
            else:
                self.edges[key] = Edge(head=hid, relation=t.relation, tail=tid,
                                       claim_kind=t.claim_kind, evidence=[ev])
                added += 1
        return added

    def add_structured(self, rows: list[dict], publisher: str, adapter: str) -> int:
        """Rows from a structured adapter (primary records). Evidence is pre-graded: the record
        itself is the citation, so it is marked entailed and keeps its source kind."""
        now = datetime.now(UTC)
        added = 0
        for r in rows:
            hid = self._entity(r["head"], r["head_type"])
            tid = self._entity(r["tail"], r["tail_type"])
            for eid, alias in ((hid, r.get("head_alias")), (tid, r.get("tail_alias"))):
                if alias and alias not in self.entities[eid]["aliases"]:
                    self.entities[eid]["aliases"].append(alias)
            if hid == tid:
                continue
            ev = Evidence(source_url=r["url"], publisher=publisher, quote=r["quote"][:400], observed_at=now,
                          extractor_version=f"adapter:{adapter}", source_kind=SourceKind.INDEPENDENT_PRIMARY,
                          stance=Stance.SUPPORTS, entailed=True, verifier_version="structured-record")
            key = (hid, r["relation"], tid)
            if key in self.edges:
                if not any(str(x.source_url) == r["url"] and x.quote == ev.quote for x in self.edges[key].evidence):
                    self.edges[key].evidence.append(ev)
            else:
                self.edges[key] = Edge(head=hid, relation=r["relation"], tail=tid, claim_kind=r["claim_kind"],
                                       evidence=[ev], attrs=r.get("attrs") or {})
                added += 1
        return added

    def _domain_from_links(self, ent: XEntity, link_domains: set[str]) -> str:
        if ent.type != "org":
            return ""
        key = slug(ent.name).replace("-", "")
        for d in link_domains:
            if d.split(".")[0] == key:
                return d
        return ""

    # ---- grading ------------------------------------------------------------------------
    def source_kind(self, publisher: str, head: str, tail: str) -> SourceKind:
        if self.entities.get(head, {}).get("domain") == publisher:
            return SourceKind.SELF
        if self.entities.get(tail, {}).get("domain") == publisher:
            return SourceKind.COUNTERPARTY
        if publisher in self.primary:
            return SourceKind.INDEPENDENT_PRIMARY
        if publisher in self.press:
            return SourceKind.PRESS
        return SourceKind.AGGREGATOR

    def finalize(self) -> None:
        """Recompute source kinds (domains may have been learned later), then grade every edge."""
        for key, e in self.edges.items():
            evs = [x if x.extractor_version.startswith("adapter:")
                   else x.model_copy(update={"source_kind": self.source_kind(x.publisher, e.head, e.tail)})
                   for x in e.evidence]
            self.edges[key] = grading.apply(e.model_copy(update={"evidence": evs}), cfg=self.cfg)

    # ---- entity resolution ----------------------------------------------------------------
    def quotes_by_entity(self, k: int = 3) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for e in self.edges.values():
            for x in (e.head, e.tail):
                lst = out.setdefault(x, [])
                if len(lst) < k:
                    lst.append(e.evidence[0].quote)
        return out

    def degrees(self) -> dict[str, int]:
        d: dict[str, int] = {}
        for e in self.edges.values():
            d[e.head] = d.get(e.head, 0) + 1
            d[e.tail] = d.get(e.tail, 0) + 1
        return d

    def apply_mapping(self, mapping: dict[str, str]) -> None:
        """Rewrite ids to canonical ones; merge aliases, attributes and edge evidence."""
        ents: dict[str, dict] = {}
        for eid, e in self.entities.items():
            c = mapping.get(eid, eid)
            ce = ents.setdefault(c, {**self.entities[c], "aliases": list(self.entities[c]["aliases"])})
            for a in e["aliases"]:
                if a not in ce["aliases"]:
                    ce["aliases"].append(a)
            for key in ("org_kind", "layer", "domain"):
                if not ce.get(key) and e.get(key):
                    ce[key] = e[key]
        edges: dict[tuple[str, str, str], Edge] = {}
        for (h, r, t), e in self.edges.items():
            h2, t2 = mapping.get(h, h), mapping.get(t, t)
            if h2 == t2:
                continue
            key = (h2, r, t2)
            if key in edges:
                seen = {(str(x.source_url), x.quote) for x in edges[key].evidence}
                edges[key].evidence.extend(x for x in e.evidence if (str(x.source_url), x.quote) not in seen)
            else:
                edges[key] = e.model_copy(update={"head": h2, "tail": t2, "evidence": list(e.evidence)})
        self.entities, self.edges = ents, edges
        self.seeds = list(dict.fromkeys(mapping.get(s, s) for s in self.seeds))

    # ---- export -------------------------------------------------------------------------
    def to_dict(self, scores: dict[str, dict] | None = None) -> dict:
        scores = scores or {}
        return {
            "seeds": self.seeds,
            "entities": [{**e, **scores.get(e["id"], {})} for e in self.entities.values()],
            "edges": [{**e.model_dump(mode="json"), "id": f"{e.head}|{e.relation}|{e.tail}"}
                      for e in self.edges.values()],
        }
