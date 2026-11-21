"""OpenRouter client: JSON-schema output, retries, per-call cost log, hard budget guard."""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from cf import config

LOG = config.DATA / "interim" / "llm_calls.jsonl"


T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    pass


AUTO = "auto"   # use the model's profile (configs/models.yaml)


def _profiles() -> dict:
    try:
        return config.load_yaml("models.yaml").get("profiles", {}) or {}
    except FileNotFoundError:
        return {}


def reasoning_for(model: str, requested):
    """Resolve the reasoning setting for a model: AUTO → profile; never 'off' for models that require it."""
    prof = _profiles().get(model, {})
    value = prof.get("reasoning", 0) if requested == AUTO else requested
    if prof.get("reasoning_required") and not value:
        value = prof.get("reasoning") or 600
    if "reasoning" in prof and prof["reasoning"] is None and requested == AUTO:
        value = None
    return value


def role_chain(role: str) -> list[str]:
    return (config.load_yaml("models.yaml").get("roles", {}) or {}).get(role, [])


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic model -> JSON schema in the strict form providers accept: $refs inlined, every
    object closed (additionalProperties: false) with all properties required, titles dropped."""
    root = model.model_json_schema()
    defs = root.pop("$defs", {})

    def fix(node, in_properties: bool = False):
        if isinstance(node, list):
            return [fix(x) for x in node]
        if not isinstance(node, dict):
            return node
        if in_properties:  # keys are field names: keep them all
            return {k: fix(v) for k, v in node.items()}
        if "$ref" in node:
            return fix(defs[node["$ref"].rsplit("/", 1)[-1]])
        out = {k: fix(v, in_properties=(k == "properties"))
               for k, v in node.items() if k not in ("title", "default", "description")}
        if out.get("type") == "object":
            out["additionalProperties"] = False
            out["required"] = list(out.get("properties", {}))
        return out

    return fix(root)


class LLM:
    spent_usd: float = 0.0  # shared across instances in one process

    def __init__(self, model: str, budget_usd: float | None = None, timeout: float = 120,
                 fallbacks: list[str] | None = None):
        if not config.is_set("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY missing (see .env)")
        self.model = model
        self.fallbacks = [m for m in (fallbacks or []) if m != model]
        self.budget = budget_usd if budget_usd is not None else float(config.env("CF_LLM_BUDGET_USD", "20"))
        self.base = config.env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.http = httpx.Client(timeout=timeout, headers={
            "Authorization": f"Bearer {config.env('OPENROUTER_API_KEY')}",
            "X-Title": "connected-frontiers",
        })

    def json(self, system: str, user: str, schema: dict, name: str, max_tokens: int = 8000,
             reasoning_max_tokens: int | None = 1500) -> dict:
        """Structured call. Reasoning models spend hidden tokens before answering. "effort: low" is
        only a hint (we saw 19k reasoning tokens with it), so reasoning gets a hard token cap. A
        truncated answer (finish_reason=length) is retried with 2x the output budget."""
        last = None
        budget_tokens = max_tokens
        for attempt in range(4):
            if LLM.spent_usd >= self.budget:
                raise BudgetExceeded(f"spent ${LLM.spent_usd:.4f} >= budget ${self.budget}")
            body = {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0,
                "max_tokens": budget_tokens,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": name, "strict": True, "schema": schema}},
                "provider": {"require_parameters": True},
                "usage": {"include": True},
            }
            rmt = reasoning_for(self.model, reasoning_max_tokens)
            if rmt == 0:                       # explicit: no hidden reasoning at all
                body["reasoning"] = {"enabled": False, "exclude": True}
            elif rmt:
                body["reasoning"] = {"max_tokens": rmt, "exclude": True}
            try:
                r = self.http.post(f"{self.base}/chat/completions", json=body)
                if r.status_code in (429, 500, 502, 503, 504):
                    last = f"HTTP {r.status_code}"
                    time.sleep(2 ** attempt * 2)
                    continue
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code} from {self.model}: {r.text[:300]}")
                data = r.json()
                if "error" in data:
                    raise RuntimeError(f"OpenRouter error: {data['error']}")
                choice = data["choices"][0]
                content = choice["message"].get("content") or ""
                usage = data.get("usage", {})
                cost = float(usage.get("cost") or 0.0)
                LLM.spent_usd += cost
                finish = choice.get("finish_reason") or choice.get("native_finish_reason")
                self._log(name, usage, cost, finish)
                if finish == "length" or not content.strip():
                    last = f"truncated/empty (finish={finish}, max_tokens={budget_tokens})"
                    budget_tokens = min(budget_tokens * 2, 32000)
                    continue
                return _parse_json(content)
            except (httpx.TransportError, json.JSONDecodeError) as e:
                last = repr(e)
                time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM call failed after retries: {last}")

    def chat(self, messages: list[dict], tools: list[dict] | None = None, name: str = "chat",
             max_tokens: int = 3000, reasoning_max_tokens: int | None = 800) -> tuple[dict, dict]:
        """One chat turn (optionally with tools). Returns (assistant message, usage). Logs cost."""
        if LLM.spent_usd >= self.budget:
            raise BudgetExceeded(f"spent ${LLM.spent_usd:.4f} >= budget ${self.budget}")
        body = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": max_tokens,
                "usage": {"include": True}}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
            body["provider"] = {"require_parameters": True}
        rmt = reasoning_for(self.model, reasoning_max_tokens)
        if rmt == 0:
            body["reasoning"] = {"enabled": False, "exclude": True}
        elif rmt:
            body["reasoning"] = {"max_tokens": rmt, "exclude": True}
        last = None
        for attempt in range(4):
            try:
                r = self.http.post(f"{self.base}/chat/completions", json=body)
                if r.status_code in (429, 500, 502, 503, 504):
                    last = f"HTTP {r.status_code}"
                    time.sleep(2 ** attempt * 2)
                    continue
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code} from {self.model}: {r.text[:300]}")
                data = r.json()
                if "error" in data:
                    raise RuntimeError(f"OpenRouter error: {data['error']}")
                usage = data.get("usage", {})
                cost = float(usage.get("cost") or 0.0)
                LLM.spent_usd += cost
                choice = data["choices"][0]
                self._log(name, usage, cost, choice.get("finish_reason"))
                msg = choice["message"]
                empty = not (msg.get("content") or "").strip() and not msg.get("tool_calls")
                if empty and choice.get("finish_reason") == "length" and attempt < 3:
                    # Fallback: the model spent the budget on hidden reasoning. Turn reasoning off
                    # if the model allows it; otherwise give it more room.
                    prof = _profiles().get(self.model, {})
                    if prof.get("reasoning_required"):
                        body["max_tokens"] = min(body["max_tokens"] * 2, 12000)
                    else:
                        body["reasoning"] = {"enabled": False, "exclude": True}
                    last = "empty answer (reasoning ate the budget)"
                    continue
                return msg, usage
            except httpx.TransportError as e:
                last = repr(e)
                time.sleep(2 ** attempt)
        raise RuntimeError(f"chat failed after retries: {last}")

    def parse(self, system: str, user: str, out: type[T], name: str, **kw) -> T:
        """Type-safe call: schema generated from `out`, response validated into `out`.
        One retry on a validation failure; then raise with the validation error."""
        schema = strict_schema(out)
        errors = []
        primary = self.model
        for model in [primary, *self.fallbacks]:
            self.model = model
            try:
                last: ValidationError | None = None
                for _ in range(2):
                    data = self.json(system, user, schema, name, **kw)
                    try:
                        return out.model_validate(data)
                    except ValidationError as e:
                        last = e
                raise RuntimeError(f"schema validation failed: {str(last)[:200]}")
            except BudgetExceeded:
                raise
            except RuntimeError as e:          # fall back to the next model in the role chain
                errors.append(f"{model}: {str(e)[:160]}")
            finally:
                self.model = primary
        raise RuntimeError(f"{name}: all models failed: {' | '.join(errors)}")

    def _log(self, name: str, usage: dict, cost: float, finish: str | None = None) -> None:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        details = usage.get("completion_tokens_details") or {}
        with LOG.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.now(UTC).isoformat(), "model": self.model, "call": name,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens"),
                "finish": finish, "cost_usd": cost, "spent_total_usd": round(LLM.spent_usd, 6),
            }) + "\n")


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    return json.loads(text)
