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
