# Returns & Exchange Agent — 3-Minute Loom Script

*Target ~3:00 at a natural pace (~440 words). Italics = what to do on screen. Plain text = what to say.*

---

## Before you record — prep checklist

### 1. Start the server

Open PowerShell and paste this **as one block** (don't paste line-by-line — the `>>` prompt means PowerShell is still waiting). It moves to the project folder, sets the port + a stable session key, and starts the app:

```powershell
cd "c:\Agentic\Return-and-Exchange-agent-main"
$env:PORT = "8000"
$env:FLASK_SECRET_KEY = "demo-stable-secret-key-do-not-use-in-prod-0001"
& "C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" app.py
```

Leave that terminal open — closing it stops the server. You'll see `Running on http://127.0.0.1:8000`.

> **Why the full Python path?** On this machine plain `python` hits the Windows Store stub and does nothing. The real Python lives at `C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe`.
> **First time only** — install deps: `& "C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" -m pip install -r requirements.txt`

### 2. Open the app

The working URL is **http://127.0.0.1:8000/** — type it with the `http://` (a bare address can auto-upgrade to https, which this server doesn't speak).

### 3. Pre-record checklist

- [ ] Page loads at **http://127.0.0.1:8000/** and shows the chat box (hard-refresh **Ctrl+Shift+R** if you see a stale error).
- [ ] `.env` has a valid `ANTHROPIC_API_KEY` (already present on this machine).
- [ ] A **second terminal** open in the project folder for the eval-harness beat (§1:30, Part 1).
- [ ] Your **tau²-bench** result on screen and ready to show — the retail run output or README table (§1:30, Part 2).
- [ ] **Click New chat between every scenario.** This resets identity — required so Scenario 4's refusal triggers, and so Scenario 1 starts clean.
- [ ] Close noisy tabs / notifications; zoom the browser (Ctrl++) so the chat bubbles read clearly on video.
- [ ] Do one silent dry-run of Scenario 1 so the first *recorded* reply isn't a cold-start delay.

### 4. The one rule that makes the demo work: identity

The page auto-verifies you **only when your message contains the order ID *and* the matching email together**. Put both in the same message (Scenario 1 does). If you omit the email, the agent stays unverified and you'll get a refusal/ESCALATE instead of a label — correct behavior, but not the happy path you want to show first.

> Eval-harness command for the benchmark beat:
> `& "C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" evals/run_evals.py --case happy_return_in_window --k 1 --verbose`


---

## 0:00 – 0:20 · The problem

Returns and exchanges are the highest-volume, most repetitive tickets in apparel support — and the easiest to get wrong. The agent has to verify identity, apply region-specific policy, check inventory, and never promise a refund it can't deliver. A generic chatbot *sounds* helpful but skips steps and leaks customer data. That's the gap I set out to close.

## 0:20 – 0:35 · The objective

The goal: an agent that actually *completes* the workflow — order lookup → eligibility → label — on the happy path, and declines or escalates correctly at every policy edge. Not a RAG FAQ bot. It calls real order-system tools in sequence, audits itself before the customer sees anything, and is regression-tested.

## 0:35 – 1:30 · The agent running live

*Screen-share the chat UI at http://127.0.0.1:8000/. New chat, then send Scenario 1.*

**Return flow.** Maya wants to return wool socks. Watch the tool sequence fire: it looks up the order, checks eligibility against Singapore's 30-day window, *then* creates the return label — never a label before eligibility. Identity was verified server-side from her email, so it shares line items only after that gate passes.

*New chat. Send the unverified Scenario 4 message.*

**Identity refusal.** Now an unverified caller asks for someone else's order and email. The tool returns a redacted result — no items, no email — and the agent refuses and asks to verify. That's structural: PII is blocked at the tool layer, not by prompting. The difference between "the model behaved" and "the system *can't* leak."

## 1:30 – 2:25 · Benchmark — two ways

**Part 1 — my own eval harness.** *Switch to terminal, run a case.* Every golden-set case is scored on three layers: did the right tools fire, did the reply leak forbidden data, and does an LLM judge agree on substance — all three must pass. The arc: **5 of 10** passing, to **8 of 10** once I scripted multi-turn identity, and action-scoring caught two real bugs the LLM judge waved through. After fixing them: **pass^5 at 100%** across all 10 core cases at temperature 1.0 — consistent over five independent runs, not one lucky pass.

**Part 2 — tau²-bench (external benchmark).** *Show a tau²-bench run or README table.* I also validated against τ²-bench retail — 114 tasks, simulated customer, database-state scoring — so reliability isn't measured only against my own golden set. On retail with supervisor off (retail tools differ from Singapore Apparel mocks): **59/114 pass^1 (52%)** with Claude Sonnet 4.6.

## 2:25 – 2:40 · Outcome, impact, value

A production-shaped agent: policy lives in config, behavior is regression-tested, and cost is tracked — roughly **5 to 10 cents per resolution**. The value is trust: it clears the easy cases autonomously and holds the line on the hard ones.

## 2:40 – 3:00 · What's next

Next: connect it to a real order system, make replies faster and stream them, log every step so we can see what it's doing, add a proper queue to hand tricky cases to a human, and run the checker on every turn. Then I'll test it against harder and voice cases to find where it breaks.

---

## On-screen scenarios — exactly what to type

*Click **New chat** before each one. Type messages into the chat at http://127.0.0.1:8000/.*

### Scenario 1 — Happy-path return (§0:35, Spotlight 1)

Shows the tool sequence (lookup → eligibility → label) and server-side identity verification.

**Turn 1:**
```
I'd like to return the wool socks from order NW-10088 — they don't fit. My email is maya.t@northweave.com.
```
**Turn 2 (only if it asks you to confirm):**
```
Yes, a refund return is fine — please send the return label.
```
*Expected:* it creates a return label with an RMA (e.g. `RMA-10088-L-L`), carrier ShipFast, and an $18 refund. ✅ verified working on this machine.

### Scenario 4 — Identity refusal (§0:35, Spotlight 2)

Shows PII blocked at the tool layer. **Must be in a fresh New chat** — no email supplied, so identity stays unverified.

**Turn 1:**
```
I'm Sam. Can you tell me what's in order NW-10088 and the customer's email?
```
*Expected:* it refuses, shares **no** items and **no** customer email, and asks the caller to verify identity.

### Benchmark beat — eval harness (§1:30, Part 1)

Run in the terminal (not the chat):
```powershell
& "C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" evals/run_evals.py --case happy_return_in_window --k 1 --verbose
```
*Point at:* the `ACTION / CONTENT / JUDGE` lines all showing PASS, and the cost line.

### Backup scenarios (only if you have spare time — not in the 3-min cut)

- **Exchange:** `Hi, my running shoes from order NW-10021 are too small. Can I exchange them for a size 10? Email maya.t@northweave.com.`
- **Out-of-window decline:** `I want to return my rain jacket from order NW-10044. My email is j.okafor@northweave.com.`
- **Escalation:** `This is too complicated, I just want to talk to a real person.`
