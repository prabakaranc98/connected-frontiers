import json

from cf import config, release


def _jl(p, rows):
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_agency_rows_skip_invalidated_runs_and_dedupe(tmp_path, monkeypatch):
    ev = tmp_path / "eval"
    good, bad = ev / "experiments" / "x" / "0002", ev / "experiments" / "x" / "0001"
    for d in (good, bad):
        d.mkdir(parents=True)
        _jl(d / "tasks.jsonl", [{"id": "A-1", "kb_version": "v1"}])
        run = {"task_id": "A-1", "model": "m", "condition": "kg_agentic", "run_id": "r1", "kb_version": "v1", "notes": []}
        _jl(d / "runs.jsonl", [run, run])
        _jl(d / "scores.jsonl", [{"judge": "j", "task_id": "A-1"}])
        _jl(d / "pairwise.jsonl", [])
    _jl(ev / "experiments.jsonl", [
        {"ts": "0001", "level": "agency", "dir": str(bad)},
        {"ts": "0002", "level": "agency", "correction_of": "0001", "valid": False},
        {"ts": "0002", "level": "agency", "dir": str(good)},
    ])
    monkeypatch.setattr(config, "EVAL", ev)
    assert release.valid_experiment_dirs() == [good]
    tasks, runs, judg = release.agency_rows("v1")
    assert len(tasks) == 1 and len(runs) == 1 and runs[0]["experiment"] == "x/0002"
    assert [j["kind"] for j in judg] == ["score"]
    assert release.agency_rows("v2") == ([], [], [])
