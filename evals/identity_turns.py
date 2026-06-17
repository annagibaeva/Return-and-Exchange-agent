"""Session identity and scripted follow-ups for multi-turn eval cases.

Production auth supplies session_customer_email to run_agent (see app.py).
Multi-turn evals mirror that: session email is resolved from orders.json and
passed into every run_agent call so tool traces test return/exchange policy,
not the identity gate.

Scripted user turns remain only where the scenario still needs a second beat:
  - COMPLETION cases get an explicit go-ahead so the agent creates the label
    instead of stopping at an offer.
  - DECLINE / stop-short cases need no follow-ups — with a verified session the
    agent can reach the policy verdict on the opening turn.
"""

import re

# Verified session + explicit go-ahead to finish the task.
COMPLETION_IDS = (
    "happy_exchange_in_stock",
    "happy_return_in_window",
)

# Verified session only — policy decline / stop-short on the opening turn.
IDENTITY_ONLY_IDS = (
    "outside_return_window_singapore",
    "final_sale_blocked",
    "exchange_out_of_stock",
)

MULTI_TURN_IDS = COMPLETION_IDS + IDENTITY_ONLY_IDS

# Session email is resolved per case so each eval tests one thing in isolation:
#   - happy_path / policy_edges: verified email from the order (policy, not auth)
#   - identity_mismatch: deliberately wrong email (auth gate is under test)
#   - order_not_found / explicit_human_request: no session (lookup or escalation first)
UNVERIFIED_SESSION_IDS = ("identity_mismatch",)
SKIP_SESSION_EMAIL_IDS = ("order_not_found", "explicit_human_request")
WRONG_SESSION_EMAIL = "wrong.person@example.com"


def order_id_for_case(case):
    oid = case.get("order_id")
    if oid:
        return oid.strip().upper()
    match = re.search(r"NW-\d+", case["message"])
    return match.group(0) if match else None


def session_email_for_case(case, orders):
    """Session email for the eval harness (auth layer, not chat).

    Returns the verified order email for policy cases, a wrong email for
    identity_mismatch, or None when session identity is irrelevant.
    """
    case_id = case["id"]

    if case_id in SKIP_SESSION_EMAIL_IDS:
        return None

    if case_id in UNVERIFIED_SESSION_IDS:
        return WRONG_SESSION_EMAIL

    order_id = order_id_for_case(case)
    if not order_id:
        return None
    oid = order_id.strip().upper()
    try:
        return orders[oid]["customer_email"]
    except KeyError as e:
        raise ValueError(f"unknown order_id {oid!r} in orders.json") from e


def user_turns_for_case(case, orders):
    """Scripted follow-ups after the opening turn (completion nudge only)."""
    if case["id"] not in MULTI_TURN_IDS:
        return []
    if case["id"] in COMPLETION_IDS:
        return ["Yes, that's me — please go ahead and process it."]
    return []
