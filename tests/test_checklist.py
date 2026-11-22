"""Typed checklist: code scorer rules, Jev request/response handling, agreement, defect tests. No paid calls."""

import json

import httpx
import pytest

from cf.agent.kg import KG
from cf.bench import checklist as C
from cf.llm.client import LLM

PROFILE = {"label": "Undergraduate", "background": "Python, PyTorch basics", "constraints": "10-12 weeks, a laptop and one rented GPU",
           "goal": "a feasible capstone", "success": "a working project with an evaluation"}
TASK = {"id": "A-1", "persona": "undergrad_capstone", "question": "What capstone on speculative decoding?"}
GOOD = {"summary": "Reproduce draft-model speculative decoding; vLLM's speedups are self-claimed, so measure them yourself.",
        "learn": ["Transformer inference", "KV caching", "Speculative decoding"],
        "projects": [{"title": "Draft-model speculative decoding", "what": "Reproduce it on a small model",
                      "stack": ["vLLM", "SGLang", "PyTorch"], "first_step": "Run the vLLM example"}],
        "experiments": [{"question": "Does draft length change speedup?", "baseline": "vLLM default speculation length 5",
                         "change": "speculation length 3", "measure": "end-to-end tokens per second on ShareGPT"}],
        "stack": ["vLLM", "SGLang", "ShareGPT"], "sources": []}


@pytest.fixture
def kg(tmp_path):
    ents = [{"id": i, "type": t, "name": n, "aliases": []} for i, t, n in
            [("org:vllm", "org", "vLLM"), ("technology:sglang", "technology", "SGLang"), ("dataset:sharegpt", "dataset", "ShareGPT"),
             ("method:sd", "method", "Speculative decoding")]]
    edges = [{"id": "e1", "head": "org:vllm", "relation": "uses_method", "tail": "method:sd", "status": "claimed",
              "strength": 0.5, "evidence": []}]
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"entities": ents, "edges": edges, "communities": [], "seeds": [], "hierarchy": []}))
    return KG(path=f)


def test_code_scorer_rules_and_abstentions(kg):
    s = C.score_code(GOOD, TASK, PROFILE, kg)
    assert s["baseline"] == 1 and s["measure"] == 1 and s["specific_names"] == 1 and s["flags_uncertainty"] == 1
    assert s["one_change"] is None and s["meets_success"] is None          # judgment items: code abstains
    bad = C.perturb(GOOD, "no_baseline", kg)
    assert C.score_code(bad, TASK, PROFILE, kg)["baseline"] == 0
    assert C.score_code(C.perturb(GOOD, "infeasible", kg), TASK, PROFILE, kg)["fit_compute"] == 0
    # an unknown name makes code abstain on no_invented instead of guessing
    assert C.score_code(C.perturb(GOOD, "fake_name", kg), TASK, PROFILE, kg)["no_invented"] is None


def test_swap_name_replaces_one_known_name_everywhere(kg):
    b = C.swap_name(GOOD, kg, C.FAMOUS_WRONG)
    text = json.dumps(b)
    assert "vLLM" not in text and text.count("Theano") >= 3 and "SGLang" in text


def test_jev_client_request_shape_and_spend(monkeypatch):
    from cf.llm import typesafe
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers.get("authorization"), json.loads(req.content)
        answers = {k: {"type": "noul", "noul": 0.9} for k in seen["body"]["questions"]} | {"one_change": {"type": "refusal"}}
        return httpx.Response(200, json={"model": "typesafe/jev-1.14-20261014", "answers": answers,
                                         "usage": {"input_tokens": 1000, "output_tokens": 20, "cost": 0.042}})

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(typesafe, "LOG", typesafe.LOG.parent / "_test_llm_calls.jsonl")
    before = LLM.spent_usd
    jev = typesafe.Jev(transport=httpx.MockTransport(handler), budget_usd=1e9)
    got = C.score_jev(GOOD, TASK, PROFILE, "REFERENCE", client=jev)
    assert seen["url"] == typesafe.URL and seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == typesafe.MODEL and set(seen["body"]["questions"]) == set(C.IDS)
    assert all(q["type"] == "noul" for q in seen["body"]["questions"].values())
    assert set(seen["body"]["state"]) == {"person", "reference", "advice"}
    assert got["baseline"] == 0.9 and got["one_change"] is None and abs(LLM.spent_usd - before - 0.042) < 1e-9 and abs(jev.spent - 0.042) < 1e-9
    typesafe.LOG.unlink(missing_ok=True)


def test_jev_key_rejection_is_a_budget_stop(monkeypatch):
    from cf.llm import typesafe
    from cf.llm.client import BudgetExceeded
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    jev = typesafe.Jev(transport=httpx.MockTransport(lambda r: httpx.Response(402, text="Insufficient credits")), budget_usd=1e9)
    with pytest.raises(BudgetExceeded):
        jev.ask("x", {"q": {"type": "noul", "instructions": "?"}})


def test_agreement_and_unit_tests_with_stub_scorers(kg, monkeypatch):
    rows = [{"scorer": s, "task_id": f"T{i}", "persona": "p", "model": "m", "condition": "c",
             "items": dict.fromkeys(C.IDS, v) | {"one_change": None}}
            for i in range(4) for s, v in (("code", float(i % 2)), ("jev", float(i % 2)), ("llm:x", 1.0))]
    ag = C.agreement(rows)
    assert ag["code vs jev"]["baseline"]["agree"] == 1.0 and ag["code vs jev"]["baseline"]["kappa"] == 1.0
    assert "one_change" not in ag["code vs jev"] and ag["code vs llm:x"]["baseline"]["agree"] == 0.5
    # a scorer that catches made-up names but lets the famous wrong one pass has a positive familiarity gap
    def fake_score(s, ans, task, profile, sheet, kg_, jev=None):
        t = json.dumps(ans)
        return dict.fromkeys(C.IDS, 1.0) | {"no_invented": 0.0 if "QuantaForge" in t or "Helixon" in t else 1.0}
    monkeypatch.setattr(C, "score_one", fake_score)
    ut = C.unit_tests(["stub"], [TASK], [GOOD], {"undergrad_capstone": PROFILE}, kg, workers=1)
    s = ut["summary"]["stub"]
    assert s["by_kind"]["fake_name"] == 1.0 and s["by_kind"]["famous_wrong"] == 0.0 and s["familiarity_gap"] == 1.0
    assert "familiarity gap" in C.report(rows, ut).lower()


def test_enrich_condition_has_its_own_cache_key():
    from cf.bench import agency as A
    t = {"question": "q", "kb_version": "v1"}
    assert len({A._key(t, "m", c) for c in ("closed_book", "kg_agentic", "kg_enrich")}) == 3
