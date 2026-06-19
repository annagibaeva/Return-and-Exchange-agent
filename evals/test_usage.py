"""Unit tests for usage/cost tracking."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from usage import UsageTracker, cost_usd


def test_cost_usd_sonnet_rates():
    # 1M input @ $3 + 1M output @ $15 = $18
    assert cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == 18.0


def test_usage_tracker_summary_empty():
    summary = UsageTracker().summary()
    assert summary["api_calls"] == 0
    assert summary["cost_usd"] == 0.0


class _FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResponse:
    def __init__(self, input_tokens, output_tokens):
        self.usage = _FakeUsage(input_tokens, output_tokens)


def test_usage_tracker_records_response():
    tracker = UsageTracker()
    tracker.record("agent", "claude-sonnet-4-6", _FakeResponse(10_000, 2_000))
    tracker.record("judge", "claude-sonnet-4-6", _FakeResponse(1_000, 200))
    summary = tracker.summary()
    assert summary["api_calls"] == 2
    assert summary["input_tokens"] == 11_000
    assert summary["output_tokens"] == 2_200
    assert summary["by_component"]["agent"]["calls"] == 1
    assert summary["by_component"]["judge"]["calls"] == 1
    expected = cost_usd("claude-sonnet-4-6", 11_000, 2_200)
    assert abs(summary["cost_usd"] - expected) < 1e-9


if __name__ == "__main__":
    test_cost_usd_sonnet_rates()
    test_usage_tracker_summary_empty()
    test_usage_tracker_records_response()
    print("[ok] usage tests passed")
