# Outputs (project)

## 1. Company card

**Sierra** — customer-facing agent design for CX automation and measurable performance.

This project mirrors Sierra’s bar: production-shaped workflows (not FAQ chat), structural guardrails (identity, policy, approval gates), and reliability you can defend with benchmarks — including τ²-bench retail alongside a custom golden set.

---

## 2. Project: CX returns & exchange agent

**Retailer:** Singapore Apparel (fictional) · **Stack:** Plain Python, Claude Sonnet 4.6, mock OMS tools — no orchestration framework

| Dimension | Detail |
|-----------|--------|
| **Scope** | End-to-end returns/exchange flows: order lookup → eligibility → inventory (exchanges) → return label, with region-specific policy (`policy.yaml`), identity gates, supervisor audit, and multi-turn eval replay |
| **Success criteria (original)** | Complete scored scenarios with ≥90% correct policy application and safe handoff |
| **Success criteria (achieved)** | **10/10 core cases at pass^5 (100%)** at temperature 1.0 after multi-turn harness + bug fixes; **15-case golden set** with three-layer scoring (actions, content, judge); external validation on **τ²-bench retail: 59/114 (52%)** pass^1 |
| **What it proves** | Tool orchestration and sequencing (not RAG); hybrid deterministic + LLM eval that catches judge/action divergences; pass^k reliability under sampling variance; cost-per-resolution visibility (~$0.05–0.10/solution) |

### Eval arc (measurable)

| Phase | Overall | Notes |
|-------|---------|-------|
| Single-turn harness | 5/10 (50%) | Happy path & policy edges structurally unscorable — agent correctly paused for identity |
| Multi-turn harness | 8/10 (80%) | Scripted follow-ups; two real bugs surfaced |
| After fixes + pass^5 | 10/10 pass^5 | `happy_return_in_window`, `exchange_out_of_stock` fixed via skill prompts |

---

## 3. Agent concept (tools, data, eval plan)

### Tools (mock systems of record)

| Tool | Role |
|------|------|
| `lookup_order` | Order state from `data/orders.json`; PII redacted unless `session_customer_email` matches |
| `check_return_eligibility` | Region windows (SG 30d, MY 14d), final-sale blocks |
| `check_inventory` | Exchange stock check on **requested** replacement size |
| `create_return_label` | RMA + carrier info; only after eligibility (and stock for exchanges) |
| **Supervisor** (`supervisor.py`) | Second-pass audit: policy, PII, approval gates; deterministic fast-paths when trace is unambiguous |
| **Usage tracker** (`usage.py`) | Token-level cost per agent / supervisor / judge call |

Composable skill prompts: `skills/eligibility.py`, `return_flow.py`, `exchange.py`, `escalation.py`.

### Data

| Asset | Location |
|-------|----------|
| Synthetic orders | `data/orders.json` |
| Inventory | `data/inventory.json` |
| Policy (regions, approvals, escalation triggers) | `policy.yaml` |
| Golden test conversations | `evals/golden_set.jsonl` (15 cases) |
| Identity follow-ups (resolved at eval time) | `evals/identity_turns.py` |

### Eval plan

| Layer | What it measures |
|-------|------------------|
| **Actions** | `expected_actions` / `forbidden_actions` on accumulated tool trace |
| **Content** | `forbidden_in_reply` tokens (e.g. `customer_email` on identity mismatch) |
| **LLM judge** | Substance vs `expected_behavior` |
| **pass^k** | k independent runs must all pass — reliability, not one lucky pass |
| **τ²-bench retail** | 114 tasks, DB-state scoring, simulated customer — external generalization check |

**Error taxonomy surfaced:** judge/action divergence (sounds done, trace incomplete); sequencing skips; order-state confusion (SKU vs ordered size); identity-blocked unscorable cases vs real failures.

---

## 4. Proof bundle checklist

| Item | Status | Location |
|------|--------|----------|
| **Repo structure** | ✅ | Root agent (`agent.py`, `supervisor.py`, `tools.py`, `skills/`), mock data (`data/`), eval harness (`evals/`), docs (`docs/`), Flask UI (`app.py`) |
| **README** | ✅ | [`README.md`](../README.md) — architecture, results, cost, τ-bench, run instructions |
| **Architecture doc** | ✅ | [`docs/architecture.md`](architecture.md) |
| **Minimal live demo** | ✅ | `python app.py` → `http://localhost:5000` — paste ticket → tool sequence + policy + label/decline; identity refusal at tool layer |
| **Presenter demo script** | ✅ | [`docs/demo-script.md`](demo-script.md) — 5 scenarios, order IDs, 15/30/45 min timing |
| **Benchmark + test set** | ✅ | 15 scenarios in `evals/golden_set.jsonl`; run `python evals/run_evals.py`; fast guards in `evals/test_golden_set.py`, `evals/test_usage.py` |
| **Case study (learnings + tradeoffs)** | ✅ | [`docs/case-study.md`](case-study.md) — eval journey, bugs, pass^5, cost, lessons |
| **Demo video script** | ✅ | [`docs/demo-script-3min.md`](demo-script-3min.md) — ~3 min Loom script (happy return + identity refusal + harness + τ²-bench) |

### Live demo quick path

1. Scenario 1 (return): order **NW-10088** + `maya.t@northweave.com` → eligibility → label  
2. Scenario 4 (safety): unverified caller on NW-10088 → redacted tool result, no PII  
3. Terminal: `python evals/run_evals.py --case happy_return_in_window --k 1 --verbose` → ACTION / CONTENT / JUDGE + cost

---

## 5. Recruiter hook

Built a returns/exchange agent for a fictional apparel retailer that orchestrates mock OMS tools in sequence (not RAG), supervises drafts before send, and ships a three-layer eval harness that caught real bugs the LLM judge missed — reaching **pass^5 100% on 10 core cases** at temperature 1.0 and **52% on τ²-bench retail** (59/114 tasks). Policy lives in config, PII is blocked at the tool layer, and every eval run reports cost per resolution.

---

## Success criteria

| Criterion | Delivered |
|-----------|-----------|
| **Publish measurable outcomes** | Eval arc 50% → 80% → pass^5 100%; suite breakdowns; judge/action divergence reporting; pass^k at temp 1.0; τ²-bench retail baseline |
| **Scenario scores + error taxonomy** | Per-case ACTION / CONTENT / JUDGE; documented failure modes (`happy_return_in_window`, `exchange_out_of_stock`) and fixes |
| **Regression suite** | `evals/golden_set.jsonl` + `evals/run_evals.py` + `evals/test_golden_set.py`; adversarial suite (5 cases) ready for pass^5 |
| **README** | ✅ |
| **Demo** | Flask UI + [`demo-script.md`](demo-script.md) |
| **Tests / bench** | Golden set guards, usage tests, full harness with cost summary |
| **Narrative of learnings + tradeoffs** | [`case-study.md`](case-study.md) — multi-turn eval shape, policy-in-data vs prompts, supervisor fast-paths, skeptical interpretation of 100% |
