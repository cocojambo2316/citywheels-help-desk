"""Tests of the agent loop with a fake model: no network, no API key."""

from agent import MAX_STEPS, run_agent
from llm import LLMResponse, ToolCall


class FakeLLM:
    """Pretends to be Gemini: returns prepared responses in order and remembers what it was sent."""

    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.received: list[list[dict]] = []

    def generate(self, system_prompt, messages, tools):
        self.received.append(list(messages))  # a copy of the conversation at this call
        return self.responses.pop(0)


def test_answer_without_tools():
    llm = FakeLLM([LLMResponse(text="Hello!")])
    result = run_agent("Hi", llm)
    assert result.answer == "Hello!"
    assert result.tool_calls == []


def test_loop_runs_tool_and_gives_result_back_to_model():
    llm = FakeLLM([
        LLMResponse(tool_calls=[ToolCall("calculate_refund", {"booking_id": "CW-1002"})]),
        LLMResponse(text="You will get 340 EUR back."),
    ])
    result = run_agent("How much do I get back for CW-1002?", llm)

    assert result.answer == "You will get 340 EUR back."
    assert [c.name for c in result.tool_calls] == ["calculate_refund"]
    # the second model call must contain the REAL result of our tool, computed by our code
    tool_message = llm.received[1][-1]
    assert tool_message["role"] == "tool"
    assert tool_message["result"]["total_refund_eur"] == 340.0


def test_unknown_booking_does_not_crash():
    llm = FakeLLM([
        LLMResponse(tool_calls=[ToolCall("get_booking", {"booking_id": "CW-9999"})]),
        LLMResponse(text="Booking CW-9999 was not found."),
    ])
    result = run_agent("Show booking CW-9999", llm)
    assert "not found" in result.answer
    assert llm.received[1][-1]["result"]["found"] is False


def test_two_tools_in_one_step():
    llm = FakeLLM([
        LLMResponse(tool_calls=[
            ToolCall("search_policies", {"query": "e-bike price day"}),
            ToolCall("search_policies", {"query": "opening hours Saturday"}),
        ]),
        LLMResponse(text="40 EUR per day, we open at 08:00."),
    ])
    result = run_agent("E-bike price for a day and Saturday hours?", llm)
    assert len(result.tool_calls) == 2
    assert [m["role"] for m in llm.received[1][-2:]] == ["tool", "tool"]


def test_bad_tool_arguments_become_an_error_result():
    llm = FakeLLM([
        LLMResponse(tool_calls=[ToolCall("get_booking", {"wrong_argument": "x"})]),
        LLMResponse(text="Sorry, something went wrong."),
    ])
    run_agent("?", llm)
    assert "error" in llm.received[1][-1]["result"]


def test_loop_stops_after_max_steps():
    endless = [LLMResponse(tool_calls=[ToolCall("get_booking", {"booking_id": "CW-1001"})])] * MAX_STEPS
    result = run_agent("?", FakeLLM(endless))
    assert "contact the staff" in result.answer


def test_follow_up_question_sees_previous_conversation():
    llm = FakeLLM([LLMResponse(text="340 EUR."), LLMResponse(text="300 EUR.")])
    messages: list[dict] = []
    run_agent("How much for CW-1002?", llm, messages)
    run_agent("And if I cancel tomorrow?", llm, messages)
    texts = [m.get("text") for m in llm.received[1]]
    assert "How much for CW-1002?" in texts
    assert "340 EUR." in texts