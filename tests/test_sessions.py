"""Deterministic parts of the session builder: scoring and checks (no LLM calls)."""

from cf.bench import sessions as S


class FakeKG:
    def __init__(self):
        self.ents = {"org:a": {"name": "Alpha Labs"}, "org:b": {"name": "Beta AI"}, "method:m": {"name": "LoRA"}}

    def name(self, i):
        return self.ents[i]["name"]

    def match(self, text, k=1, exact_first=False):
        for i, e in self.ents.items():
            if e["name"].lower() == text.lower():
                return [(1.0, i)]
        return [(0.2, "org:a")]


def test_set_f1_and_abstention():
    kg = FakeKG()
    key = {"kind": "set", "ids": ["org:a", "org:b"]}
    assert S.score_turn(kg, key, [{"name": "Alpha Labs"}, {"name": "Beta AI"}]) == 1.0
    assert S.score_turn(kg, key, [{"name": "Alpha Labs"}]) == 0.667
    assert S.score_turn(kg, key, [{"name": "Nobody"}]) == 0.0          # unmatched names never count
    empty = {"kind": "set", "ids": [], "allow_empty": True}
    assert S.score_turn(kg, empty, []) == 1.0 and S.score_turn(kg, empty, [{"name": "Beta AI"}]) == 0.0


def test_status_labels_distinguish_claimed_from_confirmed():
    kg = FakeKG()
    key = {"kind": "labels", "labels": {"org:a": "claimed", "org:b": "confirmed"}}
    items = [{"name": "Alpha Labs", "label": "self-claimed"}, {"name": "Beta AI", "label": "confirmed by a partner"}]
    assert S.score_turn(kg, key, items) == 1.0
    assert S.score_turn(kg, key, [{"name": "Alpha Labs", "label": "confirmed"}]) == 0.0


def test_check_flags_leak_missing_and_empty():
    kg = FakeKG()
    s = {"anchors": ["method:m"], "gold_edge_ids": ["e1"],
         "turns": [{"key": {"kind": "set", "ids": ["org:a"]}}, {"key": {"kind": "set", "ids": ["org:zzz"]}},
                   {"key": {"kind": "set", "ids": []}}],
         "messages": ["Who uses LoRA, e.g. Alpha Labs?", "And their partners?", "Anything else?"]}
    p = " | ".join(S.check(kg, s))
    assert "turn 1: answer leaked" in p and "turn 2: ids not in KB" in p and "turn 3: empty key" in p
    assert "LoRA" not in p                                              # anchors may appear in questions


def test_graph_query_multi_hop(tmp_path):
    import json

    from cf.agent.kg import KG
    ents = [{"id": i, "type": t, "name": n, "aliases": []} for i, t, n in
            [("problem:p", "problem", "Protein design"), ("org:a", "org", "Alpha"), ("org:b", "org", "Beta"),
             ("method:m", "method", "Diffusion"), ("method:r", "method", "Rare trick")]]
    E = [("e1", "org:a", "works_on", "problem:p"), ("e2", "org:b", "works_on", "problem:p"),
         ("e3", "org:a", "uses_method", "method:m"), ("e4", "org:b", "uses_method", "method:m"),
         ("e5", "org:b", "uses_method", "method:r")]
    edges = [{"id": i, "head": h, "relation": r, "tail": t, "status": "claimed", "strength": 0.5, "evidence": []}
             for i, h, r, t in E]
    f = tmp_path / "graph.json"
    f.write_text(json.dumps({"entities": ents, "edges": edges, "communities": [], "hierarchy": [], "seeds": []}))
    kg = KG(path=f)
    r = kg.graph_query("problem:p", [{"relation": "works_on", "direction": "in", "type": "org"},
                                     {"relation": "uses_method", "direction": "out"}])
    got = {x["name"]: (x["n_sources"], x["global_in"]) for x in r["results"]}
    assert r["per_step_counts"] == [2, 2]
    assert got == {"Diffusion": (2, 2), "Rare trick": (1, 1)}          # rarity visible without extra calls
    assert all(x["via_edge_ids"] for x in r["results"])


def test_build_gate_loop_offline(monkeypatch):
    """The gate loop runs end to end without LLMs (writer and solvers stubbed)."""
    from cf.bench import sessions as S

    class K:
        kb_version = "test"

        def __init__(self):
            self.ents = {"x:a": {"name": "Alpha"}, "x:b": {"name": "Beta"}}

        def name(self, i):
            return self.ents[i]["name"]

    spec = {"template": "learn", "anchors": ["x:a"], "gold_edge_ids": ["e1"],
            "turns": [{"intent": "i", "key": {"kind": "set", "ids": ["x:b"]}}]}
    monkeypatch.setattr(S, "KG", K)
    monkeypatch.setattr(S, "GENERATORS", {"learn": lambda kg, rnd: dict(spec)})
    monkeypatch.setattr(S, "write", lambda sp, model: {**sp, "persona": "p", "messages": ["What is it related to?"]})
    monkeypatch.setattr(S, "add_facts", lambda kg, s: s)
    scores = iter([[0.0], [1.0]])                       # first solver fails, second passes
    def fake_run(*a, **k):
        t = next(scores)
        return {"turn_scores": t, "mean_score": t[0], "cost_usd": 0}

    monkeypatch.setattr(S, "run_session", fake_run)
    acc, _ = S.build(n=1, writer="w", solvers=["s1", "s2"])
    assert len(acc) == 1 and acc[0]["gate"]["passed"] and [t["passed"] for t in acc[0]["gate"]["tries"]] == [False, True]


def test_discovery_claims_are_recomputed_on_the_graph(tmp_path):
    import json

    from cf.agent.kg import KG
    from cf.bench.discovery import check
    ents = [{"id": i, "type": t, "name": n, "aliases": []} for i, t, n in
            [("problem:p", "problem", "Contract review"), ("org:a", "org", "Alpha"), ("org:b", "org", "Beta"),
             ("method:ft", "method", "Fine-tuning"), ("method:lora", "method", "LoRA")]]
    E = [("e1", "org:a", "works_on", "problem:p", "claimed"), ("e2", "org:b", "works_on", "problem:p", "claimed"),
         ("e3", "org:a", "serves", "org:b", "confirmed")]
    edges = [{"id": i, "head": h, "relation": r, "tail": t, "status": s, "strength": 0.5, "evidence": []} for i, h, r, t, s in E]
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"entities": ents, "edges": edges, "communities": [], "seeds": [],
                             "hierarchy": [{"child": "method:lora", "parent": "method:ft", "kind": "subtype_of"}]}))
    kg = KG(path=f)
    C = lambda **k: {"text": "", "number": 0, "status": "", "edge_ids": [], **k}
    assert check(kg, C(kind="gap", entities=["Contract review"], relation="works_on", number=2))["holds"]
    assert not check(kg, C(kind="gap", entities=["Contract review"], relation="works_on", number=1))["holds"]
    assert check(kg, C(kind="pattern", entities=["Contract review"], relation="works_on", number=2))["holds"]
    assert check(kg, C(kind="status", entities=["Alpha", "Beta"], relation="serves", status="confirmed"))["holds"]
    assert not check(kg, C(kind="status", entities=["Alpha", "Beta"], relation="serves", status="claimed"))["holds"]
    assert check(kg, C(kind="step", entities=["Fine-tuning", "LoRA"], relation=""))["holds"]
    assert not check(kg, C(kind="step", entities=["LoRA", "Fine-tuning"], relation=""))["holds"]
    g = check(kg, C(kind="fact", entities=["Alpha", "Contract review"], relation="works_on", edge_ids=["e1"]))
    assert g["holds"] and g["grounded"]


def test_touched_records_graph_query_edges():
    from cf.agent.harness import _touched
    t = _touched({"start": {"id": "org:a"}, "results": [{"id": "method:m", "via_edge_ids": ["e1", "e2"]}]})
    assert set(t["edges"]) == {"e1", "e2"} and "method:m" in t["entities"]


def test_key_limit_is_budget_stop_not_a_zero_score(monkeypatch):
    """An exhausted provider key must stop work, never be scored as a wrong answer or a failed page."""
    import httpx
    import pytest

    from cf.llm.client import LLM, BudgetExceeded

    class R:
        status_code, text = 403, '{"error":{"message":"Key limit exceeded"}}'

    llm = LLM("x/y")
    monkeypatch.setattr(llm.http, "post", lambda *a, **k: R())
    with pytest.raises(BudgetExceeded):
        llm.chat([{"role": "user", "content": "hi"}], name="t")
    _ = httpx


def test_agency_perturbations_hit_their_target():
    from cf.bench.agency import FAKE, TARGET, perturb
    good = {"summary": "Do X.", "learn": ["SFT", "DPO"], "stack": ["TRL", "vLLM"],
            "projects": [{"title": "P", "what": "Train with TRL on Aya data", "stack": ["TRL"], "first_step": "Run SFT"}],
            "experiments": [{"question": "Does DPO help?", "baseline": "SFT only", "change": "add DPO", "measure": "win rate"}]}
    assert set(TARGET) == {"generic", "false_claim", "infeasible", "no_baseline"}
    assert perturb(good, "generic")["stack"] == ["Python", "PyTorch"]
    assert FAKE["tool"] in perturb(good, "false_claim")["stack"]
    assert "64 H100" in perturb(good, "infeasible")["summary"]
    assert perturb(good, "no_baseline")["experiments"][0]["baseline"] == "none"
    assert good["stack"] == ["TRL", "vLLM"]                 # the original is never modified


def test_personas_catalogue_is_complete():
    from cf.bench.agency import personas
    P = personas()
    assert len(P) >= 8
    for k, p in P.items():
        assert {"label", "anchor", "background", "constraints", "goal", "success", "request"} <= set(p), k
        assert p["anchor"] in ("method", "technology", "org") and "{a}" in p["request"], k
