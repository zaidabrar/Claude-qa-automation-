"""Thin layer over the Anthropic SDK used by every stage.

* ``structured()`` - one call, schema-validated pydantic output (planning, triage, bug drafting).
* ``run_agent()``  - a tool-using loop that ends when the model calls ``finish`` with a
  schema-validated result (test generation, self-healing).

Both enforce a per-run dollar budget, handle ``refusal``/``max_tokens`` stop reasons
explicitly, opt into server-side refusal fallbacks, and keep the message history
append-only (thinking blocks are passed back unchanged) so preserved thinking and
prompt caching both stay valid.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from .config import LLMConfig
from .tools import ToolRegistry

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens: (input, output, cache_read). Cache writes are billed at 1.25x input.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}

# Non-streaming requests above ~21k max_tokens trip the SDK's long-request guard.
STRUCTURED_MAX_TOKENS = 20000


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


@dataclass
class CostTracker:
    limit_usd: float
    spent_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    calls: int = 0

    def add(self, model: str, usage: Any) -> None:
        price_in, price_out, price_cache = PRICES.get(model, PRICES["claude-opus-5-5"])
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        cread = getattr(usage, "cache_read_input_tokens", 0) or 0
        cwrite = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.input_tokens += inp + cwrite
        self.output_tokens += out
        self.cache_read_tokens += cread
        self.calls += 1
        self.spent_usd += (
            inp * price_in + cwrite * price_in * 1.25 + out * price_out + cread * price_cache
        ) / 1_000_000

    def check(self) -> None:
        if self.spent_usd >= self.limit_usd:
            raise BudgetExceeded(f"LLM budget exhausted: ${self.spent_usd:.2f} of ${self.limit_usd:.2f}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "spent_usd": round(self.spent_usd, 4),
            "limit_usd": self.limit_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "calls": self.calls,
        }


@dataclass
class AgentOutcome:
    result: BaseModel
    turns: int
    transcript: list[dict[str, Any]] = field(default_factory=list)


EventSink = Callable[[str, dict[str, Any]], None]


class LLM:
    def __init__(
        self,
        cfg: LLMConfig,
        client: anthropic.Anthropic | None = None,
        on_event: EventSink | None = None,
    ):
        self.cfg = cfg
        self.client = client or anthropic.Anthropic()
        self.cost = CostTracker(limit_usd=cfg.max_usd_per_run)
        self.on_event = on_event or (lambda kind, data: None)

    # ------------------------------------------------------------------ helpers

    def _common(self, effort: str | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.cfg.model,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort or self.cfg.effort},
        }
        if self.cfg.fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    def _account(self, response: Any) -> None:
        self.cost.add(getattr(response, "model", self.cfg.model), response.usage)
        self.on_event("llm_usage", {"model": response.model, **self.cost.as_dict()})

    @staticmethod
    def _check_stop(response: Any, where: str) -> None:
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMRefusal(f"{where}: model declined the request (category={category})")

    # ------------------------------------------------------------------ structured

    def structured(
        self,
        *,
        system: str,
        content: str | list[dict[str, Any]],
        output: type[T],
        effort: str | None = None,
    ) -> T:
        self.cost.check()
        response = self.client.beta.messages.parse(
            max_tokens=STRUCTURED_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=output,
            **self._common(effort),
        )
        self._account(response)
        self._check_stop(response, f"structured[{output.__name__}]")
        if response.stop_reason == "max_tokens":
            raise LLMError(f"structured[{output.__name__}]: output truncated at max_tokens")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"structured[{output.__name__}]: no parsable output")
        return parsed

    # ------------------------------------------------------------------ agent loop

    def run_agent(
        self,
        *,
        system: str,
        task: str,
        tools: ToolRegistry,
        result_model: type[T],
        effort: str | None = None,
        max_turns: int | None = None,
    ) -> AgentOutcome:
        """Run a tool loop until the model calls ``finish`` with a valid ``result_model``."""
        tool_defs = tools.definitions() + [
            {
                "name": "finish",
                "description": (
                    "Call exactly once when the task is complete and verified. "
                    "The input is your final structured result."
                ),
                "input_schema": _inline_refs(result_model.model_json_schema()),
                "eager_input_streaming": True,
            }
        ]
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        max_turns = max_turns or self.cfg.max_agent_turns
        nudged = False

        for turn in range(1, max_turns + 1):
            self.cost.check()
            with self.client.beta.messages.stream(
                max_tokens=self.cfg.max_tokens,
                system=system,
                tools=tool_defs,
                messages=messages,
                cache_control={"type": "ephemeral"},
                **self._common(effort),
            ) as stream:
                response = stream.get_final_message()
            self._account(response)
            self._check_stop(response, "agent")
            # Append-only history: the full content, thinking blocks included.
            messages.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            for b in response.content:
                if b.type == "text" and b.text.strip():
                    self.on_event("agent_text", {"turn": turn, "text": b.text[:2000]})

            if response.stop_reason == "max_tokens" and not tool_uses:
                messages.append({"role": "user", "content": "Your reply was cut off. Continue, using smaller steps."})
                continue

            if not tool_uses:
                if nudged:
                    raise LLMError("agent ended without calling finish")
                nudged = True
                messages.append(
                    {
                        "role": "user",
                        "content": "If the task is done, call `finish` with the result. Otherwise continue.",
                    }
                )
                continue

            results: list[dict[str, Any]] = []
            finished: BaseModel | None = None
            for tu in tool_uses:
                if response.stop_reason == "max_tokens" and tu is tool_uses[-1]:
                    # Input may be truncated mid-JSON; never execute it.
                    results.append(_tool_error(tu.id, "Input was truncated (max_tokens). Re-issue the call."))
                    continue
                if tu.name == "finish":
                    try:
                        finished = result_model.model_validate(_as_dict(tu.input))
                        results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "ok"})
                    except (ValidationError, ValueError) as exc:
                        results.append(_tool_error(tu.id, f"Invalid finish payload: {exc}"))
                    continue
                self.on_event("tool_call", {"turn": turn, "tool": tu.name, "input": _preview(tu.input)})
                output, is_error = tools.execute(tu.name, _as_dict(tu.input))
                self.on_event(
                    "tool_result", {"turn": turn, "tool": tu.name, "error": is_error, "output": output[:1500]}
                )
                block: dict[str, Any] = {"type": "tool_result", "tool_use_id": tu.id, "content": output}
                if is_error:
                    block["is_error"] = True
                results.append(block)

            # All results for one assistant turn go back in a single user message.
            messages.append({"role": "user", "content": results})
            if finished is not None:
                return AgentOutcome(result=finished, turns=turn, transcript=_serializable(messages))

        raise LLMError(f"agent did not finish within {max_turns} turns")


# ---------------------------------------------------------------------- utilities


def _tool_error(tool_use_id: str, message: str) -> dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": message, "is_error": True}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):  # eager streaming can hand back raw JSON text
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("tool input is not a JSON object")


def _preview(value: Any, limit: int = 400) -> str:
    text = json.dumps(value, default=str) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "..."


def _serializable(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        content = m["content"]
        if isinstance(content, list):
            content = [c.model_dump(mode="json") if hasattr(c, "model_dump") else c for c in content]
        out.append({"role": m["role"], "content": content})
    return out


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve pydantic ``$defs`` references so tool schemas are self-contained."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return resolve(defs[name])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)
