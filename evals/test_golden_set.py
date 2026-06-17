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
from identity_turns import MULTI_TURN_IDS, order_id_for_case, user_turns_for_case
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
        turns = user_turns_for_case(case, orders)
        assert turns[0].startswith("My email is "), f"{case_id}: missing email turn"
        email = turns[0].removeprefix("My email is ")
        order_id = order_id_for_case(case)
        assert email == orders[order_id]["customer_email"], (
            f"{case_id}: identity turn email must match orders.json for {order_id}"
        )
        assert "user_turns" not in case, (
            f"{case_id}: user_turns must not be stored in golden_set.jsonl"
        )


if __name__ == "__main__":
    n = len(load_cases())
    print(f"[ok] {GOLDEN.name} parses ({n} cases)")
    test_action_names_are_real_tools()
    print("[ok] all action names match real tools")
    test_forbidden_in_reply_tokens()
    print("[ok] forbidden_in_reply tokens valid")
    test_identity_turns_resolve_from_orders()
    print("[ok] identity turns resolve from orders.json")
