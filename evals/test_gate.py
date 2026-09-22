"""Unit tests for the pass^k CI gate decision.

These run offline. The gate is the thing that turns the harness from a
dashboard into something that can block a merge, so its decision logic is
worth testing without spending an API call to find out.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.run_evals import gate_verdict


def test_all_passing_clears_a_full_bar():
    ok, rate, reason = gate_verdict(10, 10, 1.0)
    assert ok is True
    assert rate == 1.0
    assert reason == ""


def test_one_failure_fails_a_full_bar():
    ok, rate, _ = gate_verdict(9, 10, 1.0)
    assert ok is False
    assert abs(rate - 0.9) < 1e-9


def test_partial_bar_allows_some_failures():
    ok, _, _ = gate_verdict(8, 10, 0.8)
    assert ok is True
    ok, _, _ = gate_verdict(7, 10, 0.8)
    assert ok is False


def test_empty_selection_fails_rather_than_passing_vacuously():
    # A gate that goes green because nothing ran is worse than no gate.
    ok, rate, reason = gate_verdict(0, 0, 1.0)
    assert ok is False
    assert rate == 0.0
    assert "nothing verified" in reason


def test_zero_bar_still_requires_cases_to_have_run():
    ok, _, _ = gate_verdict(0, 0, 0.0)
    assert ok is False
    ok, _, _ = gate_verdict(0, 5, 0.0)
    assert ok is True


if __name__ == "__main__":
    test_all_passing_clears_a_full_bar()
    test_one_failure_fails_a_full_bar()
    test_partial_bar_allows_some_failures()
    test_empty_selection_fails_rather_than_passing_vacuously()
    test_zero_bar_still_requires_cases_to_have_run()
    print("[ok] gate tests passed")
