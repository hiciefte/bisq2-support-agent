"""Responses support-answer adapter with local MCP execution and native streaming."""

import json
import logging
from collections.abc import Iterator
from copy import deepcopy
from typing import Any

import httpx
from app.utils.instrumentation import track_tokens_and_cost
from jsonschema import validate

logger = logging.getLogger(__name__)


class _ResponseContractError(RuntimeError):
    """Controlled diagnostic text that never contains provider or tool payloads."""


def _log_failure(operation: str, error: Exception) -> None:
    reason = (
        str(error)
        if isinstance(error, _ResponseContractError)
        else type(error).__name__
    )
    status = getattr(error, "status_code", None)
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
    if type(status) is not int:
        status = None
    # Provider/validation exception bodies can contain request or tool content.
    logger.warning(
        "Responses %s failed: %s (http_status=%s)", operation, reason, status
    )


class OpenAIResponsesLLMWrapper:
    """Keep provider generation separate from the application's local MCP bridge.

    Usage is emitted here once per provider response. Returned usage includes
    ``cost_tracked=True`` so RAG callers must not account for it a second time.
    """

    def __init__(
        self,
        client: Any,
        model: str,
        max_tokens: int,
        reasoning_effort: str,
        mcp_url: str,
        mcp_timeout_seconds: float = 30,
        *,
        input_cost_per_token: float,
        cached_input_cost_per_token: float,
        cache_write_cost_per_token: float,
        output_cost_per_token: float,
    ):
        self.client = client
        self.model_id = model
        self.model = model.removeprefix("openai:")
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort or "low"
        self.mcp_url = mcp_url
        self.mcp_timeout_seconds = mcp_timeout_seconds
        self.input_rate = input_cost_per_token
        self.cached_rate = cached_input_cost_per_token
        self.write_rate = cache_write_cost_per_token
        self.output_rate = output_cost_per_token

    @staticmethod
    def _plain(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", exclude_none=True)
        return value

    def _request(self, items: list[dict], **kwargs: Any) -> dict:
        return {
            "model": self.model,
            "input": deepcopy(items),
            "reasoning": {"effort": self.reasoning_effort},
            "max_output_tokens": self.max_tokens,
            "store": False,
            "service_tier": "default",
            "include": ["reasoning.encrypted_content"],
            **kwargs,
        }

    @staticmethod
    def _messages(prompt: str, system_content: str | None) -> list[dict]:
        messages = []
        if system_content is not None:
            messages.append({"role": "system", "content": system_content})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _usage(self, response: dict) -> dict:
        usage = response.get("usage")
        if not isinstance(usage, dict):
            raise _ResponseContractError("Responses usage missing")
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        details = usage.get("input_tokens_details") or {}
        cached = details.get("cached_tokens", 0)
        written = details.get(
            "cache_write_tokens", details.get("cache_creation_tokens", 0)
        )
        values = (input_tokens, output_tokens, cached, written)
        if any(type(value) is not int or value < 0 for value in values):
            raise _ResponseContractError("Invalid Responses usage")
        if cached + written > input_tokens:
            raise _ResponseContractError("Invalid Responses cache usage")
        cost = (
            (input_tokens - cached - written) * self.input_rate
            + cached * self.cached_rate
            + written * self.write_rate
        )
        track_tokens_and_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost_per_token=(
                cost / input_tokens if input_tokens else self.input_rate
            ),
            output_cost_per_token=self.output_rate,
        )
        return {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_tracked": True,
            "provider_usage": deepcopy(usage),
        }

    @staticmethod
    def _output(response: dict) -> list[dict]:
        if response.get("status") != "completed":
            raise _ResponseContractError("Responses generation did not complete")
        output = response.get("output")
        if not isinstance(output, list):
            raise _ResponseContractError("Responses output missing")
        return output

    @staticmethod
    def _text(output: list[dict]) -> str:
        parts = []
        for item in output:
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        parts.append(content.get("text", ""))
                    elif content.get("type") == "refusal":
                        parts.append(content.get("refusal", ""))
        text = "".join(parts)
        if not text.strip():
            raise _ResponseContractError("Responses returned no answer")
        return text

    def invoke(self, prompt: str, system_content: str | None = None):
        from app.services.rag.llm_provider import LLMResponse

        try:
            response = self._plain(
                self.client.responses.create(
                    **self._request(self._messages(prompt, system_content))
                )
            )
            usage = self._usage(response)
            output = self._output(response)
            if any(item.get("type") == "function_call" for item in output):
                raise _ResponseContractError("Unexpected tool request")
            return LLMResponse(content=self._text(output), usage=usage)
        except Exception as exc:
            _log_failure("answer", exc)
            raise RuntimeError("Responses answer generation failed") from None

    def _rpc(
        self, client: httpx.Client, method: str, params: dict, request_id: int
    ) -> dict:
        reply = client.post(
            self.mcp_url,
            json={
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
        )
        reply.raise_for_status()
        data = reply.json()
        if (
            data.get("error")
            or data.get("id") != request_id
            or not isinstance(data.get("result"), dict)
        ):
            raise _ResponseContractError("Local MCP request failed")
        return data["result"]

    def invoke_with_tools(
        self, prompt: str, max_turns: int = 3, system_content: str | None = None
    ):
        from app.services.rag.llm_provider import ToolCallResult

        calls: list[dict] = []
        iterations = 0
        try:
            if type(max_turns) is not int or not 1 <= max_turns <= 5:
                raise ValueError("Tool turn limit must be between one and five")
            items = self._messages(prompt, system_content)
            seen_ids: set[str] = set()
            with httpx.Client(timeout=self.mcp_timeout_seconds, trust_env=False) as mcp:
                definitions = self._rpc(mcp, "tools/list", {}, 1).get("tools")
                if not isinstance(definitions, list) or not definitions:
                    raise _ResponseContractError("MCP tool catalogue missing")
                by_name = {item["name"]: item for item in definitions}
                if len(by_name) != len(definitions):
                    raise _ResponseContractError("Duplicate MCP tool names")
                tools = [
                    {
                        "type": "function",
                        "name": item["name"],
                        "description": item["description"],
                        "parameters": deepcopy(item["inputSchema"]),
                        "strict": False,
                    }
                    for item in definitions
                ]
                for turn in range(max_turns):
                    response = self._plain(
                        self.client.responses.create(
                            **self._request(items, tools=tools)
                        )
                    )
                    self._usage(response)
                    output = self._output(response)
                    requested = [
                        item for item in output if item.get("type") == "function_call"
                    ]
                    if not requested:
                        return ToolCallResult(
                            content=self._text(output),
                            tool_calls_made=calls,
                            iterations=iterations,
                        )
                    if turn == max_turns - 1:
                        raise _ResponseContractError("Tool turn limit reached")
                    # Validate the entire batch before any local tool dispatch.
                    parsed_calls = []
                    for item in requested:
                        name, call_id, arguments = (
                            item.get("name"),
                            item.get("call_id"),
                            item.get("arguments"),
                        )
                        if (
                            name not in by_name
                            or not isinstance(call_id, str)
                            or not call_id
                            or call_id in seen_ids
                        ):
                            raise _ResponseContractError("Invalid MCP function request")
                        if not isinstance(arguments, str):
                            raise _ResponseContractError("Invalid MCP arguments")
                        parsed = json.loads(arguments)
                        if not isinstance(parsed, dict):
                            raise _ResponseContractError(
                                "MCP arguments must be an object"
                            )
                        validate(parsed, by_name[name]["inputSchema"])
                        seen_ids.add(call_id)
                        parsed_calls.append((name, call_id, arguments, parsed))
                    items.extend(deepcopy(output))
                    iterations += 1
                    for name, call_id, arguments, parsed in parsed_calls:
                        result = self._rpc(
                            mcp,
                            "tools/call",
                            {"name": name, "arguments": parsed},
                            len(calls) + 2,
                        )
                        if result.get("isError"):
                            raise _ResponseContractError("MCP tool reported failure")
                        content = result.get("content")
                        if (
                            not isinstance(content, list)
                            or not content
                            or any(
                                item.get("type") != "text"
                                or not isinstance(item.get("text"), str)
                                for item in content
                            )
                        ):
                            raise _ResponseContractError(
                                "MCP tool returned unsupported content"
                            )
                        text = "\n".join(item["text"] for item in content)
                        calls.append({"tool": name, "args": arguments, "result": text})
                        items.append(
                            {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": text,
                            }
                        )
        except Exception as exc:
            _log_failure("tools", exc)
            return ToolCallResult(
                content="Responses or local MCP invocation failed",
                tool_calls_made=calls,
                iterations=iterations,
                success=False,
            )
        return ToolCallResult(
            content="Responses tool loop incomplete",
            tool_calls_made=calls,
            iterations=iterations,
            success=False,
        )

    def stream(self, prompt: str, system_content: str | None = None) -> Iterator[str]:
        stream = None
        try:
            stream = self.client.responses.create(
                **self._request(self._messages(prompt, system_content), stream=True)
            )
            emitted = False
            for event in stream:
                data = self._plain(event)
                event_type = data.get("type")
                if event_type in (
                    "response.output_text.delta",
                    "response.refusal.delta",
                ):
                    delta = data.get("delta")
                    if not isinstance(delta, str):
                        raise _ResponseContractError("Invalid Responses stream delta")
                    if delta:
                        emitted = True
                        yield delta
                elif event_type in (
                    "response.completed",
                    "response.failed",
                    "response.incomplete",
                ):
                    response = data.get("response") or {}
                    self._usage(response)
                    output = self._output(response)
                    if event_type != "response.completed" or not emitted:
                        raise _ResponseContractError(
                            "Responses stream failed or was empty"
                        )
                    self._text(output)
                    return
                elif event_type == "error":
                    raise _ResponseContractError("Responses stream error")
            raise _ResponseContractError("Responses stream ended before completion")
        except Exception as exc:
            _log_failure("stream", exc)
            raise RuntimeError("Responses streaming generation failed") from None
        finally:
            if stream is not None:
                stream.close()
