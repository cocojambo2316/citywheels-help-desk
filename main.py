"""Command line for the CityWheels help desk agent.

    python main.py "What time do you open on Saturday?"   # one question
    python main.py                                         # chat mode, with follow-up questions
"""

import os
import sys

from dotenv import load_dotenv

from agent import run_agent
from llm import GeminiLLM

DEFAULT_MODEL = "gemini-flash-latest"


def make_llm() -> GeminiLLM:
    load_dotenv()  # reads .env into environment variables
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
    return GeminiLLM(api_key=api_key, model=os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL)


def main() -> None:
    llm = make_llm()

    if len(sys.argv) > 1:
        print(run_agent(" ".join(sys.argv[1:]), llm).answer)
        return

    print("CityWheels help desk. Ask a question (empty line to quit).")
    messages: list[dict] = []  # kept between questions, so follow-ups work
    while True:
        question = input("\nYou: ").strip()
        if not question:
            break
        print("Agent:", run_agent(question, llm, messages).answer)


if __name__ == "__main__":
    main()