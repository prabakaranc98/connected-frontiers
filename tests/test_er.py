"""Entity-resolution rules (no LLM): normalization, acronyms, blocking, union-find."""

from cf.resolve.er import Candidate, candidates, is_acronym_of, merge_groups, normalize


def E(i, name, t="method", domain=None):
    return {"id": i, "name": name, "type": t, "domain": domain}


def test_normalize_possessive_and_suffix():
    assert normalize("Harvey's Legal Agent Benchmark", "benchmark") == "harvey legal agent benchmark"
    assert normalize("Cohere Inc.", "org") == "cohere"


def test_acronyms():
    assert is_acronym_of("RL", "Reinforcement Learning")
    assert is_acronym_of("LAB", "Legal Agent Benchmark")
    assert not is_acronym_of("RL", "Retrieval")            # single word
    assert not is_acronym_of("SFT", "Reinforcement Learning")


def test_candidates_are_blocked_by_type():
    ents = {"m:rl": E("m:rl", "RL"), "b:rl": E("b:rl", "Reinforcement Learning", "benchmark")}
    assert candidates(ents) == []                          # method vs benchmark: never compared


def test_candidate_reasons():
    ents = {
        "m:rl": E("m:rl", "RL"), "m:rl2": E("m:rl2", "Reinforcement learning"),
        "b:lab": E("b:lab", "Legal Agent Benchmark", "benchmark"),
        "b:hlab": E("b:hlab", "Harvey's Legal Agent Benchmark", "benchmark"),
        "o:a": E("o:a", "Harvey", "org", "harvey.ai"), "o:b": E("o:b", "Harvey AI", "org", "harvey.ai"),
        "o:c": E("o:c", "Harvey", "org", "harvey.com"),
    }
    by = {(c.a, c.b): c for c in candidates(ents)}
    assert by[("m:rl", "m:rl2")].reason == "acronym" and not by[("m:rl", "m:rl2")].auto
    assert by[("b:lab", "b:hlab")].reason == "containment"
    assert not by[("o:a", "o:b")].auto                      # same domain → judge, not auto (silver v1 finding)
    assert ("o:a", "o:c") not in by                        # different known domains: never merged


def test_union_find_transitive():
    m = merge_groups(["a", "b", "c", "d"], [Candidate("a", "b", "", 1, True), Candidate("b", "c", "", 1, True)])
    assert m["a"] == m["b"] == m["c"] and m["d"] == "d"


def test_silver_v1_regressions_go_to_judge():
    """Pairs the silver ensemble showed were wrongly auto-merged must reach the judge (part_of/different)."""
    ents = {
        "s": E("s", "Stanford", "org", "stanford.edu"), "h": E("h", "Stanford HAI", "org", "stanford.edu"),
        "n": E("n", "NVIDIA", "org", "nvidia.com"), "r": E("r", "NVIDIA Research", "org", "nvidia.com"),
        "g": E("g", "Google", "org"), "ga": E("ga", "Google AI", "org"),
        "c1": E("c1", "Cohere Inc.", "org"), "c2": E("c2", "Cohere", "org"),
    }
    by = {frozenset((c.a, c.b)): c for c in candidates(ents)}
    for a, b in [("s", "h"), ("n", "r"), ("g", "ga")]:
        c = by.get(frozenset((a, b)))
        assert c is not None and not c.auto, (a, b)
    assert by[frozenset(("c1", "c2"))].auto                    # legal suffix only → safe auto-merge
