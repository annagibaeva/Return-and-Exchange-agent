NAME = "mixed_return_and_exchange"
DESCRIPTION = "Complete both a refund return and an exchange on the same order."
PROMPT = """
When the customer wants both a refund return and an exchange on the same order:
1. lookup_order → classify each line item as a refund return or an exchange.
   Returns and exchanges are separate resolutions — never combine them in one
   create_return_label call (resolution is either 'refund' or 'exchange' per SKU).
2. check_return_eligibility for each SKU; check_inventory for each exchange
   replacement size (see the return and exchange skills).
3. Two separate confirmations if needed — summarize the refund return and get
   yes, then summarize the exchange and get yes (or one combined summary if
   you listed both).
4. **Return items** → create_return_label with resolution='refund' for each
   return SKU.
5. **Exchange items** → create_return_label with resolution='exchange' for each
   exchange SKU.
6. After each yes, call the matching label tool(s) before your reply — never
   confirm a label in prose without the tool. Do not stop after only one of the
   two; every confirmed return and exchange SKU must have its own
   create_return_label in the trace before the request is complete.
"""
