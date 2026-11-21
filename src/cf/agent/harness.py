"""Minimal agent harness: one tool-calling loop, any OpenRouter model, three conditions.

closed_book  – no tools, no context (memory only)
kg_tools     – the KG tools (find_entity, neighbors, evidence, ppr, paths, segment)
oracle       – the task's answer-key subgraph pasted into the prompt (upper bound for retrieval)
"""

from __future__ import annotations

import json
import re
import time

from cf import trace
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


def _touched(result) -> dict:
    """Ids a tool result exposed to the agent: the traversal record (entities, edges, passages)."""
    ent, edg, chk = set(), set(), set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("id", "other_id") and isinstance(v, str) and ":" in v:
                    ent.add(v)
                elif k == "edge_id" and isinstance(v, str):
                    edg.add(v)
                elif k == "chunk_id" and isinstance(v, str):
                    chk.add(v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(result)
    return {"entities": sorted(ent), "edges": sorted(edg), "chunks": sorted(chk)}


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
    elif condition == "graph_rag":
        r = kg.search_text(task["brief"], k=8)
        ctx = "\n".join([f"[{p['chunk_id']}] ({p['url']}) {p['text']}" for p in r["passages"]]
                        + [f"[{e['edge_id']}] {e['head']} —{e['relation']}→ {e['tail']} (status: {e['status']})" for e in r["supporting_edges"]])
        messages = [{"role": "system", "content": SYSTEM_ORACLE},
                    {"role": "user", "content": f"RETRIEVED PASSAGES AND EDGES:\n{ctx}\n\nTASK:\n{task['brief']}"}]
        tools = None
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
                calls.append({"tool": fn, "args": tc["function"].get("arguments"), "step": step,
                              "touched": _touched(result), "thought": (msg.get("content") or "")[:600]})
                trace.event("agent", {"task": task["id"], "model": model, "condition": condition, "step": step,
                                      "tool": fn, "args": tc["function"].get("arguments"),
                                      "result": trace.trunc(result, 3000), "thought": trace.trunc(msg.get("content") or "", 1500)})
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result)[:6000]})
            continue
        final = _parse_final(msg.get("content") or "")
        break
    final = final or {"answer": "", "items": [], "error": "no answer"}
    trace.event("agent", {"task": task["id"], "model": model, "condition": condition, "final": trace.trunc(final, 6000),
                          "n_tool_calls": len(calls)})
    return {"model": model, "condition": condition, "task_id": task["id"], "use_case": task["use_case"],
            "kb_version": kg.kb_version, "run_id": trace.RUN_ID,
            "output": final, "tool_calls": calls, "n_tool_calls": len(calls),
            "cost_usd": round(LLM.spent_usd - spend0, 5), "latency_s": round(time.time() - t0, 1)}
