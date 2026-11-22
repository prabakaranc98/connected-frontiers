"""TypeSafe Jev ("System One"): a typed evaluation model. It does not write text; it answers typed questions
(`noul` = yes/no probability, `choice`, `score`) about a `state`, with probabilities.

Called through OpenRouter's Decisions API (alpha; the shape may change), with the same OPENROUTER_API_KEY as every
other model here: POST https://openrouter.ai/api/alpha/decisions, body {model, state, questions}, response
{model, answers, usage: {cost, ...}}. Probed 2026-11-22: `typesafe/jev-1.14` answers (served as
jev-1.14-20261014, provider TypeSafe); `typesafe/jev-latest` does not exist on OpenRouter. A 304-token request
cost $0.0000128. The same request shape works on TypeSafe's own API (/v1/systemone), whose SDKs OpenRouter supports.

Known limits (TypeSafe docs): a noul cannot abstain; weak at counting, arithmetic and dates; reads questions
literally; text that claims to satisfy a rubric can raise its answer. So it is one scorer among several here,
never the only one. A `refusal` answer is possible and is returned as None.

Spend is added to the shared `LLM.spent_usd`, so `CF_LLM_BUDGET_USD` caps Jev and the LLM judges together.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import httpx

from cf import config
from cf.llm.client import _LOG_LOCK, _SPEND_LOCK, LLM, LOG, BudgetExceeded

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.14"             # pinned minor version: thresholds must not move with a new release


class Jev:
    def __init__(self, model: str = MODEL, budget_usd: float | None = None, timeout: float = 60,
                 transport: httpx.BaseTransport | None = None):
        if not config.is_set("OPENROUTER_API_KEY") and transport is None:
            raise RuntimeError("OPENROUTER_API_KEY missing (see .env)")
        self.model = model
        self.budget = budget_usd if budget_usd is not None else float(config.env("CF_LLM_BUDGET_USD", "20"))
        self.spent = 0.0
        self.http = httpx.Client(timeout=timeout, transport=transport, headers={
            "Authorization": f"Bearer {config.env('OPENROUTER_API_KEY', '')}", "Content-Type": "application/json",
            "X-Title": "connected-frontiers"})

    def ask(self, state, questions: dict, name: str = "jev") -> dict:
        """questions: {id: {"type": "noul"|"choice"|"score", "instructions": ..., "criteria": ...}}.
        Returns the `answers` dict, keyed like `questions`."""
        if LLM.spent_usd >= self.budget:
            raise BudgetExceeded(f"spent ${LLM.spent_usd:.4f} >= budget ${self.budget}")
        body = {"model": self.model, "state": state, "questions": questions}
        last = None
        for attempt in range(5):
            try:
                r = self.http.post(URL, json=body)
            except httpx.TransportError as e:
                last = repr(e)
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504, 524, 529):
                last = f"HTTP {r.status_code}"
                time.sleep(float(r.headers.get("retry-after") or 2 ** attempt))
                continue
            if r.status_code == 402 or (r.status_code in (401, 403) and ("limit" in r.text.lower() or "credit" in r.text.lower())):
                raise BudgetExceeded(f"key limit or credits exhausted: {r.text[:200]}")
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code} from {self.model}: {r.text[:300]}")
            data = r.json()
            usage = data.get("usage") or {}
            cost = float(usage.get("cost") or 0.0)
            with _SPEND_LOCK:
                LLM.spent_usd += cost
            self.spent += cost
            self._log(name, usage, cost, data.get("model"))
            return data["answers"]
        raise RuntimeError(f"Jev call failed after retries: {last}")

    def _log(self, name: str, usage: dict, cost: float, served: str | None) -> None:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK, LOG.open("a") as f:
            f.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "model": served or self.model, "call": name,
                                "prompt_tokens": usage.get("input_tokens"), "completion_tokens": usage.get("output_tokens"),
                                "cost_usd": cost, "spent_total_usd": round(LLM.spent_usd, 6)}) + "\n")
