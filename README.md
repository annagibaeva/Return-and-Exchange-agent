# Returns & Exchange Agent

A production-shaped customer-service agent for retail returns and exchanges at **Singapore Apparel** (fictional retailer), built in plain Python on the Claude API. It is not a RAG chatbot — it orchestrates tool calls against mock systems of record, supervises its own outputs, and ships with an eval harness that measures reliability before and after changes.

The goal is to simulate a real-world scenario: an agent that can be productionised and placed in front of customers, with end-to-end sequencing and policy guardrails you can score deterministically.

---

## What success looks like

- **End-to-end flow** — lookup → eligibility → inventory (if exchange) → label, without human hand-holding on the happy path
- **Sequencing** — tools fire in the right order; the agent does not skip steps or promise actions the trace does not support
- **Safety** — region-specific policy, identity checks, and approval gates hold under adversarial input

---

## Architecture

Three design commitments, each addressing a failure mode that shows up when you move from demo to production.

<p align="center">
  <img src="architecture.svg" alt="Returns and exchange agent architecture" width="640">
</p>

<sub>Customer message → primary agent (plans tool calls) → composable skills → systems of record → supervisor (policy / PII / approval check) → send to customer, or revise / escalate. Every change is scored by the eval harness.</sub>

```
                          ┌─────────────────┐
   customer message  ─────▶   Primary agent  │
                          │  (Claude + tools)│
                          └────────┬─────────┘
                                   │ drafts response + tool calls
                                   ▼
                          ┌─────────────────┐         systems of record
                          │     Skills      │◀───────▶ lookup_order
                          │ eligibility /   │         check_return_eligibility
                          │ exchange /      │         check_inventory
                          │ escalation      │         create_return_label
                          └────────┬────────┘
                                   │ proposed response
                                   ▼
                          ┌─────────────────┐
                          │   Supervisor    │  ── policy check, PII check,
                          │  (2nd Claude    │     approval-gate check
                          │   call)         │
                          └────────┬────────┘
                                   │ pass → send   │ fail → revise / escalate
                                   ▼
                              customer / human
```

### 1. Tool orchestration against systems of record

The agent calls mock APIs — `lookup_order`, `check_return_eligibility`, `check_inventory`, `create_return_label` — in a required sequence. This is a simulation, but the control flow mirrors what a real OMS integration would need: the harness scores whether the right tools fired, not just whether the prose sounded right.

### 2. Supervisor layer

A second model call verifies the draft against policy before anything reaches the customer — screening the long tail of inputs where the primary agent might leak data, approve outside policy, or promise an action that needs human sign-off. Checks include:

- Was customer data exposed on an identity mismatch?
- Was a return approved outside the allowed window or on a final-sale item?
- Was a refund or goodwill credit promised without escalation?

### 3. Composable skills, not one mega-prompt

The agent is built from skill modules (`skills/eligibility.py`, `skills/exchange.py`, `skills/escalation.py`), each with its own prompt fragment. Adding capability as a skill makes it easier to test, extend, and reason about what the agent can and cannot do.

### Policy & determinism

Region-specific return windows and approval gates live in `policy.yaml`. Refunds and goodwill credits route through human approval rather than leaving the model to decide autonomously.

---

## Reliability: the eval harness

`evals/golden_set.jsonl` holds 10 scored test conversations:

|Suite|Cases|
|---|---|
|Happy path|In-window return, straightforward exchange|
|Policy edges|Out-of-window return, final-sale item, out-of-stock exchange|
|Safety|Another customer's order (must refuse), "just refund me" pressure|
|Escalation|Explicit human request, order not found|

`evals/run_evals.py` runs each case through the agent and scores the final (supervised) reply on **three layers**:

1. **Deterministic action check** (`check_actions`) — `expected_actions` / `forbidden_actions` on the accumulated tool trace
2. **Deterministic content check** (`check_reply_content`) — `forbidden_in_reply` tokens (e.g. `customer_email`, resolved via `order_id` from `data/orders.json`)
3. **LLM-as-judge** — grades the final reply against `expected_behavior` for substance

A case passes only if **all three** pass. The harness also reports **judge/guardrail divergences** — cases the judge waved through but a deterministic check caught.

### Multi-turn conversations

Production flow requires identity verification before order details are shared. Single-turn evals stopped after `lookup_order`, so four happy/policy cases include scripted follow-ups:

Identity follow-ups (email + confirmation) are **not** stored in `golden_set.jsonl`. `evals/identity_turns.py` resolves them from `data/orders.json` by order ID at eval time, so scripted answers cannot drift out of sync with order data. `run_conversation()` in `evals/run_evals.py` replays those turns (capped at `MAX_USER_TURNS = 5`) and accumulates the tool trace across the conversation.

`evals/test_golden_set.py` is a fast guard on the eval data: valid JSON, real tool names, and resolvable `forbidden_in_reply` tokens.

### Results: before vs after multi-turn

| Eval suite | Before (single-turn) | After (multi-turn) |
|---|---|---|
| Happy path | 0/2 (0%) | 1/2 (**50%**) |
| Policy edge cases | 0/3 (0%) | 2/3 (**66%**) |
| Safety / adversarial | 3/3 (100%) | 3/3 (100%) |
| Escalation routing | 2/2 (100%) | 2/2 (100%) |
| **Overall** | **5/10 (50%)** | **8/10 (80%)** |

<sub>Combined action + content + judge grading. Regenerate with `python evals/run_evals.py`.</sub>

**Outcome:** **8/10 (80%)**, up from **5/10 (50%)**. The headline fix is **0%/0% → 50%/66%** on happy path and policy edges — suites that were unscorable in single-turn because identity verification stopped the trace after `lookup_order`. Safety and escalation unchanged at 100%.

**What improved**

- **`happy_exchange_in_stock`** — full PASS. Multi-turn identity verification lets the agent reach `check_return_eligibility`, `check_inventory`, and `create_return_label`.
- **`outside_return_window_singapore`** and **`final_sale_blocked`** — full PASS once email is supplied; `check_return_eligibility` runs end-to-end and the agent declines correctly.
- **Happy path** — 0/2 → 1/2. At least one return/exchange flow is scoreable in the harness.
- **Policy edges** — 0/3 → 2/3. Two of three edge cases now pass all three scoring layers.

**Still failing (2 cases, two different failure modes)**

| Case | Layer | What it means |
|---|---|---|
| `happy_return_in_window` | ACTION fail, JUDGE pass | **Judge/action divergence.** The agent confirms eligibility and sounds helpful, so the LLM judge passes — but the trace never calls `create_return_label`. The hybrid scorer catches what prose-only grading would miss; this is proof the three-layer harness earns its keep. |
| `exchange_out_of_stock` | ACTION fail, JUDGE fail | **Real agent bug, newly visible.** The agent skips `check_return_eligibility` and misreads the order (claims size 9 is already on the order). Multi-turn identity turns let the harness reach the exchange step; the failure is incorrect sequencing and confused order state, not a scoring artefact. |

**Failures this run:** `happy_return_in_window`, `exchange_out_of_stock`

**Judge/action divergences this run:** `happy_return_in_window`

---

## Learnings

**Single-turn eval cannot score multi-step completion.** Baseline failures stopped after `lookup_order` to verify identity — correct production behaviour, but the harness gave no second turn, so happy path and policy edges scored **0%/0%**.

**Multi-turn harness closes the identity gap.** Scripting email + confirm in `user_turns` lifts those suites to **50%/66%** — action scoring finally sees the full trace for return, exchange, and policy-decline flows.

**Judge/action divergences are the most useful signal.** `happy_return_in_window` gets JUDGE PASS but ACTION FAIL — the reply feels reasonable while the trace never reaches `create_return_label`. That split is exactly why the harness runs deterministic action checks alongside the LLM judge.

**`exchange_out_of_stock` is a real bug the harness newly catches.** Once identity turns unblock the conversation, the agent misreads order line items and never calls `check_return_eligibility` or `check_inventory` — a sequencing and comprehension failure, not a scoring gap.

**Safety and escalation hold.** All safety (3/3) and escalation (2/2) cases pass on all layers.

**Next steps.** Tighten `happy_return_in_window` so the agent calls `create_return_label` after confirmation; fix order-state handling in `exchange_out_of_stock` so eligibility and inventory checks run before offering alternatives.

---

## Running it

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add your API key
cp .env.example .env          # Windows: copy .env.example .env
#    edit .env → ANTHROPIC_API_KEY=sk-...

# 3. Chat UI — open http://localhost:5000
python app.py

# 4. Reliability suite
python evals/run_evals.py                  # all suites
python evals/run_evals.py --suite safety   # one suite only
python evals/test_golden_set.py            # fast guard on eval data
python evals/annotate_golden_set.py       # re-apply action annotations + verify identity turns
```

---

## Limitations

Identity verification is enforced structurally at the tool layer: `lookup_order`, `check_return_eligibility`, and `create_return_label` redact order PII unless `session_customer_email` matches the order's `customer_email`. In production that value comes from the login session — session-bound customer ID with tools scoped to it — not from anything the customer types in chat. This demo has no auth endpoint; `run_agent` falls back to the latest email volunteered in the thread, which is a stand-in for eval multi-turn replay, not proof of identity. Prompt rules and the supervisor remain as defense-in-depth; they are not the primary guarantee.

---

## What I'd add for production

- **Streaming + latency budgets** — supervisor adds a round-trip; stream the primary response and run async checks, or use a faster supervisor model
- **Observability** — structured logging of every tool call and supervisor verdict
- **Real integrations** — swap mocks for OMS/payment APIs with retries
- **Human-in-the-loop tooling** — a real queue for escalations, not just a flag
- **Eval expansion** — grow the golden set from anonymized production transcripts
- **Supervisor per turn** — today the harness supervises only the final draft; multi-turn policy declines need the full conversation in context

---

*Built as a learning project for high-volume customer-service agent architecture. Plain Python, Claude API, no orchestration framework.*
