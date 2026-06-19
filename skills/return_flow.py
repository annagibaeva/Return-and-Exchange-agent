NAME = "return"
DESCRIPTION = "Complete a standard return when the customer wants to send an item back."
PROMPT = """
For a return (customer wants to send an item back for a refund, not an exchange):
1. Look up the order, then check_return_eligibility for the item's SKU.
2. If eligible and the customer has already asked to return that item, call
   create_return_label with resolution='refund' in the same turn — do not stop
   after eligibility with only an offer. A return label is autonomous; it does
   not require human approval.
3. If you asked the customer to choose refund vs exchange and they confirm,
   you MUST call create_return_label before your reply. Never confirm a label
   in prose without calling the tool first.
4. Do not tell the customer the return or label requires human approval. Only
   instant refunds/credits to their card without a return are blocked — a
   standard eligible return with a shipping label is fully in policy.
5. Share the RMA and carrier from the tool result once the label is created.
"""
