from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from qa_harness.config import LLMConfig
from qa_harness.llm import LLM, BudgetExceeded, LLMError, LLMRefusal, _inline_refs
from qa_harness.models import GenerationResult
from qa_harness.tools import ToolRegistry

from .fakes import FakeAnthropic, response, text_block, tool_use


class EchoIn(BaseModel):
    text: str


def _registry() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.add("echo", "Echo text back", EchoIn)
    def echo(inp: EchoIn) -> str:
        return inp.text.upper()

    return reg


FINISH = {"files": [{"path": "a.py", "purpose": "x"}], "test_node_ids": ["a.py::t"], "summary": "done"}


def test_agent_loop_validates_tools_and_finish():
    client = FakeAnthropic(
        [
            # Parallel calls: one valid, one with a schema error.
            response(text_block("exploring"), tool_use("t1", "echo", {"text": "hi"}), tool_use("t2", "echo", {})),
            # Bad finish payload is rejected and the model retries.
            response(tool_use("t3", "finish", {"files": "nope"})),
            response(tool_use("t4", "finish", FINISH)),
        ]
    )
    llm = LLM(LLMConfig(), client=client)
    outcome = llm.run_agent(system="s", task="t", tools=_registry(), result_model=GenerationResult)

    assert isinstance(outcome.result, GenerationResult) and outcome.turns == 3
    second = client.requests[1]["messages"]
    results = second[-1]["content"]
    # Both tool results come back in one user message, the invalid one flagged as an error.
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert results[0]["content"] == "HI" and "is_error" not in results[0]
    assert results[1]["is_error"] is True
    third = client.requests[2]["messages"][-1]["content"]
    assert third[0]["is_error"] is True and "Invalid finish payload" in third[0]["content"]

    req = client.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["thinking"] == {"type": "adaptive"}
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["cache_control"] == {"type": "ephemeral"}
    assert req["tools"][-1]["name"] == "finish" and "$defs" not in str(req["tools"][-1]["input_schema"])
    assert llm.cost.calls == 3 and llm.cost.spent_usd > 0


def test_history_is_append_only():
    client = FakeAnthropic(
        [response(tool_use("t1", "echo", {"text": "a"})), response(tool_use("t2", "finish", FINISH))]
    )
    LLM(LLMConfig(), client=client).run_agent(system="s", task="t", tools=_registry(), result_model=GenerationResult)
    first, second = client.requests[0]["messages"], client.requests[1]["messages"]
    assert second[: len(first)] == first


def test_nudges_once_then_fails_without_finish():
    client = FakeAnthropic([response(text_block("done?"), stop_reason="end_turn")] * 2)
    with pytest.raises(LLMError, match="without calling finish"):
        LLM(LLMConfig(), client=client).run_agent(
            system="s", task="t", tools=_registry(), result_model=GenerationResult
        )


def test_truncated_tool_call_is_not_executed():
    calls = []
    reg = ToolRegistry()

    @reg.add("echo", "Echo", EchoIn)
    def echo(inp: EchoIn) -> str:
        calls.append(inp.text)
        return "ok"

    client = FakeAnthropic(
        [
            response(tool_use("t1", "echo", {"text": "partial"}), stop_reason="max_tokens"),
            response(tool_use("t2", "finish", FINISH)),
        ]
    )
    LLM(LLMConfig(), client=client).run_agent(system="s", task="t", tools=reg, result_model=GenerationResult)
    assert calls == []
    assert "truncated" in client.requests[1]["messages"][-1]["content"][0]["content"]


def test_refusal_raises():
    resp = response(stop_reason="refusal")
    resp.stop_details = SimpleNamespace(category="cyber")
    with pytest.raises(LLMRefusal, match="cyber"):
        LLM(LLMConfig(), client=FakeAnthropic([resp])).run_agent(
            system="s", task="t", tools=_registry(), result_model=GenerationResult
        )


def test_budget_is_enforced():
    llm = LLM(LLMConfig(max_usd_per_run=0.0001), client=FakeAnthropic([response(tool_use("t", "echo", {"text": "a"}))]))
    with pytest.raises(BudgetExceeded):
        llm.run_agent(system="s", task="t", tools=_registry(), result_model=GenerationResult)


def test_structured_returns_parsed_output():
    parsed = GenerationResult(files=[], test_node_ids=[], summary="x")
    resp = response(stop_reason="end_turn")
    resp.parsed_output = parsed
    client = FakeAnthropic([resp])
    out = LLM(LLMConfig(effort="medium"), client=client).structured(system="s", content="c", output=GenerationResult)
    assert out is parsed
    assert client.requests[0]["output_format"] is GenerationResult
    assert client.requests[0]["output_config"] == {"effort": "medium"}


def test_inline_refs_resolves_nested_models():
    schema = _inline_refs(GenerationResult.model_json_schema())
    assert "$defs" not in schema
    assert schema["properties"]["files"]["items"]["properties"]["path"]["type"] == "string"
