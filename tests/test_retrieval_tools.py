"""IR tools and retrieval metrics on a tiny graph: top, link, broader, twins, facts handed to notes, stage metrics."""

import json

import pytest

from cf.agent.kg import KG


@pytest.fixture
def kg(tmp_path):
    ents = [{"id": i, "type": t, "name": n, "aliases": []} for i, t, n in [
        ("org:harvey", "org", "Harvey"), ("org:vllm", "org", "vLLM"), ("technology:vllm", "technology", "vLLM"),
        ("org:a", "org", "Alpha"), ("org:b", "org", "Beta"), ("org:c", "org", "Gamma"),
        ("method:reinforcement-learning", "method", "reinforcement learning"), ("method:agentic-rl", "method", "agentic RL"),
        ("method:grpo", "method", "GRPO"), ("model:base", "model", "Base-7B"), ("model:d1", "model", "Deriv-1"),
        ("model:d2", "model", "Deriv-2"), ("technology:lexisnexis", "technology", "LexisNexis")]]
    E = [("org:a", "uses_method", "method:reinforcement-learning", "claimed"), ("org:b", "uses_method", "method:reinforcement-learning", "confirmed"),
         ("org:c", "uses_method", "method:reinforcement-learning", "claimed"), ("org:a", "uses_method", "method:agentic-rl", "claimed"),
         ("org:b", "uses_method", "method:grpo", "claimed"), ("model:d1", "builds_on", "model:base", "verified"),
         ("model:d2", "builds_on", "model:base", "verified"), ("org:harvey", "uses_tech", "technology:lexisnexis", "claimed"),
         ("org:a", "uses_tech", "technology:vllm", "claimed"), ("org:vllm", "uses_method", "method:grpo", "claimed")]
    edges = [{"id": f"{h}|{r}|{t}", "head": h, "relation": r, "tail": t, "status": s, "strength": 0.5,
              "evidence": [{"publisher": h.split(":")[1], "quote": "q", "source_url": "u", "source_kind": "self", "entailed": True}]}
             for h, r, t, s in E]
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"entities": ents, "edges": edges, "communities": [], "seeds": [], "hierarchy": []}))
    return KG(path=f)


def test_top_ranks_by_distinct_sources(kg):
    r = kg.top("uses_method", "in", "method")["results"]
    assert r[0]["name"] == "reinforcement learning" and r[0]["count"] == 3
    assert kg.top("builds_on", "in", "model")["results"][0] == {**kg.top("builds_on", "in", "model")["results"][0], "count": 2, "name": "Base-7B"}
    assert kg.top("no_such_relation")["results"] == []


def test_link_finds_question_entities(kg):
    got = [x["id"] for x in kg.link("Harvey uses LexisNexis; should we try agentic RL?")]
    assert {"org:harvey", "technology:lexisnexis", "method:agentic-rl"} <= set(got)


def test_broader_expands_thin_node_by_head_noun_and_abbreviation(kg):
    assert kg.broader("method:agentic-rl")[0]["id"] == "method:reinforcement-learning"
    kg.empty_hints = True
    assert any("broader" in x for x in kg.neighbors("method:agentic-rl"))


def test_twins_merge_org_and_technology_with_the_same_name(kg):
    assert kg.twins("org:vllm") == ["technology:vllm"]
    assert not any("via_twin" in x for x in kg.neighbors("org:vllm"))        # off by default (kg_tools baseline)
    kg.merge_twins = True
    rows = kg.neighbors("org:vllm")
    assert {x["other_id"] for x in rows} == {"method:grpo", "org:a"} and any(x.get("via_twin") == "technology:vllm" for x in rows)


def test_facts_block_lists_touched_edges_best_supported_first(kg):
    from cf.bench.guidance import _facts
    steps = [{"touched": {"edges": ["org:a|uses_method|method:reinforcement-learning", "model:d1|builds_on|model:base",
                                    "org:b|uses_method|method:reinforcement-learning"]}}]
    assert [e["status"] for e in _facts(kg, steps)] == ["verified", "confirmed", "claimed"]


def test_stage_metrics_separate_retrieved_grounded_used(kg):
    from cf.bench import retrieval as R
    g = R.gold(kg, [{"anchor": "method:reinforcement-learning", "relations": ["uses_method"], "direction": "in"}])
    assert g["entities"] == {"org:a", "org:b", "org:c"}
    run = {"steps": [{"touched": {"entities": ["org:a", "org:b"], "edges": []}}],
           "notes": [{"entities": ["Alpha"], "edge_ids": []}], "answer": {"summary": "Use Alpha. It is unverified."},
           "metrics": {"kb_entities": ["org:a"]}}
    m = R.stage_metrics(kg, run, g)
    assert (m["retrieved"], m["grounded"], m["used"], m["utilisation"], m["doubt"]) == (0.667, 0.333, 0.333, 0.5, 1)
    assert R.gold(kg, [{"top": {"relation": "builds_on", "type": "model", "k": 1}}])["entities"] == {"model:base"}
