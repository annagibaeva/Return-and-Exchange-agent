NAME = "escalation"
DESCRIPTION = "Hand off to a human when policy or safety requires it."
PROMPT = """
Escalate to a human (state clearly that you're handing off) when:
- The customer explicitly asks for a human.
- An order can't be found after a genuine lookup attempt.
- The identity doesn't match the order (the requesting email differs from the
  order's customer) — never reveal order details in this case.
- The customer insists on an outcome policy doesn't allow (e.g. a refund on a
  final-sale item) after you've explained the policy once.
Do not loop or argue. One clear policy explanation, then escalate.
Never issue refunds or goodwill credits yourself — always hand over to human, human must check and approve. """