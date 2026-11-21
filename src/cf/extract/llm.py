"""LLM extractor (page -> typed entities + triples with verbatim quotes) and Verifier.

Type-safe: the response contracts are Pydantic models. The JSON schema sent to the model is
generated from them (cf.llm.client.strict_schema), and every response is validated back into them.

Guards that don't need a model:
- quotes must appear verbatim in the page text (hallucinated quotes are dropped and counted);
- relation and type values are closed Literals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cf.crawl.fetch import registrable
from cf.graph.schema import ClaimKind, EntityType, Layer, OrgKind, Relation, Stance
from cf.interfaces import Page
from cf.llm.client import LLM

NONE = "none"


def _lit(values: list[str]):
    return Literal.__getitem__(tuple(values))


EntityTypeLit = _lit([t.value for t in EntityType if t != EntityType.PERSON])  # people off in v1
OrgKindLit = _lit([k.value for k in OrgKind] + [NONE])
LayerLit = _lit([x.value for x in Layer] + [NONE])
RelationLit = _lit([r.value for r in Relation])
ClaimKindLit = _lit([c.value for c in ClaimKind])
StanceLit = _lit([s.value for s in Stance])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class XEntity(_Strict):
    name: str
    type: EntityTypeLit
    org_kind: OrgKindLit
    layer: LayerLit
    domain: str


class XTriple(_Strict):
    head: str
    head_type: EntityTypeLit
    relation: RelationLit
    tail: str
    tail_type: EntityTypeLit
    quote: str
    claim_kind: ClaimKindLit


class ExtractionOut(_Strict):
    entities: list[XEntity]
    triples: list[XTriple]


class Verdict(_Strict):
    i: int
    entailed: bool
    stance: StanceLit


class VerifyOut(_Strict):
    results: list[Verdict]


EXTRACT_SYSTEM = """You extract a knowledge graph of the AI research and industry ecosystem from one web page.

Return entities and triples that the page states EXPLICITLY. Do not infer or use outside knowledge.
The page is published by the organisation that owns its domain. "We", "our" and unnamed subjects refer to it.

Entity types: org (companies, labs, universities, investors), problem (a task/use case, e.g. "legal agents"),
method (e.g. "reinforcement learning", "self-distillation"), benchmark, model (e.g. "GPT-5.5"),
technology (hardware, frameworks, platforms, products), paper (incl. research blog posts), role (job role), skill.
- org_kind: frontier_lab | neolab (research-led company selling training/models) | startup | infra | customer | investor | academic, else "none".
- layer: compute | cloud | models | platform | tooling | application | adopter | research | talent | capital, else "none".
- domain: the org's web domain ONLY if it appears on the page; otherwise "".

Relations (head -> tail), keep the direction exactly:
serves (vendor -> customer org) | works_on (org -> problem/use case; NOT for methods) |
uses_method (org/paper -> method) | measured_on (org/model/paper -> benchmark) |
builds_on (org/model -> model it is built on) | uses_tech (org -> technology/product) |
compares_against (org/model -> model it is compared with) | publishes (org -> paper/post) |
cites (paper -> paper) | hires_for (org -> role) | requires (role -> skill) |
invests_in | acquired (acquirer -> acquired) | partners_with (org -> org) |
offers (org -> its OWN product, model, platform or service; e.g. Mistral offers "Le Chat") |
part_of (sub-unit -> parent org; e.g. a directorate -> its agency) |
subtype_of (specific method/technology -> general one; e.g. "SFT" -> "fine-tuning").
Use uses_tech only for technology the org USES but does not make (e.g. Modal uses_tech "NVIDIA H100").

Index and listing pages (blog indexes, news lists, model hubs, "customers" grids) show headlines or cards
written by or about OTHER parties. From such pages extract only:
- publishes (publisher -> post title) when the post is clearly the publisher's own,
- serves / partners_with when a card explicitly names a customer or partner of the publisher.
Do NOT turn a headline into a claim about third parties unless the headline itself states the relation.

claim_kind: quantitative if the triple rests on a number, rank or comparison ("#1", "15x cheaper", "30% fewer");
event for dated events (acquired, raised); relational for business relations; descriptive otherwise.

quote: copy the SHORTEST exact span (<= 300 chars) from the page that states the triple. Copy it character
for character. If you cannot quote it, do not output the triple.
Use canonical names ("Harvey", not "Harvey's team"). Skip navigation, footers and cookie text."""

VERIFY_SYSTEM = """You are a strict fact checker for a knowledge graph. Each item has a QUOTE from a web page and a
CLAIM (head, relation, tail). You also get the SOURCE: the publisher's domain and the page title.

Read the quote in the context of its source: on a page published by X, "we", "our" and an unnamed subject
mean X. Beyond that source context, use nothing outside the quote.

Web-page genre conventions. These COUNT as stating the claim:
- On X's site, a case study, customer story, testimonial, customer logo or a title naming an organisation Z
  ("... with Z", "... at Z", "How Z uses ...", "Z case study") states that X serves / works with Z.
- "Our research on Y", "we use Y", "built on Y" on X's site states that X uses / works on Y.
- A product, model or feature listing of X's own offerings on X's site states that X offers them.
- A dated post title listed on X's site states that X publishes that post.
- A result line on X's site like "#1 on B" or "surpassed M" next to a customer case states that the
  work was measured on B / compared against M.
These conventions settle WHO did WHAT. They do not make numbers true: a quantitative claim is entailed if
the quote states the number, and it remains the publisher's own claim (the grader handles trust).

entailed = true only if the quote (in source context) states the claim, with the correct relation and the
correct direction. Being plausible or on-topic is not enough.
stance:
- supports: the quote asserts the claim
- qualifies: it asserts a limited form ("pilot", "up to", "in some cases")
- contradicts: the quote DENIES the claim or states the opposite (e.g. reversed acquisition)
- not_enough_info: the quote does not settle the claim either way
If entailed is false, stance must be contradicts or not_enough_info.
Return exactly one result per item, with the same i."""


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("×", "x")
    return re.sub(r"\s+", " ", s).strip().lower()


@dataclass
class Extraction:
    entities: list[XEntity] = field(default_factory=list)
    triples: list[XTriple] = field(default_factory=list)
    dropped_unquoted: int = 0


class LLMExtractor:
    def __init__(self, model: str, max_chars: int = 14000):
        self.llm = LLM(model)
        self.version = f"llm-v0:{model}"
        self.max_chars = max_chars

    def extract(self, page: Page) -> Extraction:
        text = page.text[: self.max_chars]
        user = (f"PUBLISHER: {registrable(page.url)}\nURL: {page.url}\nTITLE: {page.title}\n\n"
                f"PAGE TEXT:\n{text}")
        out = self.llm.parse(EXTRACT_SYSTEM, user, ExtractionOut, "kg_extract")
        ntext = _norm(text)
        kept = [t for t in out.triples
                if t.quote and _norm(t.quote) in ntext and t.head.strip() and t.tail.strip()]
        return Extraction(list(out.entities), kept, len(out.triples) - len(kept))


class Verifier:
    def __init__(self, model: str, reasoning_max_tokens: int | None = 1500):
        self.llm = LLM(model)
        self.reasoning = reasoning_max_tokens
        self.version = f"verify-v1:{model}:r{reasoning_max_tokens}"

    def verify(self, triples: list[XTriple], page: Page) -> list[Verdict | None]:
        """One verdict per triple, in order. None = the model skipped that item (stays unchecked)."""
        if not triples:
            return []
        source = f"SOURCE: publisher={registrable(page.url)} | title={page.title!r} | url={page.url}\n\n"
        items = "\n".join(
            f'{i}. QUOTE: "{t.quote}"\n   CLAIM: ({t.head}) -[{t.relation}]-> ({t.tail})'
            for i, t in enumerate(triples))
        out = self.llm.parse(VERIFY_SYSTEM, source + items, VerifyOut, "kg_verify", max_tokens=4000,
                             reasoning_max_tokens=self.reasoning)
        by_i = {r.i: r for r in out.results}
        return [by_i.get(i) for i in range(len(triples))]


class EscalatingVerifier:
    """Fallback for false support: items the primary ACCEPTS but that are risky (relation in the
    risky set, fragment quote, or a side not mentioned) get a second opinion from a different
    model family. Support needs both to agree; otherwise the citation is not_enough_info."""

    def __init__(self, primary: Verifier, secondary: Verifier, risky: set[str], min_words: int = 5):
        self.primary, self.secondary, self.risky, self.min_words = primary, secondary, risky, min_words
        self.version = f"{primary.version}+esc:{secondary.llm.model}"
        self.escalated = self.overturned = 0

    def needs_second_opinion(self, t: XTriple, page: Page) -> bool:
        q = _norm(t.quote)
        pub = registrable(page.url).split(".")[0]
        head_ok = _norm(t.head).split(" ")[0] in q or _norm(t.head).replace(" ", "").startswith(pub[:5])
        tail_ok = _norm(t.tail).split(" ")[0] in q
        return t.relation in self.risky or len(t.quote.split()) < self.min_words or not (head_ok and tail_ok)

    def combine(self, triples: list[XTriple], page: Page, first: list[Verdict | None]) -> list[Verdict | None]:
        idx = [i for i, (t, v) in enumerate(zip(triples, first, strict=True))
               if v is not None and v.entailed and self.needs_second_opinion(t, page)]
        if not idx:
            return first
        second = self.secondary.verify([triples[i] for i in idx], page)
        out = list(first)
        self.escalated += len(idx)
        for i, v2 in zip(idx, second, strict=True):
            if v2 is not None and not v2.entailed:
                out[i] = Verdict(i=i, entailed=False, stance="not_enough_info")
                self.overturned += 1
        return out

    def verify(self, triples: list[XTriple], page: Page) -> list[Verdict | None]:
        return self.combine(triples, page, self.primary.verify(triples, page))


def make_verifier():
    """Production verifier: primary (role 'verify') with escalation (role 'verify_escalate')."""
    from cf import config
    from cf.llm.client import AUTO, role_chain
    v, e = role_chain("verify"), role_chain("verify_escalate")
    cfg = config.load_yaml("models.yaml").get("escalation", {})
    primary = Verifier(v[0], AUTO)
    primary.llm.fallbacks = v[1:]
    if not e:
        return primary
    secondary = Verifier(e[0], AUTO)
    secondary.llm.fallbacks = e[1:]
    return EscalatingVerifier(primary, secondary, set(cfg.get("risky_relations", [])), cfg.get("min_quote_words", 5))
