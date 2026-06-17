"""Scripted follow-up turns for cases that pause to verify identity.

The agent (correctly, per policy) looks up the order and then pauses to verify
the requester before doing anything else. A single-turn eval gives it no second
turn, so correct behaviour scored 0%. These scripted follow-ups supply the
identity the agent asks for, so the conversation can reach a real outcome.

Two shapes, because the right follow-up depends on what should happen next:
  - COMPLETION cases also get an explicit go-ahead, so the agent actually
    creates the label instead of just offering it.
  - DECLINE / stop-short cases get identity ONLY. A "go ahead" would wrongly
    push the agent to act on something it must refuse (final sale, out of
    window) or cannot complete (out of stock).

Emails are always resolved from orders.json so the script can't drift from data.
"""

import re

# Pause for identity, then COMPLETE the task — need a go-ahead turn.
COMPLETION_IDS = (
    "happy_exchange_in_stock",
    "happy_return_in_window",
)

# Pause for identity, then DECLINE or stop short — identity turn only.
IDENTITY_ONLY_IDS = (
    "outside_return_window_singapore",
    "final_sale_blocked",
    "exchange_out_of_stock",
)

MULTI_TURN_IDS = COMPLETION_IDS + IDENTITY_ONLY_IDS


def order_id_for_case(case):
    oid = case.get("order_id")
    if oid:
        return oid.strip().upper()
    match = re.search(r"NW-\d+", case["message"])
    return match.group(0) if match else None


def identity_user_turns(order_id, orders, confirm):
    oid = order_id.strip().upper()
    try:
        email = orders[oid]["customer_email"]
    except KeyError as e:
        raise ValueError(f"unknown order_id {oid!r} in orders.json") from e
    turns = [f"My email is {email}"]
    if confirm:
        turns.append("Yes, that's me — please go ahead and process it.")
    return turns


def user_turns_for_case(case, orders):
    """Scripted follow-ups for cases that need identity verification."""
    if case["id"] not in MULTI_TURN_IDS:
        return []
    order_id = order_id_for_case(case)
    if not order_id:
        raise ValueError(f"{case['id']}: multi-turn case needs order_id or NW-#### in message")
    return identity_user_turns(order_id, orders, confirm=case["id"] in COMPLETION_IDS)
