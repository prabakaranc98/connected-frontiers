"""Deterministic parts of the session builder: scoring and checks (no LLM calls)."""

from cf.bench import sessions as S


class FakeKG:
    def __init__(self):
        self.ents = {"org:a": {"name": "Alpha Labs"}, "org:b": {"name": "Beta AI"}, "method:m": {"name": "LoRA"}}

    def name(self, i):
        return self.ents[i]["name"]

    def match(self, text, k=1):
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
