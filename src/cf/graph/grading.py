"""Evidence grading: an edge's citations -> status, strength, flags and human-readable reasons.

Deterministic and explainable on purpose. Models only supply per-citation `stance` and
`entailed` (the Verifier role). Spec: docs/EVIDENCE.md. Weights: configs/evidence.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from cf.graph.schema import ClaimKind, Edge, EdgeStatus, Evidence, SourceKind, Stance

DEFAULTS: dict = {
    "status_strength": {
        "unsupported": 0.0, "claimed": 0.35, "confirmed": 0.6, "corroborated": 0.8, "verified": 1.0,
    },
    # CLAIMED strength depends on how costly the claim is to fake. Naming a customer risks the
    # customer objecting; "15x cheaper" risks nothing until someone checks.
    "claimed_strength_by_kind": {
        "relational": 0.5, "descriptive": 0.5, "event": 0.45, "quantitative": 0.3,
    },
    "contested_factor": 0.5,
    "stale_after_days": 540,
    "stale_factor": 0.7,
}


@dataclass
class Grade:
    status: EdgeStatus
    strength: float
    contested: bool
    stale: bool
    reasons: list[str] = field(default_factory=list)


def _usable(e: Evidence) -> bool:
    return e.entailed is not False          # unchecked (None) stays usable, refuted is dropped


def _when(e: Evidence) -> date:
    return e.published_at or e.observed_at.date()


def grade(edge: Edge, now: datetime | None = None, cfg: dict | None = None) -> Grade:
    cfg = {**DEFAULTS, **(cfg or {})}
    today = (now or datetime.now(UTC)).date()
    reasons: list[str] = []

    dropped = [e for e in edge.evidence if e.entailed is False]
    if dropped:
        reasons.append(f"{len(dropped)} citation(s) dropped: quote does not support the claim")

    support = [e for e in edge.evidence if e.stance == Stance.SUPPORTS and _usable(e)]
    against = [e for e in edge.evidence if e.stance == Stance.CONTRADICTS and _usable(e)]
    contested = bool(against)
    if contested:
        reasons.append(f"contested by {len({e.publisher for e in against})} publisher(s)")

    if not support:
        reasons.append("no supporting citation")
        return Grade(EdgeStatus.UNSUPPORTED, 0.0, contested, False, reasons)

    quantitative = edge.claim_kind == ClaimKind.QUANTITATIVE
    # Quantitative claims: press usually repeats the press release, so it doesn't count.
    counted = [e for e in support if not (quantitative and e.source_kind == SourceKind.PRESS)]
    if quantitative and len(counted) < len(support):
        reasons.append("quantitative claim: press citations not counted")

    publishers = {e.publisher for e in counted}
    non_self = {e.publisher for e in counted if e.source_kind != SourceKind.SELF}
    kinds = {e.source_kind for e in counted}
    primary_checked = any(
        e.source_kind == SourceKind.INDEPENDENT_PRIMARY and e.entailed is True for e in counted
    )

    if primary_checked:
        status = EdgeStatus.VERIFIED
        reasons.append("independent primary record, entailment checked")
    elif len(publishers) >= 2 and non_self:
        status = EdgeStatus.CORROBORATED
        reasons.append(f"{len(publishers)} independent publishers")
    elif SourceKind.COUNTERPARTY in kinds:
        status = EdgeStatus.CONFIRMED
        reasons.append("confirmed by the counterparty")
    else:
        status = EdgeStatus.CLAIMED
        who = "the subject's own" if kinds <= {SourceKind.SELF} else "unconfirmed"
        reasons.append(f"only {who} source(s)")

    newest = max(_when(e) for e in support)
    stale = (today - newest).days > cfg["stale_after_days"]
    if stale:
        reasons.append(f"stale: newest support {newest.isoformat()}")

    strength = cfg["status_strength"][status.value]
    if status == EdgeStatus.CLAIMED:
        by_kind = cfg.get("claimed_strength_by_kind") or {}
        strength = by_kind.get(edge.claim_kind.value, strength)
        reasons.append(f"{edge.claim_kind.value} self-claim: strength {strength}")
    if contested:
        strength *= cfg["contested_factor"]
    if stale:
        strength *= cfg["stale_factor"]
    return Grade(status, round(strength, 4), contested, stale, reasons)


def apply(edge: Edge, **kw) -> Edge:
    """Return a copy of the edge with its grade written in."""
    g = grade(edge, **kw)
    return edge.model_copy(update={
        "status": g.status, "strength": g.strength, "contested": g.contested,
        "stale": g.stale, "grade_reasons": g.reasons,
    })
