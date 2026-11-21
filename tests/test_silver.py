"""Ensemble-vote helpers (no LLM)."""

from cf.eval.silver import _majority, fleiss_kappa


def test_majority_needs_quorum():
    assert _majority(["yes", "yes", "yes", "no"], need=3) == "yes"
    assert _majority(["yes", "yes", "no", "no"], need=3) is None


def test_fleiss_kappa_perfect_and_chance():
    assert fleiss_kappa([["yes"] * 4, ["no"] * 4, ["yes"] * 4], ["yes", "no"]) == 1.0
    k = fleiss_kappa([["yes", "no", "yes", "no"], ["no", "yes", "no", "yes"]], ["yes", "no"])
    assert k < 0
