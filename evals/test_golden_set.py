"""
test_golden_set.py — tiny guardrail test for the eval data.

Two checks, run on every edit to evals/golden_set.jsonl:

  1. The file still parses (one JSON object per line).
  2. Every action name in expected_actions / forbidden_actions is a REAL tool.

Check 2 matters most: a typo like "create_label" would make a forbidden_actions
guardrail silently never fire — a guardrail that's secretly off. We fail loud
instead, and we source the valid names from tools.py so this can't drift if a
tool is ever renamed.

    python evals/test_golden_set.py     # standalone (from project root)
    pytest evals/test_golden_set.py     # if pytest is ever added

In Cursor/VS Code: open this file and press F5 (config: "Golden set tests"),
or Terminal → Run Task → "Golden set tests". Do not run tools.py — it is imported,
not executed.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from identity_turns import (
    COMPLETION_IDS,
    MULTI_TURN_IDS,
    SKIP_SESSION_EMAIL_IDS,
    UNVERIFIED_SESSION_IDS,
    WRONG_SESSION_EMAIL,
    order_id_for_case,
    session_email_for_case,
    user_turns_for_case,
)
from tools import TOOL_FUNCTIONS, _load

GOLDEN = Path(__file__).parent / "golden_set.jsonl"
VALID_TOOLS = set(TOOL_FUNCTIONS)  # single source of truth: the real tools
ACTION_FIELDS = ("expected_actions", "forbidden_actions")
FORBIDDEN_REPLY_TOKENS = {"customer_email"}


def load_cases():
    """Check 1: every non-empty line is valid JSON. Raises on the first bad line."""
    cases = []
    for n, line in enumerate(GOLDEN.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise AssertionError(f"{GOLDEN.name} line {n} is not valid JSON: {e}") from e
    return cases


def test_file_parses():
    assert load_cases(), "golden_set.jsonl parsed to zero cases"


def test_action_names_are_real_tools():
    for case in load_cases():
        for field in ACTION_FIELDS:
            bad = set(case.get(field, [])) - VALID_TOOLS
            assert not bad, (
                f"{case['id']}: unknown tool(s) in {field}: {bad}. "
                f"Valid tools are {sorted(VALID_TOOLS)}."
            )


def test_forbidden_in_reply_tokens():
    for case in load_cases():
        tokens = case.get("forbidden_in_reply", [])
        if not tokens:
            continue
        symbolic = [t for t in tokens if t in FORBIDDEN_REPLY_TOKENS]
        if symbolic and not case.get("order_id"):
            raise AssertionError(
                f"{case['id']}: forbidden_in_reply {symbolic} requires order_id "
                f"so tokens like customer_email resolve to real values"
            )
        bad_symbolic = set(symbolic) - FORBIDDEN_REPLY_TOKENS
        assert not bad_symbolic, (
            f"{case['id']}: unknown forbidden_in_reply token(s): {bad_symbolic}. "
            f"Known tokens: {sorted(FORBIDDEN_REPLY_TOKENS)}."
        )


def test_identity_turns_resolve_from_orders():
    orders = _load("orders.json")
    by_id = {c["id"]: c for c in load_cases()}
    for case_id in MULTI_TURN_IDS:
        case = by_id[case_id]
        email = session_email_for_case(case, orders)
        order_id = order_id_for_case(case)
        assert email == orders[order_id]["customer_email"], (
            f"{case_id}: session email must match orders.json for {order_id}"
        )
        assert "user_turns" not in case, (
            f"{case_id}: user_turns must not be stored in golden_set.jsonl"
        )
        if case_id in COMPLETION_IDS:
            turns = user_turns_for_case(case, orders)
            assert turns, f"{case_id}: completion case needs confirm follow-up"


def test_session_email_per_case():
    """Harness passes the right session email so each case tests one thing."""
    orders = _load("orders.json")
    for case in load_cases():
        case_id = case["id"]
        email = session_email_for_case(case, orders)
        order_id = order_id_for_case(case)

        if case_id in SKIP_SESSION_EMAIL_IDS:
            assert email is None, f"{case_id}: session email must be omitted"
            continue

        if case_id in UNVERIFIED_SESSION_IDS:
            assert email == WRONG_SESSION_EMAIL, f"{case_id}: must use wrong session email"
            if order_id:
                assert email.lower() != orders[order_id]["customer_email"].lower(), (
                    f"{case_id}: wrong session email must not match order owner"
                )
            continue

        if order_id and order_id in orders:
            assert email == orders[order_id]["customer_email"], (
                f"{case_id}: policy case needs verified session from {order_id}"
            )


def test_tools_redact_without_verified_session():
    import yaml
    from pathlib import Path
    from tools import check_return_eligibility, create_return_label, lookup_order

    policy = yaml.safe_load(
        (Path(__file__).parent.parent / "policy.yaml").read_text(encoding="utf-8")
    )
    order_id = "NW-10021"
    email = _load("orders.json")[order_id]["customer_email"]

    redacted = lookup_order(order_id)
    assert redacted["found"] and not redacted.get("identity_verified")
    assert "customer_email" not in redacted and "items" not in redacted

    full = lookup_order(order_id, session_customer_email=email)
    assert full.get("identity_verified") and "items" in full

    blocked = check_return_eligibility(order_id, "SHOE-RUN-9", policy)
    assert blocked["reason"] == "identity_not_verified"

    label = create_return_label(order_id, "SHOE-RUN-9", "exchange")
    assert label["reason"] == "identity_not_verified"


if __name__ == "__main__":
    n = len(load_cases())
    print(f"[ok] {GOLDEN.name} parses ({n} cases)")
    test_action_names_are_real_tools()
    print("[ok] all action names match real tools")
    test_forbidden_in_reply_tokens()
    print("[ok] forbidden_in_reply tokens valid")
    test_identity_turns_resolve_from_orders()
    print("[ok] identity turns resolve from orders.json")
    test_session_email_per_case()
    print("[ok] session email per case matches harness intent")
    test_tools_redact_without_verified_session()
    print("[ok] tools redact order PII without verified session")
