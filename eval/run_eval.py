"""Run the agent on every question in eval/questions.json and check the answers automatically.

    python eval/run_eval.py

Writes the results to eval/results.md. Needs GEMINI_API_KEY (real model, real answers).
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so `agent`, `tools`, `main` can be imported when run from anywhere

from agent import STAFF_CONTACT, run_agent  # noqa: E402
from main import make_llm  # noqa: E402

QUESTIONS_FILE = ROOT / "eval" / "questions.json"
RESULTS_FILE = ROOT / "eval" / "results.md"
PAUSE_SECONDS = 20  # free tier allows ~5 requests per minute; one question uses 2-3 requests
RETRY_WAIT_SECONDS = 60  # after a 429 (rate limit) or 503 (overloaded), wait and try again
MAX_ATTEMPTS = 3
REFUSAL_MARKERS = ["staff", "help@citywheels", "+48 000 000 000"]


def check(case: dict, answer: str, tools_called: list[str]) -> list[str]:
    """Return the list of failed checks (empty list = the case passed)."""
    failures = []
    text = answer.lower().replace("*", "")  # ignore markdown bold, e.g. "**cancelled**"

    for tool in case.get("expected_tools", []):
        if tool not in tools_called:
            failures.append(f"tool `{tool}` was not called")

    for needed in case.get("must_contain", []):
        if needed.lower() not in text:
            failures.append(f"answer does not contain `{needed}`")

    options = case.get("must_contain_any", [])
    if options and not any(option.lower() in text for option in options):
        failures.append(f"answer contains none of {options}")

    for forbidden in case.get("must_not_contain", []):
        if forbidden.lower() in text:
            failures.append(f"answer contains forbidden `{forbidden}`")

    if case.get("must_refuse") and not any(marker.lower() in text for marker in REFUSAL_MARKERS):
        failures.append("expected a refusal that points to the staff")

    return failures


def ask_with_retries(question: str, llm):
    """Rate limits (429) and overload (503) are temporary: wait and ask again."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return run_agent(question, llm)
        except Exception as error:
            message = str(error)
            daily_quota = "per day" in message  # waiting a minute will not help, it resets once a day
            temporary = any(code in message for code in ("429", "503")) and not daily_quota
            if not temporary or attempt == MAX_ATTEMPTS:
                raise
            print(f"   API busy ({str(error)[:3]}), waiting {RETRY_WAIT_SECONDS} s ...", flush=True)
            time.sleep(RETRY_WAIT_SECONDS)


def main() -> None:
    cases = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    llm = make_llm()
    rows = []

    for i, case in enumerate(cases, start=1):
        print(f"[{i}/{len(cases)}] {case['id']} ...", flush=True)
        try:
            result = ask_with_retries(case["question"], llm)
            tools_called = [call.name for call in result.tool_calls]
            failures = check(case, result.answer, tools_called)
            answer = result.answer
        except Exception as error:  # still failing after retries -> counted as a failure, the run goes on
            tools_called, answer = [], ""
            failures = [f"error: {type(error).__name__}: {str(error)[:120]}"]
        rows.append({"case": case, "answer": answer, "tools": tools_called, "failures": failures})
        print("   PASS" if not failures else f"   FAIL: {'; '.join(failures)}")
        time.sleep(PAUSE_SECONDS)

    passed = sum(1 for row in rows if not row["failures"])
    write_report(rows, passed, llm.model)
    print(f"\n{passed}/{len(rows)} passed. Report: {RESULTS_FILE}")


def write_report(rows: list[dict], passed: int, model: str) -> None:
    lines = [
        "# Evaluation results",
        "",
        f"- Date: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Model: `{model}`",
        f"- **Passed: {passed}/{len(rows)}**",
        "",
        "| # | Case | Result | Tools called | Problems |",
        "|---|---|---|---|---|",
    ]
    for i, row in enumerate(rows, start=1):
        status = "PASS" if not row["failures"] else "FAIL"
        tools = ", ".join(row["tools"]) or "-"
        problems = "; ".join(row["failures"]).replace("|", "/") or "-"
        lines.append(f"| {i} | {row['case']['id']} | {status} | {tools} | {problems} |")

    lines += ["", "## Answers", ""]
    for i, row in enumerate(rows, start=1):
        lines += [f"### {i}. {row['case']['id']}", "", f"**Q:** {row['case']['question']}", "",
                  "**A:** " + (row["answer"].replace("\n", "\n> ") or "_(no answer)_"), ""]
    RESULTS_FILE.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()