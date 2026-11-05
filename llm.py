"""The LLM wrapper.

The agent loop talks only to the small interface below (`generate`), never to Gemini directly.
That is what lets the tests replace Gemini with a fake model: same method, scripted answers.

Messages use our own simple format (plain dicts), not Gemini's types:
    {"role": "user", "text": "..."}
    {"role": "assistant", "text": "...", "tool_calls": [ToolCall, ...], "raw": <provider message>}
    {"role": "tool", "name": "get_booking", "result": {...}}
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class LLMResponse:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None  # the provider's original message, sent back unchanged in the next request


class LLM(Protocol):
    def generate(self, system_prompt: str, messages: list[dict], tools: list[dict]) -> LLMResponse: ...


class GeminiLLM:
    """Gemini through the official `google-genai` SDK, with automatic function calling OFF:
    the SDK only returns the model's tool requests, our loop in agent.py runs the tools."""

    def __init__(self, api_key: str, model: str):
        from google import genai  # imported here, so tests never need the SDK or a key
        from google.genai import types

        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=60_000,  # ms: fail after 60 s instead of hanging
                retry_options=types.HttpRetryOptions(attempts=2),  # 1 retry, not 5
            ),
        )
        self.model = model

    def generate(self, system_prompt: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters_json_schema=t["parameters"],
                )
                for t in tools
            ])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0,  # as repeatable as possible, important for the evaluation
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=self._to_gemini(messages),
            config=config,
        )

        calls = [ToolCall(name=c.name, args=dict(c.args or {})) for c in (response.function_calls or [])]
        raw = response.candidates[0].content if response.candidates else None
        text = None if calls else response.text
        return LLMResponse(text=text, tool_calls=calls, raw=raw)

    @staticmethod
    def _to_gemini(messages: list[dict]) -> list:
        """Our message format -> Gemini `Content` objects.
        Tool results that follow one model turn are grouped into one 'user' message."""
        from google.genai import types

        contents = []
        for message in messages:
            if message["role"] == "user":
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message["text"])]))
            elif message["role"] == "assistant":
                if message.get("raw") is not None:
                    # Keep Gemini's own message: newer models attach "thought signatures"
                    # to tool calls and reject a history where they are missing.
                    contents.append(message["raw"])
                else:
                    parts = [types.Part.from_function_call(name=c.name, args=c.args) for c in message.get("tool_calls", [])]
                    if message.get("text"):
                        parts.insert(0, types.Part.from_text(text=message["text"]))
                    contents.append(types.Content(role="model", parts=parts))
            elif message["role"] == "tool":
                # Gemini expects tool results in a message with role "user" (it rejects role "tool").
                part = types.Part.from_function_response(name=message["name"], response=message["result"])
                previous = contents[-1] if contents else None
                if previous is not None and previous.role == "user" and all(p.function_response for p in previous.parts):
                    previous.parts.append(part)  # several tool results from one model turn -> one message
                else:
                    contents.append(types.Content(role="user", parts=[part]))
        return contents