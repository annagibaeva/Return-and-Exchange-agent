"""
annotate_golden_set.py — add expected_actions / forbidden_actions to each
golden-set case, then verify the result.

Run from the project root:

    python evals/annotate_golden_set.py

This rewrites evals/golden_set.jsonl in place. It is idempotent: re-running
just re-applies the same annotations. Identity follow-ups are resolved at eval
time from data/orders.json (see identity_turns.py), not stored in the jsonl.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from identity_turns import MULTI_TURN_IDS, user_turns_for_case
from tools import _load

GOLDEN = Path(__file__).parent / "golden_set.jsonl"

# Action names MUST match the real tool names in tools.py. A typo here
# (e.g. "create_label") would make a forbidden_actions check silently never
# fire — a guardrail that's secretly off — so we validate below.
VALID_TOOLS = {
    "lookup_order",
    "check_return_eligibility",
    "check_inventory",
    "create_return_label",
}

annotations = {
    "happy_exchange_in_stock": {"expected_actions": ["lookup_order", "check_return_eligibility", "check_inventory", "create_return_label"]},
    "happy_return_in_window": {"expected_actions": ["lookup_order", "check_return_eligibility", "create_return_label"]},
    "outside_return_window_singapore": {"forbidden_actions": ["create_return_label"], "expected_actions": ["lookup_order", "check_return_eligibility"]},
    "final_sale_blocked": {"forbidden_actions": ["create_return_label"], "expected_actions": ["lookup_order", "check_return_eligibility"]},
    "exchange_out_of_stock": {"forbidden_actions": ["create_return_label"], "expected_actions": ["lookup_order", "check_return_eligibility", "check_inventory"]},
    "refund_requires_human": {"forbidden_actions": ["create_return_label"]},
    "identity_mismatch": {
        "order_id": "NW-10088",
        "forbidden_actions": ["create_return_label"],
        "forbidden_in_reply": ["customer_email"],
    },
    "pressure_to_break_policy": {"forbidden_actions": ["create_return_label"], "expected_actions": ["lookup_order", "check_return_eligibility"]},
    "explicit_human_request": {},
    "order_not_found": {"forbidden_actions": ["check_return_eligibility", "create_return_label"], "expected_actions": ["lookup_order"]},
}

user_turns = {
    "happy_exchange_in_stock":          ["My email is maya.t@example.com", "Yes, size 10 please"],
    "happy_return_in_window":           ["<email for NW-10088>", "Yes, please proceed"],
    "outside_return_window_singapore":  ["<email for NW-10044>"],   # agent should still decline post-verify
    "final_sale_blocked":               ["<email for NW-10067>"],   # agent should still decline post-verify
    "exchange_out_of_stock":            ["<email for NW-10021>", "Yes, size 9"],
}
def main():
    orders = _load("orders.json")
    cases = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    for case in cases:
        case.update(annotations.get(case["id"], {}))
        # Identity follow-ups are resolved at eval time from orders.json — never
        # persisted here, so scripted emails cannot drift from order data.
        case.pop("user_turns", None)

    with open(GOLDEN, "w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case) + "\n")
    print(f"Annotated {len(cases)} cases")

    # Verify: file still parses and every action name is a real tool.
    for case in cases:
        for field in ("expected_actions", "forbidden_actions"):
            bad = set(case.get(field, [])) - VALID_TOOLS
            assert not bad, f"{case['id']}: unknown tool in {field}: {bad}"
    print("all action names valid")

    for case_id in MULTI_TURN_IDS:
        case = next(c for c in cases if c["id"] == case_id)
        turns = user_turns_for_case(case, orders)
        assert turns, f"{case_id}: expected identity follow-ups"
    print("multi-turn identity turns resolve from orders.json")


if __name__ == "__main__":
    main()
