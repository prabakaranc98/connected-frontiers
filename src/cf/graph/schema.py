"""The data contract: entity and edge types, with provenance on every edge.

This file is the single source of truth for the schema in docs/DESIGN.md §1 and the
Hugging Face release in docs/DATASET.md.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl


class EntityType(StrEnum):
    ORG = "org"
    PROBLEM = "problem"
    METHOD = "method"
    BENCHMARK = "benchmark"
    MODEL = "model"
    TECHNOLOGY = "technology"
    PAPER = "paper"
    ROLE = "role"
    SKILL = "skill"
    DATASET = "dataset"
    PERSON = "person"  # optional in v1; public authorship only


class OrgKind(StrEnum):
    FRONTIER_LAB = "frontier_lab"
    NEOLAB = "neolab"
    STARTUP = "startup"
    INFRA = "infra"
    CUSTOMER = "customer"
    INVESTOR = "investor"
    ACADEMIC = "academic"


class Layer(StrEnum):
    """Where an entity sits in the ecosystem stack (docs/DESIGN.md §1.1). Orientation for readers."""
    COMPUTE = "compute"            # chips, hardware
    CLOUD = "cloud"                # GPU clouds, data centres
    MODELS = "models"              # frontier labs, open-weight model builders
    PLATFORM = "platform"          # training / post-training / serving platforms, neolabs
    TOOLING = "tooling"            # evals, data, observability, agent frameworks
    APPLICATION = "application"    # AI-native products and startups
    ADOPTER = "adopter"            # customers and sectors using AI
    RESEARCH = "research"          # cross-cutting: papers, methods, benchmarks, academia
    TALENT = "talent"              # cross-cutting: roles, skills
    CAPITAL = "capital"            # cross-cutting: investors, funding


class Relation(StrEnum):
    SERVES = "serves"
    WORKS_ON = "works_on"
    USES_METHOD = "uses_method"
    MEASURED_ON = "measured_on"
    BUILDS_ON = "builds_on"
    USES_TECH = "uses_tech"
    COMPARES_AGAINST = "compares_against"
    PUBLISHES = "publishes"
    CITES = "cites"
    HIRES_FOR = "hires_for"
    REQUIRES = "requires"
    INVESTS_IN = "invests_in"
    ACQUIRED = "acquired"
    PARTNERS_WITH = "partners_with"
    OFFERS = "offers"              # org -> its own product / model / platform (round 1 fix)
    PART_OF = "part_of"            # sub-unit -> parent (team, office, division)
    SUBTYPE_OF = "subtype_of"      # specific -> general (SFT -> fine-tuning)
    TRAINED_ON = "trained_on"      # model -> dataset


class EdgeStatus(StrEnum):
    """Status ladder (docs/EVIDENCE.md §3). Assigned by cf.graph.grading, never by hand-waving."""
    UNSUPPORTED = "unsupported"    # no citation entails the claim
    CLAIMED = "claimed"            # only self / aggregator sources
    CONFIRMED = "confirmed"        # the counterparty agrees
    CORROBORATED = "corroborated"  # >=2 independent publishers, >=1 not the subject
    VERIFIED = "verified"          # independent primary record, entailment checked


class SourceKind(StrEnum):
    """Who published a citation, relative to the claim."""
    SELF = "self"                                # the subject's own page (marketing)
    COUNTERPARTY = "counterparty"                # the other party in the relation
    INDEPENDENT_PRIMARY = "independent_primary"  # leaderboard, paper with results, filing
    PRESS = "press"                              # journalism / analysts
    AGGREGATOR = "aggregator"                    # directories, wikis, unknown


class Stance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"                # the quote denies the claim
    QUALIFIES = "qualifies"                    # supports with limits ("pilot", "up to")
    NOT_ENOUGH_INFO = "not_enough_info"        # the quote doesn't settle it (FEVER's third label)


class ClaimKind(StrEnum):
    RELATIONAL = "relational"      # "A serves B"
    QUANTITATIVE = "quantitative"  # "#1 on X", "15x cheaper": stricter rule
    EVENT = "event"                # "A acquired B on <date>"
    DESCRIPTIVE = "descriptive"    # "A uses async RL"


class Entity(BaseModel):
    id: str                                   # stable slug, e.g. "org:applied-compute"
    type: EntityType
    name: str
    org_kind: OrgKind | None = None
    layer: Layer | None = None
    domain: str | None = None                # resolution key for orgs, e.g. "appliedcompute.com"
    aliases: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    source_url: HttpUrl
    publisher: str                            # registrable domain or org id; independence unit
    quote: str = Field(max_length=400)        # short excerpt only (see docs/DATASET.md, licensing)
    observed_at: datetime
    published_at: date | None = None
    extractor_version: str
    source_kind: SourceKind = SourceKind.AGGREGATOR
    stance: Stance = Stance.SUPPORTS
    entailed: bool | None = None              # set by the Verifier; None = not yet checked
    verifier_version: str | None = None


class Edge(BaseModel):
    head: str                                 # Entity.id
    relation: Relation
    tail: str                                 # Entity.id
    claim_kind: ClaimKind = ClaimKind.RELATIONAL
    evidence: list[Evidence] = Field(min_length=1)
    # Set by cf.graph.grading.grade(); defaults are the most cautious values.
    status: EdgeStatus = EdgeStatus.CLAIMED
    strength: float = Field(default=0.0, ge=0.0, le=1.0)
    contested: bool = False
    stale: bool = False
    grade_reasons: list[str] = Field(default_factory=list)
    attrs: dict[str, str] = Field(default_factory=dict)   # e.g. derivation=fine_tune

    @property
    def n_sources(self) -> int:
        return len({str(e.source_url) for e in self.evidence})

    @property
    def n_publishers(self) -> int:
        return len({e.publisher for e in self.evidence})
