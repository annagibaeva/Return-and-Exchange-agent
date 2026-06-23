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

`evals/golden_set.jsonl` holds 15 scored test conversations:

|Suite|Cases|
|---|---|
|Happy path|In-window return, straightforward exchange|
|Policy edges|Out-of-window return, final-sale item, out-of-stock exchange|
|Safety|Another customer's order (must refuse), "just refund me" pressure|
|Escalation|Explicit human request, order not found|
|Adversarial|Wrong order ID then correction, return+exchange in one message, partial email, double pushback, Singlish/English|

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

## Pass^k reliability scoring

**Why does it matter** Average pass rates hide unreliability of your agent. An agent that passes 80% of the time per attempt looks fine on a single run but fails one in five customers — unacceptable at production scale. pass^k asks a stricter question: across k identical runs, does the case pass every time? Agent needs to work on any run whether it is reporting pass@1 (single attempt), mean pass-rate, and pass^5. Objective is to ensure that there is no gap between "usually works" and "reliably works" visible — this is matters for trust.

**What i did**
1. Single-turn eval structurally couldn't score task completion — the agent pauses to verify identity, and the conversation ended before it could finish (happy_path and policy_edges scored 0%).
2. Built a scripted multi-turn harness so cases run to completion.
3. Hybrid action+judge scoring exposed two real bugs the LLM judge alone missed: an inventory misreport on exchange_out_of_stock, and a return-completion failure on happy_return_in_window.
4. Fixed both.
5. pass^5 now 100% across all 10 cases at temperature 1.0.
6. Next: adversarial cases to find where it breaks.

**Results (temperature 1.0, k=5)**
escalation     pass^5: 2/2 (100%)   mean 1.00
happy_path     pass^5: 2/2 (100%)   mean 1.00
policy_edges   pass^5: 3/3 (100%)   mean 1.00
safety         pass^5: 3/3 (100%)   mean 1.00

**What it means**: A perfect score is not proof of a good agent — it usually means the eval isn't hard enough yet. Ten passing cases show where the agent works, not where it breaks. What makes the 100% credible is that this harness has already caught real failures: the two bugs above failed visibly, action-scoring flagged them, and the green is the result of fixing them — not of a test too weak to fail. An eval that has never caught anything hasn't been shown capable of catching anything.

**Three design decisions there were important.**

**Temperature**. The agent runs at the SDK default (1.0), not 0. This matters: at temperature 0, k=5 would be near-deterministic and 100% pass^5 would measure decoding stability, not behavioral reliability. At 1.0, the agent faced genuine response variance across runs and stayed consistent — so the result reflects reliability, not determinism.
**Cost**. See [Cost per solution](#cost-per-solution) — the harness now bills every eval run from actual token usage.
**Variance interpretation**. The split that matters: a case failing 0/5 is a consistent bug (fix the agent); a case at 3/5 is flaky (a reliability problem — does it skip a tool, or does the judge grade borderline tone differently?). Same low pass^5, opposite root cause — which an averaged score erases.

**Next**: run the adversarial suite at pass^5 and analyse where reliability breaks — a 70% pass^5 on hard cases, with cost data, is worth more than 100% on easy ones.

---

## τ-bench retail — external benchmark

The golden-set harness scores **pass^5: 100%** on 10 cases the agent was built around. [τ-bench](https://github.com/sierra-research/tau2-bench) retail is a harder, external test: **114 tasks**, LLM-simulated customer, database-state scoring against the retail domain's real tools and policy — not Singapore Apparel mocks.

### Result

| Metric | Score |
|---|---|
| **This agent** | **52% pass^1** (1 trial) |
| GPT-4.1 baseline | ~74% |
| Claude 3.7 Sonnet baseline | ~79% |

The agent scored **~20–27 points below** generic baselines on the same split. That is the real number. The gap from this repo's **100% pass^5** is the lesson: the golden set tested cases I imagined; τ-bench tested the ones I didn't.

<sup>1</sup> *pass^1 only — not comparable to baselines reported at pass^4.*

### Why it scored low — three structural mismatches

**1. Tool misalignment (biggest lever).** Skills steer the model toward Singapore Apparel's API (`lookup_order`, `create_return_label`) — tools that do not exist in τ-bench retail, which uses `find_user_id_by_email`, `return_delivered_order_items`, etc. The adapter injects τ-bench's policy and can swap in τ-bench-specific skill blocks, but with legacy skills the agent partly fights its own instructions.

**2. Supervisor tuned for the wrong domain.** The supervisor fast-paths on `create_return_label` / `check_inventory` — never present in τ-bench — so it always falls through to auditing against Singapore Apparel policy that does not match the retail DB. Noise, not help.

**3. τ-bench scoring is strict and multiplicative.** A task passes only if final DB state, action sequence, and exact-number assertions (refund amounts, counts) all align. The dominant failure mode (**53/55** failing tasks) is wrong final DB state — plausible conversation, wrong write. Same "talks but doesn't act" failure the golden-set harness was built to catch, now at scale.

### Hypothesis (falsifiable)

Most of the gap is **integration, not reasoning**. Aligning skills to τ-bench's real tools and enforcing a write-after-confirmation rule should move **52% → ~65–70%**; closing cancel/modify coverage and exact-number replies should approach the **~74%** baseline. If those fixes do not move the score, the problem is deeper than alignment — which is itself worth knowing.

### Next on τ-bench

- Align skills to τ-bench retail tool names (drop Singapore Apparel workflow references)
- A/B the supervisor (`--no-supervisor` on benchmark runs — test whether it helps or hurts)
- Enforce write-after-yes; fix number assertions in replies
- Expand the golden set to cover cancel/modify/address tasks it currently ignores

### Limitations of this run

- **1 trial** — pass^1 only; baselines use pass^4
- **Cost not instrumented** — ~50h wall time, ~27 min/task
- **Adapter, not native tools** — τ-bench runs via `examples/agents/return_exchange_agent_tau2.py` in the τ-bench repo; this tests skills/supervisor bridged in, not the original `tools.py` layer

### Running τ-bench retail

From the **τ-bench** repo root (this workspace), with API keys in `.env` (`ANTHROPIC_API_KEY` for the agent, `OPENAI_API_KEY` for the user simulator):

```powershell
# Smoke test (3 tasks)
uv run python examples/agents/return_exchange_agent_tau2.py `
    --return-agent-path "C:/Agentic/tau2-bench-sierra-main/.review/Return-and-Exchange-agent" `
    --task-ids 0 1 2 `
    --user-llm openai/gpt-4.1-mini

# Full retail base split (114 tasks)
uv run python examples/agents/return_exchange_agent_tau2.py `
    --return-agent-path "C:/Agentic/tau2-bench-sierra-main/.review/Return-and-Exchange-agent"

# A/B: disable supervisor or use legacy Singapore Apparel skills
uv run python examples/agents/return_exchange_agent_tau2.py `
    --return-agent-path "C:/Agentic/tau2-bench-sierra-main/.review/Return-and-Exchange-agent" `
    --no-supervisor
```

Results land under `data/simulations/return-exchange-agent-retail/`. Browse with `uv run tau2 view`.

---

## Cost per solution

Every eval run bills **actual API token usage** — not a call-count estimate. A *solution* is one full attempt to resolve a golden-set case: agent tool loop(s) + supervisor + judge, including scripted multi-turn follow-ups.

`usage.py` records `input_tokens` / `output_tokens` from each Anthropic response. `run_evals.py` aggregates per run and prints a summary at the end.

### What you get

| Metric | Meaning |
|---|---|
| **Per solution** | Average cost across all k runs for the selected case(s) — passes and failures alike |
| **Per passing solution** | Average cost only for runs that pass all three scoring layers |
| **By component** | Split across `agent`, `supervisor`, and `judge` |

### Example output

```bash
python evals/run_evals.py --case happy_return_in_window --k 1
```

```
  run 1/1 [PASS]  ...  cost=$0.0740  tokens=20,379in/859out  calls=9

==================================================
COST PER SOLUTION
==================================================
  Total: $0.0740  (20,379 in / 859 out, 9 API calls across 1 solutions)
  Per solution (avg over k=1): $0.0740
  Per passing solution: $0.0740 (1/1 passed)
  agent        $0.0721  (8 calls, 19,972 in / 812 out)
  judge        $0.0019  (1 calls, 407 in / 47 out)
  (Sonnet 4.6 @ $3/MTok in, $15/MTok out; supervisor fast-path = $0)
```

### Where the cost goes

- **Agent (~95%)** — dominates because each tool-loop iteration resends the system prompt and growing conversation. Multi-turn cases (2–3 scripted follow-ups) multiply agent calls.
- **Judge (~3%)** — one Sonnet call per solution to grade the final reply.
- **Supervisor ($0 when fast-path hits)** — deterministic checks (label confirmed in trace, out-of-stock handled) skip the LLM supervisor entirely. Only borderline drafts trigger a billed supervisor call.

### Pricing assumptions

Rates in `usage.py` (standard, pre-cache/batch):

| Model | Input | Output |
|---|---|---|
| `claude-sonnet-4-6` | $3.00 / MTok | $15.00 / MTok |

### Rough budgets

| Run | Solutions | Estimated cost |
|---|---|---|
| Single case, k=1 | 1 | ~$0.05–0.10 |
| Adversarial suite, k=5 | 25 | ~$1.50–2.50 |
| Full harness (15 cases), k=5 | 75 | ~$5–8 |

Run deliberately — not in a CI loop on every commit. Use `--k 1` for smoke tests, `--suite adversarial` to probe hard cases without billing the full set.

```bash
python evals/run_evals.py --suite adversarial --k 5   # cost + pass^5 on hard cases
python evals/test_usage.py                            # unit tests for cost math
```

## Learnings

**Single-turn eval cannot score multi-step completion.** Baseline failures stopped after `lookup_order` to verify identity — correct production behaviour, but the harness gave no second turn, so happy path and policy edges scored **0%/0%**.

**Multi-turn harness closes the identity gap.** Scripting email + confirm in `user_turns` lifts those suites to **50%/66%** — action scoring finally sees the full trace for return, exchange, and policy-decline flows.

**Judge/action divergences are the most useful signal.** `happy_return_in_window` gets JUDGE PASS but ACTION FAIL — the reply feels reasonable while the trace never reaches `create_return_label`. That split is exactly why the harness runs deterministic action checks alongside the LLM judge.

**`exchange_out_of_stock` is a real bug the harness newly catches.** Once identity turns unblock the conversation, the agent misreads order line items and never calls `check_return_eligibility` or `check_inventory` — a sequencing and comprehension failure, not a scoring gap.

**Safety and escalation hold.** All safety (3/3) and escalation (2/2) cases pass on all layers.

**τ-bench is the harder truth.** Golden-set pass^5 at 100% does not transfer to τ-bench retail at 52% pass^1 — tool misalignment, supervisor domain mismatch, and strict DB-state scoring dominate. See [τ-bench retail — external benchmark](#τ-bench-retail--external-benchmark).

**Next steps.** Tighten `happy_return_in_window` so the agent calls `create_return_label` after confirmation; fix order-state handling in `exchange_out_of_stock`; align skills and supervisor for τ-bench retail tools; expand golden-set coverage for cancel/modify/address flows.

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

# 4. Reliability suite (prints cost-per-solution summary at the end)
python evals/run_evals.py                  # all suites
python evals/run_evals.py --suite adversarial --k 5
python evals/run_evals.py --case happy_return_in_window --k 1
python evals/test_golden_set.py            # fast guard on eval data
python evals/test_usage.py                 # cost tracking unit tests
python evals/annotate_golden_set.py       # re-apply action annotations + verify identity turns
```

**τ-bench retail** — run from the τ-bench repo root (see [τ-bench retail — external benchmark](#τ-bench-retail--external-benchmark)):

```powershell
uv run python examples/agents/return_exchange_agent_tau2.py `
    --return-agent-path "C:/Agentic/tau2-bench-sierra-main/.review/Return-and-Exchange-agent"
```

---

## Limitations

Identity verification is enforced structurally at the tool layer: `lookup_order`, `check_return_eligibility`, and `create_return_label` redact order PII unless `session_customer_email` matches the order's `customer_email`. In production that value comes from the login session — session-bound customer ID with tools scoped to it — not from anything the customer types in chat. The Flask demo (`app.py`) binds identity via `POST /verify` (order ID + email checked against `data/orders.json`); the web UI passes `allow_chat_email_fallback=False` so chat text cannot spoof the session. The REPL (`chat.py`) and eval harness keep the default chat-email fallback for multi-turn replay. Prompt rules and the supervisor remain as defense-in-depth; they are not the primary guarantee.

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
