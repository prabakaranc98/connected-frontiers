"""Scorecard pieces that need no KB on disk or LLM."""

from cf.eval import scorecard as S


def _g():
    ents = [{"id": f"org:{x}", "type": "org", "name": x} for x in "abcd"]
    ev = lambda kind: [{"publisher": kind, "source_kind": kind}]
    edges = [{"head": "org:a", "tail": "org:b", "status": "claimed", "evidence": ev("self")},
             {"head": "org:b", "tail": "org:c", "status": "claimed", "evidence": ev("press")},
             {"head": "org:c", "tail": "org:d", "status": "unsupported", "evidence": ev("self")}]
    return {"entities": ents, "edges": edges}


def test_capture_recapture():
    c = S._coverage(_g())
    # self capture {a,b,c,d}, independent {b,c}, recaptured 2 → N̂ = 4·2/2 = 4
    assert (c["capture_self"], c["capture_independent"], c["recaptured"], c["lincoln_petersen_estimate"]) == (4, 2, 2, 4)


def test_structure_ignores_unsupported_edges():
    st = S._structure(_g())
    assert st["largest_component_share"] == 0.75 and st["isolated_share"] == 0.25
    assert S._signed(0.123) == "+0.12" and S._signed(None) == "–"
