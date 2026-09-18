"""Network-free contracts for the Responses generator and local MCP bridge."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from app.services.rag.openai_responses import OpenAIResponsesLLMWrapper

pytestmark = pytest.mark.unit

TOOLS = [
    {
        "name": "get_market_prices",
        "description": "Actual market prices",
        "inputSchema": {
            "type": "object",
            "properties": {"currency": {"type": "string"}},
            "required": ["currency"],
        },
    }
]


def response(output=None, status="completed"):
    return {
        "status": status,
        "output": (
            output
            if output is not None
            else [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Actual answer"}],
                }
            ]
        ),
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_tokens_details": {"cached_tokens": 30, "cache_write_tokens": 10},
            "output_tokens_details": {"reasoning_tokens": 7},
        },
    }


def function(name="get_market_prices", call_id="call1", arguments='{"currency":"EUR"}'):
    return {
        "type": "function_call",
        "name": name,
        "call_id": call_id,
        "arguments": arguments,
    }


@pytest.fixture
def wrapper(monkeypatch):
    client = MagicMock()
    cost = MagicMock()
    monkeypatch.setattr("app.services.rag.openai_responses.track_tokens_and_cost", cost)
    obj = OpenAIResponsesLLMWrapper(
        client,
        "openai:gpt-6-astra",
        4096,
        "low",
        "http://local/mcp",
        input_cost_per_token=10e-6,
        cached_input_cost_per_token=1e-6,
        cache_write_cost_per_token=12.5e-6,
        output_cost_per_token=50e-6,
    )
    obj.cost = cost
    return obj


@pytest.fixture
def mcp(monkeypatch):
    client = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = client
    monkeypatch.setattr("app.services.rag.openai_responses.httpx.Client", factory)

    def post(url, json):
        result = (
            {"tools": deepcopy(TOOLS)}
            if json["method"] == "tools/list"
            else {"content": [{"type": "text", "text": '{"EUR":12345}'}]}
        )
        reply = MagicMock()
        reply.json.return_value = {"jsonrpc": "2.0", "id": json["id"], "result": result}
        return reply

    client.post.side_effect = post
    return client


def test_invoke_wire_format_and_cache_aware_usage(wrapper):
    wrapper.client.responses.create.return_value = response()
    result = wrapper.invoke("User text", "System text")
    wire = wrapper.client.responses.create.call_args.kwargs
    assert wire == {
        "model": "gpt-6-astra",
        "input": [
            {"role": "system", "content": "System text"},
            {"role": "user", "content": "User text"},
        ],
        "reasoning": {"effort": "low"},
        "max_output_tokens": 4096,
        "store": False,
        "service_tier": "default",
        "include": ["reasoning.encrypted_content"],
    }
    assert result.content == "Actual answer"
    assert result.usage["cost_tracked"] is True
    assert result.usage["completion_tokens"] == 20  # reasoning is already included
    emitted = wrapper.cost.call_args.kwargs
    assert emitted["input_cost_per_token"] == pytest.approx(
        (60 * 10e-6 + 30 * 1e-6 + 10 * 12.5e-6) / 100
    )
    assert emitted["output_cost_per_token"] == 50e-6
    wrapper.cost.assert_called_once()


@pytest.mark.parametrize(
    "raw", [response(status="incomplete"), response([]), response(status="failed")]
)
def test_invoke_rejects_incomplete_failed_and_empty(wrapper, raw):
    wrapper.client.responses.create.return_value = raw
    with pytest.raises(RuntimeError, match="generation failed"):
        wrapper.invoke("question")
    wrapper.cost.assert_called_once()


def test_mcp_roundtrip_preserves_encrypted_reasoning_and_exact_output(wrapper, mcp):
    reasoning = {
        "type": "reasoning",
        "id": "rs1",
        "summary": [],
        "encrypted_content": "ciphertext",
    }
    tool = function()
    wrapper.client.responses.create.side_effect = [
        response([reasoning, tool]),
        response(),
    ]
    result = wrapper.invoke_with_tools("question", 3, "policy")
    assert result.success and result.iterations == 1
    assert result.tool_calls_made == [
        {
            "tool": "get_market_prices",
            "args": '{"currency":"EUR"}',
            "result": '{"EUR":12345}',
        }
    ]
    first, second = [x.kwargs for x in wrapper.client.responses.create.call_args_list]
    assert first["tools"] == [
        {
            "type": "function",
            "name": TOOLS[0]["name"],
            "description": TOOLS[0]["description"],
            "parameters": TOOLS[0]["inputSchema"],
            "strict": False,
        }
    ]
    assert "server_url" not in str(first)
    assert second["input"][-3:] == [
        reasoning,
        tool,
        {"type": "function_call_output", "call_id": "call1", "output": '{"EUR":12345}'},
    ]
    assert mcp.post.call_args_list[1].kwargs["json"]["params"] == {
        "name": "get_market_prices",
        "arguments": {"currency": "EUR"},
    }
    assert wrapper.cost.call_count == 2


@pytest.mark.parametrize(
    "bad",
    [
        function(name="unknown"),
        function(arguments="not-json"),
        function(arguments="[]"),
        function(arguments="{}"),
        function(arguments='{"currency":9}'),
        function(call_id=""),
        function(call_id="valid"),
    ],
)
def test_whole_tool_batch_validated_before_dispatch(wrapper, mcp, bad):
    wrapper.client.responses.create.return_value = response(
        [function(call_id="valid"), bad]
    )
    result = wrapper.invoke_with_tools("question")
    assert not result.success
    assert (
        mcp.post.call_count == 1
    )  # tools/list only; even first valid call was not dispatched


def test_turn_limit_does_not_execute_unconsumable_tool(wrapper, mcp):
    wrapper.client.responses.create.return_value = response([function()])
    result = wrapper.invoke_with_tools("question", max_turns=1)
    assert not result.success and mcp.post.call_count == 1


def test_mcp_failure_is_explicit_and_does_not_invent_answer(wrapper, mcp):
    mcp.post.side_effect = RuntimeError("sensitive transport detail")
    result = wrapper.invoke_with_tools("question")
    assert not result.success and "sensitive" not in result.content
    wrapper.client.responses.create.assert_not_called()


def test_failure_diagnostics_do_not_log_provider_payloads(wrapper, caplog):
    error = RuntimeError("private request and credential material")
    error.status_code = 429
    wrapper.client.responses.create.side_effect = error
    with pytest.raises(RuntimeError):
        wrapper.invoke("private user question")
    assert "RuntimeError" in caplog.text and "http_status=429" in caplog.text
    assert "private request" not in caplog.text
    assert "private user" not in caplog.text


def test_contract_failure_has_specific_safe_diagnostic(wrapper, caplog):
    wrapper.client.responses.create.return_value = response(status="incomplete")
    with pytest.raises(RuntimeError):
        wrapper.invoke("question")
    assert "Responses generation did not complete" in caplog.text


class FakeStream:
    def __init__(self, events):
        self.events, self.closed = iter(events), False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.events)

    def close(self):
        self.closed = True


def test_native_stream_yields_real_deltas_and_tracks_completion(wrapper):
    stream = FakeStream(
        [
            {"type": "response.output_text.delta", "delta": "Actual "},
            {"type": "response.output_text.delta", "delta": "answer"},
            {"type": "response.completed", "response": response()},
        ]
    )
    wrapper.client.responses.create.return_value = stream
    chunks = wrapper.stream("question", "system")
    assert next(chunks) == "Actual "
    wrapper.cost.assert_not_called()  # first delta did not wait for the full response
    assert list(chunks) == ["answer"]
    assert (
        stream.closed
        and wrapper.client.responses.create.call_args.kwargs["stream"] is True
    )
    wrapper.cost.assert_called_once()


@pytest.mark.parametrize(
    "terminal", [None, "response.failed", "response.incomplete", "error"]
)
def test_stream_failure_or_premature_eof_closes_and_never_retries(wrapper, terminal):
    events = [{"type": "response.output_text.delta", "delta": "Partial"}]
    if terminal:
        events.append({"type": terminal, "response": response(status="failed")})
    stream = FakeStream(events)
    wrapper.client.responses.create.return_value = stream
    with pytest.raises(RuntimeError, match="streaming generation failed"):
        list(wrapper.stream("question"))
    assert stream.closed
    wrapper.client.responses.create.assert_called_once()


def test_stream_refusal_delta_and_consumer_close(wrapper):
    raw = response(
        [
            {
                "type": "message",
                "content": [{"type": "refusal", "refusal": "Cannot assist"}],
            }
        ]
    )
    stream = FakeStream(
        [
            {"type": "response.refusal.delta", "delta": "Cannot assist"},
            {"type": "response.completed", "response": raw},
        ]
    )
    wrapper.client.responses.create.return_value = stream
    assert list(wrapper.stream("question")) == ["Cannot assist"]
    assert stream.closed
    stream2 = FakeStream([{"type": "response.output_text.delta", "delta": "Partial"}])
    wrapper.client.responses.create.return_value = stream2
    generator = wrapper.stream("question")
    assert next(generator) == "Partial"
    generator.close()
    assert stream2.closed


def test_actual_tool_failure_stops_before_another_provider_turn(wrapper, mcp):
    original = mcp.post.side_effect

    def fail_tool(url, json):
        reply = original(url, json)
        if json["method"] == "tools/call":
            reply.json.return_value = {
                "id": json["id"],
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "private detail"}],
                },
            }
        return reply

    mcp.post.side_effect = fail_tool
    wrapper.client.responses.create.return_value = response([function()])
    result = wrapper.invoke_with_tools("question")
    assert not result.success and "private detail" not in result.content
    wrapper.client.responses.create.assert_called_once()


def test_five_turns_are_bounded_and_final_request_is_not_dispatched(wrapper, mcp):
    wrapper.client.responses.create.side_effect = [
        response([function(call_id=f"call{i}")]) for i in range(5)
    ]
    result = wrapper.invoke_with_tools("question", max_turns=5)
    assert not result.success
    assert wrapper.client.responses.create.call_count == 5
    assert len(result.tool_calls_made) == 4
    assert mcp.post.call_count == 5  # catalogue plus four executions
    assert wrapper.cost.call_count == 5
