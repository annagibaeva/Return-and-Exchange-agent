"""
test_golden_set.py — tiny guardrail test for the eval data.

Two checks, run on every edit to evals/golden_set.jsonl:

  1. The file still parses (one JSON object per line).
  2. Every action name in expected_actions / forbidden_actions is a REAL tool.

Check 2 matters most: a typo like "create_label" would make a forbidden_actions
guardrail silently never fire — a guardrail that's secretly off. We fail loud
instead, and we source the valid names from tools.py so this can't drift if a
tool is ever renamed.

    python evals/test_golden_set.py     # standalone
    pytest evals/test_golden_set.py     # if pytest is ever added
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools import TOOL_FUNCTIONS

GOLDEN = Path(__file__).parent / "golden_set.jsonl"
VALID_TOOLS = set(TOOL_FUNCTIONS)  # single source of truth: the real tools
ACTION_FIELDS = ("expected_actions", "forbidden_actions")


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


if __name__ == "__main__":
    n = len(load_cases())
    print(f"[ok] {GOLDEN.name} parses ({n} cases)")
    test_action_names_are_real_tools()
    print("[ok] all action names match real tools")
