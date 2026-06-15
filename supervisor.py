"""
supervisor.py — the supervision layer.

After the primary agent drafts a response, a second model call checks it
against policy before anything would reach a customer. This is the
demo-to-production move: a single agent gets the common case right; the
supervisor catches the long tail of inputs where it might leak data, approve
something outside policy, or promise an action that needs human sign-off.

Returns a verdict: PASS (send as-is), REVISE (problem found, with reason),
or ESCALATE (hand to a human).
"""

import json
import os
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
with open(Path(__file__).parent / "policy.yaml", encoding="utf-8") as _f:
    POLICY = yaml.safe_load(_f)

SUPERVISOR_PROMPT = f"""You are a supervision layer reviewing a customer-service agent's draft
reply before it is sent to a customer of Singapore Apparel. You do not talk to
the customer. You audit the draft against policy and the tool calls that were made.

Policy summary:
- Return windows: Singapore {POLICY['return_window_days']['Singapore']} days, Malaysia {POLICY['return_window_days']['Malaysia']} days.
- Final-sale items are NOT returnable.
- Refunds and goodwill credits ALWAYS require human approval — the agent must never grant them itself.
- Window or final-sale overrides require human approval.
- Order details must never be shared if the requester's identity doesn't match the order.

Check the draft for these failure modes:
1. Promising a return/exchange/refund that policy forbids (out of window, final sale).
2. Issuing or promising a refund or goodwill credit without escalation.
3. Revealing order details on an identity mismatch.
4. Claiming an action (e.g. label created) that the tool trace doesn't support.
5. Confirming an exchange when inventory was out of stock.

Respond ONLY with a JSON object, no prose, no markdown:
{{"verdict": "PASS" | "REVISE" | "ESCALATE", "reason": "<short reason, empty if PASS>"}}"""


def review(customer_messages, draft_reply, trace, client=None):
    """
    Audit a draft reply. Returns {"verdict", "reason"}.
    customer_messages: the conversation so far (list of {role, content} with string content)
    draft_reply: the agent's proposed text
    trace: list of tool calls made by the agent
    """
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    convo_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in customer_messages
        if isinstance(m.get("content"), str)
    )
    trace_text = json.dumps(trace, indent=2)

    audit_input = f"""CONVERSATION:
{convo_text}

TOOL CALLS MADE BY AGENT:
{trace_text}

AGENT'S DRAFT REPLY:
{draft_reply}

Audit this draft. Respond with the JSON verdict only."""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SUPERVISOR_PROMPT,
        messages=[{"role": "user", "content": audit_input}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        verdict = json.loads(raw)
        if verdict.get("verdict") not in {"PASS", "REVISE", "ESCALATE"}:
            return {"verdict": "ESCALATE", "reason": "unparseable supervisor verdict"}
        return verdict
    except json.JSONDecodeError:
        # Fail safe: if the supervisor itself misbehaves, escalate rather than send.
        return {"verdict": "ESCALATE", "reason": "supervisor returned non-JSON"}


def supervised_reply(customer_messages, draft_reply, trace, client=None):
    """
    Convenience wrapper: returns the message that should actually be sent,
    applying the supervisor's verdict.
    """
    v = review(customer_messages, draft_reply, trace, client)
    if v["verdict"] == "PASS":
        return draft_reply, v
    if v["verdict"] == "ESCALATE":
        return ("Thanks for your patience — I'm connecting you with a member of "
                "our team who can help with this directly."), v
    # REVISE: in this scaffold we surface a safe fallback; a fuller build would
    # loop back to the agent with the supervisor's reason for a second attempt.
    return ("I want to make sure I get this right for you — let me bring in a "
            "colleague to confirm the details before we proceed."), v
