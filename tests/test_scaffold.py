from datetime import datetime

import pytest
from typer.testing import CliRunner

from cf.cli import app
from cf.graph.schema import Edge, EdgeStatus, Evidence, Relation


def test_doctor_runs():
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "OPENROUTER_API_KEY" in result.output


def test_unbuilt_command_exits_2():
    assert CliRunner().invoke(app, ["crawl"]).exit_code == 2


def _ev(url="https://www.appliedcompute.com/training"):
    return Evidence(source_url=url, publisher=url.split("/")[2], quote="#1 on Harvey's Legal Agent Benchmark",
                    observed_at=datetime(2026, 11, 21), extractor_version="manual")


def test_edge_needs_evidence():
    with pytest.raises(ValueError):
        Edge(head="org:harvey", relation=Relation.MEASURED_ON, tail="benchmark:harvey-lab", evidence=[])


def test_edge_counts_distinct_sources():
    e = Edge(head="org:harvey", relation=Relation.MEASURED_ON, tail="benchmark:harvey-lab",
             evidence=[_ev(), _ev(), _ev("https://www.harvey.ai/")])
    assert e.n_sources == 2
    assert e.status == EdgeStatus.CLAIMED
