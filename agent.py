"""The CityWheels help desk agent: system prompt, tool descriptions and the tool-calling loop."""

from dataclasses import dataclass, field

from llm import LLM, ToolCall
from tools import calculate_refund, get_booking, search_policies

MAX_STEPS = 6  # max model calls per question, so a confused model can never loop forever

STAFF_CONTACT = "help@citywheels.example or +48 000 000 000"

SYSTEM_PROMPT = f"""You are the help desk assistant of CityWheels, a small bike rental shop.

The current date and time is Wednesday 2026-06-10 09:00, Europe/Warsaw time (UTC+02:00).
Use it for anything about "today", "tomorrow", opening hours or the season.

Rules:
1. Answer ONLY from the results of your tools. Never use general knowledge, even if you know the answer.
2. For questions about prices, opening hours, age limits, payment, rules or what to do when
   something goes wrong, call search_policies first.
3. For questions about a specific booking, call get_booking. Never guess or invent booking details.
4. For any refund or cancellation amount, call calculate_refund and quote its amounts exactly.
   Never calculate or change amounts yourself. If the customer asks about another moment
   ("what if I cancel tomorrow at 10?"), pass that moment as cancel_at in ISO format.
5. If a booking is not found, tell the customer and ask them to check the booking number.
6. If the tools do not answer the question, or it has nothing to do with CityWheels,
   say that you cannot answer it and tell the customer to contact the staff: {STAFF_CONTACT}.
7. You cannot cancel or change bookings yourself. To actually cancel, the customer contacts the staff.
8. Reply in the customer's language. Be short, friendly and concrete.
"""

TOOLS = [
    {
        "name": "search_policies",
        "description": (
            "Search the CityWheels policy documents (prices, cancellations and refunds, FAQ: opening hours, "
            "age limits, payment, helmets, accidents, theft). Returns the most relevant sections."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords in English, e.g. 'opening hours Saturday' or 'e-bike price day'.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_booking",
        "description": "Get the details of one booking by its number. Returns found=false if it does not exist.",
        "parameters": {
            "type": "object",
            "properties": {
                "booking_id": {"type": "string", "description": "Booking number, e.g. 'CW-1002'."},
            },
            "required": ["booking_id"],
        },
    },
    {
        "name": "calculate_refund",
        "description": (
            "Calculate how much the customer gets back if the booking is cancelled, following the "
            "cancellation rules. Uses the current time unless cancel_at is given."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "booking_id": {"type": "string", "description": "Booking number, e.g. 'CW-1002'."},
                "cancel_at": {
                    "type": "string",
                    "description": "Optional moment of cancellation in ISO format, e.g. '2026-06-11T10:00'.",
                },
            },
            "required": ["booking_id"],
        },
    },
]

TOOL_FUNCTIONS = {
    "search_policies": search_policies,
    "get_booking": get_booking,
    "calculate_refund": calculate_refund,
}


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)  # every tool the model called, for the evaluation


def run_tool(call: ToolCall) -> dict:
    """Run one tool the model asked for. Errors become a result the model can read, never a crash."""
    function = TOOL_FUNCTIONS.get(call.name)
    if function is None:
        return {"error": f"Unknown tool: {call.name}"}
    try:
        return function(**call.args)
    except Exception as error:  # wrong arguments, unreadable file, ...
        return {"error": f"{type(error).__name__}: {error}"}


def run_agent(question: str, llm: LLM, messages: list[dict] | None = None) -> AgentResult:
    """Answer one customer question.

    The loop: send the conversation to the model -> if it asks for tools, run them and add the
    results to the conversation -> ask again -> ... until the model answers with text.

    `messages` is the conversation so far (for follow-up questions); it is updated in place.
    """
    if messages is None:
        messages = []
    messages.append({"role": "user", "text": question})
    calls_made: list[ToolCall] = []

    for _ in range(MAX_STEPS):
        response = llm.generate(SYSTEM_PROMPT, messages, TOOLS)

        if not response.tool_calls:  # no tool requests -> this is the final answer
            answer = response.text or f"Sorry, I could not answer that. Please contact the staff: {STAFF_CONTACT}."
            messages.append({"role": "assistant", "text": answer, "raw": response.raw})
            return AgentResult(answer=answer, tool_calls=calls_made)

        messages.append({"role": "assistant", "text": response.text, "tool_calls": response.tool_calls, "raw": response.raw})
        for call in response.tool_calls:
            calls_made.append(call)
            messages.append({"role": "tool", "name": call.name, "result": run_tool(call)})

    answer = f"Sorry, I could not find an answer. Please contact the staff: {STAFF_CONTACT}."
    messages.append({"role": "assistant", "text": answer})
    return AgentResult(answer=answer, tool_calls=calls_made)