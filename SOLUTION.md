# CityWheels Help Desk Agent - Solution

This is a command-line agent for the CityWheels bike rental. It answers customer questions about prices, rules,
bookings and refunds. The model decides which tool to call, my code runs the tool and sends the result back
to the model. Refund amounts are always calculated by my code, not by the model.

## 1. How to install and run

You need Python 3.10 or newer.

```bash
git clone https://github.com/cocojambo2316/citywheels-help-desk.git
cd citywheels-help-desk
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then put your Gemini API key in .env
```

You can get a free key at <https://aistudio.google.com> ("Get API key").

```bash
python main.py "I want to cancel booking CW-1002. How much will I get back?"   # one question
python main.py                                                                 # chat mode with follow-up questions
pytest                                                                         # all tests, no key or internet needed
python eval/run_eval.py                                                        # evaluation, needs the key
```

## 2. Model and provider

I use **Gemini** with the official `google-genai` library, on the free tier.

- The key is free and easy to get, and Gemini supports function calling.
- The model name is in `.env` (`GEMINI_MODEL`), so I can change the model without changing the code.
- The final evaluation ran on **`gemini-3.5-flash-lite`**. First I used `gemini-3.6-flash`, but on the free tier
  it allows only 5 requests per minute and 20 per day. One evaluation run needs 40-50 requests
  (2-3 per question), so it does not fit into one day. Flash-Lite allows 500 requests per day.
- I call `generate_content` with **automatic function calling turned off**. This way the tool-calling loop is my
  own code, and I can test it with a fake model.

## 3. How the agent works

```
main.py  ->  agent.run_agent()  ->  llm.GeminiLLM.generate()  ->  Gemini API
                    |
                    +-> tools.py: search_policies / get_booking / calculate_refund
```

**The loop (`run_agent` in `agent.py`):**

1. The customer question is added to the conversation.
2. The conversation, the system prompt and the tool descriptions go to the model.
3. If the model asks for tools, my code runs them, adds the results to the conversation and goes back to step 2.
4. If the model answers with text, this is the final answer.
5. The model can be called at most 6 times per question (`MAX_STEPS`), so the agent can never loop forever.

If a tool call goes wrong (unknown tool, wrong arguments), the model gets `{"error": ...}` back.
The program does not crash.

**Tools (`tools.py`):**

| Tool | What it does |
|---|---|
| `search_policies(query)` | Cuts the three Markdown files into sections by the `## ` headings. Each section gets points for every word from the query it contains, words in the heading count twice. Returns the 3 best sections. |
| `get_booking(booking_id)` | Finds the booking in `bookings.json`. Works with messy ids like `cw 1002`, `cw_1002` or `CW1002`. Returns `found: false` if the booking does not exist. |
| `calculate_refund(booking_id, cancel_at=None)` | Follows the cancellation rules. First it checks the status. Then it gives back 100%, 50% or 0% of the rental price, depending on how many hours are left before the start (exactly 48 h gives 100%, exactly 24 h gives 50%). The deposit always comes back, the booking fee never. If the customer paid with a voucher, they get a new voucher. With `cancel_at` it can answer "what if I cancel tomorrow?". |

**System prompt:** it gives the model the fixed current date from the README (2026-06-10 09:00, Warsaw time).
It tells the model to answer only from the tool results, to always use `calculate_refund` for money, and to send
the customer to the staff when the documents have no answer.

**The LLM wrapper (`llm.py`):** the agent only talks to one small method (`generate`). Thanks to this, the tests
can use a fake model instead of Gemini.

## 4. Tests

`pytest` runs 28 tests in less than a second, without internet and without a key.

- `tests/test_tool.py` - every refund rule on its own (100%, 50%, 0%, both boundaries, booking fee, voucher,
  statuses that cannot be cancelled, cancelling at another time, cancelling after the start), unknown booking,
  messy booking ids, policy search.
- `tests/test_agent.py` - the loop with a fake model: answer without tools, the tool result goes back to the model,
  two tools in one step, unknown booking, wrong tool arguments, the step limit, follow-up questions.

## 5. Evaluation

`eval/questions.json` has 17 questions. For each one I wrote what should happen: which tools must be called,
what the answer must or must not contain, and if the agent must refuse and send the customer to the staff.

The questions cover 7 refund cases (both the 48 h and 24 h boundaries, voucher, "cancel tomorrow"), a booking
that is already cancelled, an unknown booking, opening hours, age limits, prices, a storm warning (staff decides),
and 4 questions the agent should not answer (pizza, small talk, general knowledge, car parking which is not in the
documents). I wrote them in 5 languages (English, Polish, Russian, Belarusian, Finnish) and used messy booking ids.

**Latest result: 17/17** (`eval/results.md`, `gemini-3.5-flash-lite`).

How I got there:

| Run | Result | What I found | What I changed |
|---|---|---|---|
| 1 | 15/17 | #8 unknown booking: the agent said "not found, please check the number" but gave no staff contact. It did exactly what my prompt said, so the problem was in my prompt. #9 failed because of the rate limit. | Rule 5 in the prompt now also gives the staff contact. The eval script now waits and tries again after a 429 or 503 error. |
| 2 | 16/17 | #7 (already cancelled booking) failed, but the answer was correct ("already has the status **cancelled**"). My check was too strict. When I read all the answers myself, I found that #12 (pizza) passed, but the model copied the text of my prompt ("I cannot answer it and tell the customer to contact the staff"). | The check for #7 now accepts more phrases, ignores markdown, and also checks that no refund amount is promised. Rule 6 now asks the model to answer in its own words. |
| 3 | 17/17 | - | - |

What I learned from this:

- My automatic checks are simple text checks. They found real problems, but they also missed one (#12) and gave
  one false alarm (#7). That is why I read all the answers in `results.md` after every run.
- The answers change a little between runs, even with `temperature=0`. #7 passed in run 1 and failed in run 2
  with the same check. One run does not prove much. Running every question several times would give a better number.

## Extras

- **Conversation memory - done.** In chat mode (`python main.py` without a question) the agent keeps the
  conversation, so follow-up questions like "and what if I cancel tomorrow instead?" work. The model passes the
  new time as `cancel_at` to `calculate_refund`. There is a test for it:
  `test_follow_up_question_sees_previous_conversation`.
- **Two models - partly.** `gemini-3.6-flash` passed all 5 questions it got to before the daily limit stopped it.
  The full run is on `gemini-3.5-flash-lite` (17/17). So this is not a full comparison.
- **GitHub Actions - not done.**

## 6. Limitations

- **Keyword search.** It does not know synonyms. If a customer uses other words than the documents, the right
  section can be missed. It works here because the documents are short and the model searches with English
  keywords, even when the question is in another language.
- **Free tier.** Gemini sometimes returns 503 (too busy) and has strict limits per minute and per day.
  In `main.py` such an error is shown as a Python traceback.
- **No login.** Anyone who knows a booking number can see the booking and the refund.
- **Fixed date.** "Now" comes from the README. In a real system it would be the real time.
- **My own decision:** a booking that has already started, but still has the status `confirmed` in the data,
  cannot be cancelled. The rules do not say what to do in this case.
- **The agent does not cancel bookings.** It only explains the refund and sends the customer to the staff.

## 7. What I would do next

- Smarter search (embeddings together with keywords) if there were many more documents.
- A friendly message instead of a traceback when the API is down.
- Run every eval question several times and show the pass rate. Add an LLM-as-judge check for tone and for
  made-up facts, which simple text checks cannot see.
- GitHub Actions to run `pytest` on every push.
- A full comparison of two models on the same questions.

## 8. How I used AI assistants

I used Claude as a pair programmer. It wrote most of the first version of the code and the tests and explained
them to me. I ran everything, checked it, wrote the evaluation questions and made the decisions: which model to use,
which edge cases to test, and how to fix the problems the evaluation found. Before this task I had never built
an agent with tool calling, so I also used it to learn how this works.

Examples where the AI was wrong or I had to change its output:

1. **Role `"tool"` (found in a live run).** The AI sent the tool results with the role `"tool"`. It took this
   from an example in the `google-genai` README. All unit tests passed, because the fake model does not check
   roles. But the first real run failed with `400 Role 'tool' is not supported`. I gave the error to the
   assistant, and the fix was to use the role `"user"`. So tests with a fake model do not replace a real run.
2. **Booking id normalization (found by my eval questions).** I wrote eval questions with messy ids like
   `cw_1002`. This showed that the code only removed spaces and dashes (`cw_1002` became `CW-_1002`, and the
   booking was not found). Now the code keeps only letters and digits from the id, and there is a test for it.
3. **Eval checks.** My first checks were too strict for one correct answer (#7) and too weak for another (#12).
   See section 5.