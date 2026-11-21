"""Grading scenarios drawn from the Applied Compute /training page (docs/EVIDENCE.md)."""

from datetime import date, datetime

from cf.graph.grading import apply, grade
from cf.graph.schema import ClaimKind, Edge, EdgeStatus, Evidence, Relation, SourceKind, Stance

NOW = datetime(2026, 11, 21)


def ev(publisher, kind, stance=Stance.SUPPORTS, entailed=None, published=date(2026, 11, 1), n=0):
    return Evidence(source_url=f"https://{publisher}/page{n}", publisher=publisher,
                    quote="…", observed_at=NOW, published_at=published,
                    extractor_version="test", source_kind=kind, stance=stance, entailed=entailed)


def edge(*evidence, kind=ClaimKind.RELATIONAL, rel=Relation.SERVES, tail="org:harvey"):
    return Edge(head="org:applied-compute", relation=rel, tail=tail,
                claim_kind=kind, evidence=list(evidence))


def test_self_only_is_claimed_even_with_many_pages():
    g = grade(edge(*[ev("appliedcompute.com", SourceKind.SELF, n=i) for i in range(5)]), now=NOW)
    assert g.status == EdgeStatus.CLAIMED
    assert any("subject's own" in r for r in g.reasons)


def test_counterparty_confirms():
    g = grade(edge(ev("harvey.ai", SourceKind.COUNTERPARTY)), now=NOW)
    assert g.status == EdgeStatus.CONFIRMED


def test_self_plus_counterparty_corroborates():
    g = grade(edge(ev("appliedcompute.com", SourceKind.SELF),
                   ev("harvey.ai", SourceKind.COUNTERPARTY)), now=NOW)
    assert g.status == EdgeStatus.CORROBORATED


def test_quantitative_claim_not_corroborated_by_press_echo():
    e = edge(ev("appliedcompute.com", SourceKind.SELF), ev("technews.example", SourceKind.PRESS),
             kind=ClaimKind.QUANTITATIVE, rel=Relation.MEASURED_ON, tail="benchmark:apex-agents")
    g = grade(e, now=NOW)
    assert g.status == EdgeStatus.CLAIMED
    assert any("press citations not counted" in r for r in g.reasons)


def test_verified_needs_checked_primary_record():
    unchecked = edge(ev("leaderboard.example", SourceKind.INDEPENDENT_PRIMARY, entailed=None),
                     kind=ClaimKind.QUANTITATIVE)
    checked = edge(ev("leaderboard.example", SourceKind.INDEPENDENT_PRIMARY, entailed=True),
                   kind=ClaimKind.QUANTITATIVE)
    assert grade(unchecked, now=NOW).status != EdgeStatus.VERIFIED
    assert grade(checked, now=NOW).status == EdgeStatus.VERIFIED


def test_refuted_citation_is_dropped():
    g = grade(edge(ev("harvey.ai", SourceKind.COUNTERPARTY, entailed=False)), now=NOW)
    assert g.status == EdgeStatus.UNSUPPORTED and g.strength == 0.0


def test_contested_and_stale_reduce_strength():
    base = grade(edge(ev("harvey.ai", SourceKind.COUNTERPARTY)), now=NOW).strength
    contested = grade(edge(ev("harvey.ai", SourceKind.COUNTERPARTY),
                           ev("other.example", SourceKind.PRESS, stance=Stance.CONTRADICTS)), now=NOW)
    stale = grade(edge(ev("harvey.ai", SourceKind.COUNTERPARTY, published=date(2023, 1, 1))), now=NOW)
    assert contested.contested and contested.strength < base
    assert stale.stale and stale.strength < base


def test_self_claim_strength_depends_on_claim_kind():
    rel = grade(edge(ev("appliedcompute.com", SourceKind.SELF)), now=NOW)
    num = grade(edge(ev("appliedcompute.com", SourceKind.SELF), kind=ClaimKind.QUANTITATIVE), now=NOW)
    assert rel.status == num.status == EdgeStatus.CLAIMED
    assert rel.strength > num.strength       # naming a customer is costlier to fake than "15x"


def test_apply_writes_grade_into_edge():
    e = apply(edge(ev("harvey.ai", SourceKind.COUNTERPARTY)), now=NOW)
    assert e.status == EdgeStatus.CONFIRMED and e.strength > 0 and e.grade_reasons
