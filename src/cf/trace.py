"""Observability: append-only JSONL traces per run.

data/interim/traces/<run_id>/
  llm.jsonl    every LLM call: prompt (system hash + user text), response, reasoning text, tool calls,
               usage, cost, finish, latency, model actually used
  pages.jsonl  crawler: per page fetch result, gate fired, triples, verified/rejected, new edges
  agent.jsonl  benchmark/agent runs: every step, tool call, tool result (truncated)

Set CF_TRACE=0 to disable, CF_TRACE_REASONING=0 to stop requesting reasoning text from models.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, datetime

from cf import config

RUN_ID = os.environ.get("CF_RUN_ID") or f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{os.getpid()}"
ROOT = config.DATA / "interim" / "traces" / RUN_ID
ENABLED = os.environ.get("CF_TRACE", "1") != "0"
WANT_REASONING = os.environ.get("CF_TRACE_REASONING", "1") != "0"
_lock = threading.Lock()


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def trunc(text, n: int) -> str:
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    return text if len(text) <= n else text[:n] + f"…[+{len(text) - n} chars]"


def event(stream: str, record: dict) -> None:
    if not ENABLED:
        return
    rec = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "run": RUN_ID, **record}
    line = json.dumps(rec, ensure_ascii=False, default=str) + "\n"
    with _lock:
        ROOT.mkdir(parents=True, exist_ok=True)
        with (ROOT / f"{stream}.jsonl").open("a") as f:
            f.write(line)


def llm_call(name: str, model: str, body: dict, data: dict | None, latency_s: float, error: str | None = None) -> None:
    msgs = body.get("messages", [])
    system = next((m.get("content", "") for m in msgs if m.get("role") == "system"), "")
    req = [{"role": m.get("role"), "content": trunc(m.get("content") or "", 4000),
            **({"tool_calls": m["tool_calls"]} if m.get("tool_calls") else {})}
           for m in msgs if m.get("role") != "system"]
    rec = {"call": name, "model": model, "latency_s": round(latency_s, 2),
           "request": {"system_sha": sha(system), "system_head": system[:200], "messages": req[-6:],
                       "n_messages": len(msgs), "tools": bool(body.get("tools")), "max_tokens": body.get("max_tokens"),
                       "reasoning": body.get("reasoning"), "schema": (body.get("response_format") or {}).get("json_schema", {}).get("name")}}
    if data:
        ch = (data.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        rec["response"] = {"content": trunc(msg.get("content") or "", 8000),
                           "reasoning": trunc(msg.get("reasoning") or "", 8000) if msg.get("reasoning") else None,
                           "tool_calls": msg.get("tool_calls"), "finish": ch.get("finish_reason"),
                           "provider": data.get("provider"), "model_served": data.get("model")}
        rec["usage"] = data.get("usage")
    if error:
        rec["error"] = trunc(error, 600)
    event("llm", rec)
