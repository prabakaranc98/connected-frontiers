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


def test_locale_gate_covers_region_codes():
    from cf.crawl.noise import url_ok
    for path in ("/ar-SA/hub/customers/x", "/pt-BR/blog/y", "/zh-Hans/docs", "/fr/"):
        assert not url_ok("https://example.com" + path, path), path
    for path in ("/ai/agents", "/blog/post", "/customers/acme"):
        assert url_ok("https://example.com" + path, path), path


def test_verify_cache_rejects_mismatched_verdicts(tmp_path, monkeypatch):
    import json

    from cf import cache
    from cf.extract.llm import Extraction, Verdict, XTriple
    monkeypatch.setattr(cache, "VERIFY", tmp_path)

    class Page:
        url, raw_sha256 = "https://x.ai/", "abc"

    class Ve:
        version = "test"
        calls = 0

        def verify(self, triples, page):
            Ve.calls += 1
            return [Verdict(i=i, entailed=True, stance="supports") for i in range(len(triples))]

    t = XTriple(head="A", head_type="org", relation="serves", tail="B", tail_type="org", quote="q", claim_kind="relational")
    two, three = Extraction([], [t, t], 0), Extraction([], [t, t, t], 0)
    ve = Ve()
    v, hit = cache.get_verdicts(Page, two, "k", ve)
    assert len(v) == 2 and not hit
    v, hit = cache.get_verdicts(Page, three, "k", ve)          # same key, different triples → re-verify
    assert len(v) == 3 and not hit and Ve.calls == 2
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["triples_sha"]


def test_metric_gate_keeps_numeric_names():
    from cf.crawl.noise import is_metric
    for n, t in [("1B events per month", "benchmark"), ("up to 99.6% cache hits", "technology"),
                 ("30-minute outage prediction lead time", "benchmark"), ("13B parameter model", "model"),
                 ("2026 Best in Tech Awards", "benchmark")]:
        assert is_metric(n, t), n
    for n, t in [("10x Genomics", "org"), ("11x", "org"), ("10 years of AlphaGo", "paper"),
                 ("3D Gaussian Splatting", "method"), ("4o Image Generation", "technology"), ("GPT-4o", "model")]:
        assert not is_metric(n, t), n
