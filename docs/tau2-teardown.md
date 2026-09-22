# τ²-bench teardown

The safety layer I was proudest of was making my agent worse. On τ²-bench retail, Sierra's public benchmark for customer-service agents, my returns agent passed 59 of 114 tasks (52%); after switching that layer off and pointing the agent at the right tool names, the same agent on the same model — Claude Sonnet 4.6 — passed 92 (81%).

| Run | Setup | Tasks passed |
|-----|-------|--------------|
| Run 1 | Singapore Apparel instructions, supervisor on | 59/114 (52%) |
| Side test, tasks 0–5 | Supervisor on vs off | 2/6 vs 4/6 |
| Run 2 | τ²-bench instructions, write rules, supervisor off | 92/114 (81%) |

One trial per task; published baselines often use pass^4, so compare directionally. Full transcripts are not in the repo; counts match the README. My own golden-set harness (10 Singapore Apparel cases, five runs each, all passing) is a separate test on a store I wrote myself, and says nothing about how this agent behaves anywhere else.

The model's reasoning never changed. What changed was that I stopped pointing the agent at a store that wasn't there.

## What τ²-bench is testing

τ²-bench ships a simulated retail store: a database of users, orders and products, a set of tools that read and write that database, and 114 tasks.

Each task puts an LLM-simulated customer in front of your agent with a goal — cancel this pending order, return two items from a delivered one, change the shipping address, swap the payment method. The agent gets that store's tools and that store's policy document, and has to work the request through the conversation.

The part that makes it different from most agent evals: **it does not read the conversation to decide whether you passed. It reads the store.**

The store is a database — rows for users, orders, items, payments. Every task ships with the rows that should exist once the request has been handled correctly. When the conversation ends, the harness dumps the database and diffs it against those rows: is this order's status field now `cancelled`, does a return row exist against the right two items, is the refund amount right to the cent. It also checks the sequence of tool calls the agent made along the way, and assertions on specific numbers it should have quoted.

So "your order has been cancelled" earns nothing. The order has to be cancelled. An agent that is fluent, polite, correctly apologetic and never writes to the database scores zero.

That is also why it measures the agent rather than the model. The tool layer is common to everyone who runs it — same store, same 114 tasks, same simulated customers. What varies between submissions is the scaffolding built on top: prompts, control flow, guardrails. My two runs held the model constant as well, so the 29-point gap between them is scaffolding and nothing else.

## The agent I brought to it

I built this agent for Singapore Apparel: a hypothetical clothing company, with synthetic data. Its tools are mocks I wrote that return fake orders — `lookup_order`, `check_return_eligibility`, `create_return_label`, `check_inventory`.

Two layers matter here, because both are where it broke.

**The instructions** are skill files telling the model how to handle returns and exchanges for this one customer. They name the mock tools directly, and they work against whatever policy Singapore Apparel has configured — read from a config file at runtime, currently a 30-day return window (14 in Malaysia), no returns on final sale, refunds always requiring human approval.

**The supervisor** is a second model call that runs after the agent drafts a reply and before it reaches the customer. It reads the draft, the conversation and the tool trace, checks them against that policy, and returns PASS, REVISE or ESCALATE. On ESCALATE the draft is discarded and replaced with a holding message: *"I'm connecting you with a member of our team."*

In front of the supervisor sit the **shortcuts**: two deterministic rules that approve obviously-fine replies without paying for the second model call. One fires when the trace shows a return label was created against an eligible check and the draft names that label. They skip the supervisor's review — not the agent's reasoning.

## What went wrong

Both layers failed for the same reason: they were built for one store and pointed at another.

### The supervisor turned correct work into escalations

- It checks every reply against Singapore Apparel's policy, including "refunds always need human approval."
- In τ²-bench's store, handling that refund yourself is the correct answer. So the supervisor kept reading correct work as a policy breach.
- Its shortcuts — the rules that wave an obviously-fine reply through without a second model call — all look for Singapore Apparel's tools. None of them exist here, so no shortcut ever fired and **every single reply went to the supervisor for review.**
- When it escalated, the agent's reply was thrown away and replaced with "I'm connecting you with a member of our team." The customer now has nothing to confirm, so the agent never writes, so the database never changes.
- On a benchmark that reads the store, a polite handoff and a wrong answer score the same: zero.
- Worse than the same agent with the supervisor off: 2/6 against 4/6 on a six-task side test. Six tasks proves nothing alone, but it matched the transcripts — and it spent an extra model call on every turn to get there.

### The instructions described a store that wasn't there

- The skill files tell the model which tools to use by name, and those names were Singapore Apparel's mocks, not this store's.
- So the agent kept reaching for tools that were not in front of it.
- Lookups mostly survived. "Find the customer" has an equivalent in any store, and the model found it.
- Writes mostly did not. A write needs the exact tool, the exact order state and the exact arguments — there is nothing to improvise with. And writes are what the benchmark reads.

## What I changed

**1. Turned the supervisor off and re-ran.** Six tasks, nothing else changed: 2/6 became 4/6. That was enough to stop treating the supervisor as a fixed part of the agent and start treating it as a Singapore Apparel component. It stays on there, and is off by default in the τ²-bench adapter.

**2. Rewrote the instructions around τ²-bench's tool names** — `find_user_id_by_email`, `cancel_pending_order`, `modify_pending_order_items`, `return_delivered_order_items` in place of the mock tools.

**3. Added rules for the write path,** where the failures sat: write only after the customer says yes, one action per turn; never claim an action is done before the tool result is in the trace; authenticate before sharing order data; route by order status, so pending orders go to cancel/modify tools and delivered orders to return/exchange; use the exact cancellation reason strings the system accepts, verbatim; quote calculator-sourced refund amounts before asking for confirmation; stop escalating routine work.

All three went in together in the full run, so I cannot split the credit. The six-task A/B gives partial attribution to the supervisor and none to the other two.

## What still fails

22 tasks. Run 2 breakdown: reads correct 93.8% (335/357), writes 83.5% (147/176), database match 82.5% (94/114). Failures cluster in writes, not lookups — the agent finds the right order, then misses the write or gets an argument wrong.

I have not categorised all 22 by root cause, so I know where they sit but not yet why each one fell over. That is the next piece of work, and what would tell me whether the remaining gap is more rules or a real reasoning limit.

Worth noting that 94 tasks ended with a matching database but only 92 passed: two got the end state right and the action sequence or a number assertion wrong.

## Before this goes near a real customer

A checklist I would want cleared before deploying an agent like this into anyone's live systems:

1. **Every tool the agent and its guardrails can call exists in this customer's stack.** Not just the agent's tools — the guardrail's conditions too. Mine silently degraded to "always ask the model" because it was pattern-matching on tool names that had disappeared.
2. **The guardrail's policy is this customer's policy.** A rule that is protective in one deployment is a blocker in the next. Re-read every hardcoded threshold, approval requirement and escalation trigger against the new contract.
3. **The agent never says an action is done before the tool result is in the log.** "Sounds done, isn't done" is the failure mode that survives every text-based test.
4. **Orders in different states route to different tools,** and enumerated values like cancellation reasons match the exact strings the system accepts.
5. **The acceptance test grades system state, not reply quality.** If the test can be passed by a well-worded message, it is not a test.
6. **Escalation is counted, not just allowed.** An escalation rate that quietly climbs is the same failure as a wrong answer, and it does not look like one in a transcript review.
7. **Before go-live, re-run the whole suite against the customer's own systems in a sandbox.** 81% on someone else's store tells me the scaffolding is portable. It tells me nothing about this customer's store. The first run against their stack is the only number that should gate a deployment — and by then every item above has a concrete answer rather than an assumption.

## Links

- [README: τ-bench section](../README.md)
- Benchmark code for this agent lives in my τ-bench fork: `examples/agents/return_exchange_agent_tau2.py`, `tau2_retail_skills.py`
