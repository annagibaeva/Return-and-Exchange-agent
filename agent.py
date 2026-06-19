"""
agent.py — the primary agent: a Claude tool-calling loop.

Flow: take the conversation, let Claude plan and call tools against the mock
systems of record, loop until it produces a final text response. That response
is then handed to the supervisor (see supervisor.py) before it would reach a
customer.

Plain Python and the Anthropic SDK — no orchestration framework.
"""

import json
import os
import re
from functools import lru_cache
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

import tools as toolbox

load_dotenv()

MODEL = "claude-sonnet-4-6"

MAX_TURNS = 8

with open(Path(__file__).parent / "policy.yaml", encoding="utf-8") as _f:
    POLICY = yaml.safe_load(_f)


@lru_cache(maxsize=1)
def _system_prompt():
    from skills import assemble_skill_prompt

    return f"""You are the customer-service agent for Singapore Apparel, an online retailer.
You help customers with returns and exchanges. You are friendly, concise, and honest.

Hard rules:
- Always look up the order before making any claim about it.
- Respect every eligibility verdict exactly. Never promise something policy forbids.
- Never reveal order details unless the customer's identity matches the order.
- Never issue instant refunds or goodwill credits to a card yourself — those require
  human approval. Creating a return label (create_return_label) when eligible is
  autonomous, including refund-resolution labels.
- When replacement stock is unavailable, say so plainly (name the size), list
  in-stock alternatives or a return option, and do not escalate — out-of-stock
  exchanges are routine.
- When unsure or when policy is exceeded, escalate to a human rather than improvise.

Region return windows and rules are enforced by the tools; trust their verdicts.

{assemble_skill_prompt()}

When you have resolved the request or decided to escalate, give the customer a
clear final message. Do not call more tools than you need."""


_EMAIL_FROM_MESSAGE = re.compile(
    r"(?i)(?:my email is|email(?:\s+address)?(?:\s+is)?)\s+(\S+@\S+)"
)


def _session_customer_email(messages, session_customer_email=None):
    """Auth-layer email, or the latest address the customer volunteered in chat."""
    if session_customer_email:
        return session_customer_email.strip()
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        match = _EMAIL_FROM_MESSAGE.search(content)
        if match:
            return match.group(1).strip()
    return None


def _run_tool(name, args, session_customer_email=None):
    """Dispatch a tool call, injecting policy and session identity where needed."""
    fn = toolbox.TOOL_FUNCTIONS[name]
    if name == "check_return_eligibility":
        return fn(
            args["order_id"],
            args["sku"],
            POLICY,
            session_customer_email=session_customer_email,
        )
    if name in {"lookup_order", "create_return_label"}:
        return fn(**args, session_customer_email=session_customer_email)
    return fn(**args)


def run_agent(messages, client=None, verbose=False, session_customer_email=None, usage_tracker=None):
    """
    Run the agent loop over a list of {role, content} messages.
    Returns (final_text, trace) where trace is the list of tool calls made.

    session_customer_email: verified address from the auth layer (login/session).
    When omitted, the agent uses any email the customer volunteered in the thread.
    """
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    convo = list(messages)
    trace = []
    verified_email = _session_customer_email(convo, session_customer_email)

    for _ in range(MAX_TURNS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=_system_prompt(),
            tools=toolbox.TOOL_SCHEMAS,
            messages=convo,
        )
        if usage_tracker is not None:
            usage_tracker.record("agent", MODEL, resp)

        if resp.stop_reason == "tool_use":
            convo.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = _run_tool(
                        block.name, block.input, session_customer_email=verified_email
                    )
                    trace.append({"tool": block.name, "input": block.input, "result": result})
                    if verbose:
                        print(f"  -> {block.name}({block.input}) = {json.dumps(result)[:120]}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
            convo.append({"role": "user", "content": tool_results})
            continue

        # Final text response
        final_text = "".join(b.text for b in resp.content if b.type == "text")
        return final_text, trace

    return "I'm having trouble completing this — let me hand you to a human agent.", trace


if __name__ == "__main__":
    # Quick manual smoke test
    msg = [{"role": "user", "content": "Hi, I'd like to return my running shoes from order NW-10021, they're too small."}]
    text, trace = run_agent(msg, verbose=True)
    print("\nAGENT:", text)
