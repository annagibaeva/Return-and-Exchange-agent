"""
chat.py — interactive REPL for the returns-and-exchange agent.

Talk to the agent one turn at a time. Each draft the agent produces is passed
through the supervisor (supervised_reply) before it's shown, so what you see is
what a customer would actually receive — including the supervisor's PASS /
REVISE / ESCALATE handling.

Type 'quit' or 'exit' (or press Ctrl-C) to stop.
"""

import os

import anthropic
from dotenv import load_dotenv

from agent import run_agent
from supervisor import supervised_reply

load_dotenv()


def main():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    conversation = []  # list of {role, content} with plain-string content

    print("Returns & exchange agent — type 'quit' to exit.\n")

    while True:
        try:
            user_input = input("YOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit"}:
            print("Goodbye!")
            break

        conversation.append({"role": "user", "content": user_input})

        # Agent drafts a reply (looking up orders / checking policy via tools),
        # then the supervisor audits it before it reaches the customer.
        draft, trace = run_agent(conversation, client=client)
        reply, verdict = supervised_reply(conversation, draft, trace, client=client)

        print(f"\nAGENT: {reply}")
        if verdict["verdict"] != "PASS":
            print(f"  [supervisor: {verdict['verdict']} — {verdict.get('reason', '')}]")
        print()

        # Record what the customer actually saw (the supervised reply, not the
        # raw draft) so the conversation history stays faithful.
        conversation.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
