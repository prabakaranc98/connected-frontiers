"""Minimal agent harness: one tool-calling loop, any OpenRouter model, three conditions.

closed_book  – no tools, no context (memory only)
kg_tools     – the KG tools (find_entity, neighbors, evidence, ppr, paths, segment)
oracle       – the task's answer-key subgraph pasted into the prompt (upper bound for retrieval)
"""

from __future__ import annotations

import json
import re
import time

from cf.agent.kg import KG, TOOL_SPECS
from cf.llm.client import LLM

CONTRACT = """When you are done, reply with ONLY one JSON object:
{"answer": "<your analysis in prose; cite edge ids like [edge_id] after each factual statement>",
 "items": [{"name": "<entity name>", "label": "<optional label asked for by the task>", "edge_ids": ["<supporting edge ids>"]}]}
"""

SYSTEM_TOOLS = """You are an analyst of the frontier-AI research and industry ecosystem with access to a knowledge graph.
Use the tools to find entities, follow their relations and read evidence. Ground every factual statement in an edge
you retrieved and cite its edge_id. Match wording to evidence status: verified -> state plainly; corroborated or
confirmed -> "reported by ..."; claimed -> "<publisher> claims ..."; if the graph doesn't contain it, say so instead
of guessing. Be efficient: a few targeted tool calls, then answer.
""" + CONTRACT

SYSTEM_CLOSED = """You are an analyst of the frontier-AI research and industry ecosystem. Answer from your own knowledge.
If you are not sure, say so. Leave edge_ids empty.
""" + CONTRACT

SYSTEM_ORACLE = """You are an analyst of the frontier-AI research and industry ecosystem. You are given the relevant part of a
knowledge graph below (edges with ids and evidence status). Use only it, cite edge ids, and match wording to evidence status.
""" + CONTRACT


def _parse_final(text: str) -> dict:
    text = text or ""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(0))
            if isinstance(d, dict):
                d.setdefault("items", [])
                return d
        except json.JSONDecodeError:
            pass
    return {"answer": text, "items": [], "parse_error": True}


def run(model: str, task: dict, condition: str, kg: KG, max_steps: int = 10, reasoning: int | None = 800) -> dict:
    llm = LLM(model)
    t0, spend0 = time.time(), LLM.spent_usd
    if condition == "kg_tools":
        messages = [{"role": "system", "content": SYSTEM_TOOLS}, {"role": "user", "content": task["brief"]}]
        tools = TOOL_SPECS
    elif condition == "oracle":
        ctx = "\n".join(task.get("oracle_edges", []))
        messages = [{"role": "system", "content": SYSTEM_ORACLE},
                    {"role": "user", "content": f"KNOWLEDGE GRAPH EXCERPT:\n{ctx}\n\nTASK:\n{task['brief']}"}]
        tools = None
    else:
        messages = [{"role": "system", "content": SYSTEM_CLOSED}, {"role": "user", "content": task["brief"]}]
        tools = None

    calls: list[dict] = []
    final = None
    for step in range(max_steps):
        force_final = step == max_steps - 1
        if force_final and tools:
            messages.append({"role": "user", "content": "Step budget reached. Answer now with the JSON object."})
        try:
            msg, _ = llm.chat(messages, tools=None if force_final else tools, name=f"bench_{condition}",
                              max_tokens=3000, reasoning_max_tokens=reasoning)
        except RuntimeError as e:
            final = {"answer": "", "items": [], "error": str(e)[:200]}
            break
        tcs = msg.get("tool_calls") or []
        if tcs and tools and not force_final:
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcs})
            for tc in tcs:
                fn = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                    result = getattr(kg, fn)(**args) if fn in {t["function"]["name"] for t in TOOL_SPECS} else {"error": "unknown tool"}
                except (TypeError, ValueError, KeyError) as e:
                    result = {"error": f"bad arguments: {e}"}
                calls.append({"tool": fn, "args": tc["function"].get("arguments")})
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result)[:6000]})
            continue
        final = _parse_final(msg.get("content") or "")
        break
    final = final or {"answer": "", "items": [], "error": "no answer"}
    return {"model": model, "condition": condition, "task_id": task["id"], "use_case": task["use_case"],
            "output": final, "tool_calls": calls, "n_tool_calls": len(calls),
            "cost_usd": round(LLM.spent_usd - spend0, 5), "latency_s": round(time.time() - t0, 1)}
