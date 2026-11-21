"""Type-safe LLM contracts: generated schemas are strict, bad outputs are rejected."""

import json

import pytest
from pydantic import ValidationError

from cf.extract.llm import ExtractionOut, VerifyOut, XTriple
from cf.llm.client import strict_schema


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


@pytest.mark.parametrize("model", [ExtractionOut, VerifyOut])
def test_schema_is_strict_and_self_contained(model):
    s = strict_schema(model)
    assert "$ref" not in json.dumps(s) and "$defs" not in s
    for node in _walk(s):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def test_relation_enum_in_schema():
    s = strict_schema(ExtractionOut)
    rel = s["properties"]["triples"]["items"]["properties"]["relation"]
    assert "serves" in rel["enum"] and "acquired" in rel["enum"]


GOOD = {"head": "Applied Compute", "head_type": "org", "relation": "serves", "tail": "Harvey",
        "tail_type": "org", "quote": "with Harvey", "claim_kind": "relational"}


def test_valid_triple_parses():
    assert XTriple.model_validate(GOOD).relation == "serves"


@pytest.mark.parametrize("bad", [
    {"relation": "is_friends_with"},        # not in the closed relation set
    {"head_type": "person"},                # people are off in v1
    {"extra_field": 1},                     # extra keys are forbidden
])
def test_invalid_triples_rejected(bad):
    with pytest.raises(ValidationError):
        XTriple.model_validate({**GOOD, **bad})


def test_not_enough_info_is_not_support():
    from datetime import datetime

    from cf.graph.grading import grade
    from cf.graph.schema import Edge, EdgeStatus, Evidence, SourceKind, Stance
    ev = Evidence(source_url="https://harvey.ai/x", publisher="harvey.ai", quote="…",
                  observed_at=datetime(2026, 11, 21), extractor_version="t",
                  source_kind=SourceKind.COUNTERPARTY, stance=Stance.NOT_ENOUGH_INFO, entailed=False)
    g = grade(Edge(head="org:a", relation="serves", tail="org:harvey", evidence=[ev]),
              now=datetime(2026, 11, 21))
    assert g.status == EdgeStatus.UNSUPPORTED and not g.contested
