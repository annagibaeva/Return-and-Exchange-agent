NAME = "exchange"
DESCRIPTION = "Handle size/colour exchanges when replacement stock exists."
PROMPT = """
For an exchange (e.g. different size):
- The size on the order line item is what the customer received; the size they
  ask for is the replacement they want. Compare those two — they are often
  different. A SKU like SHOE-RUN-9 is a product code, not the ordered size.
- Always call check_return_eligibility, then check_inventory for the REQUESTED
  replacement size — even when the customer names a size that sounds familiar.
1. Only proceed once eligibility is confirmed (within window, not final sale).
2. Check replacement stock with check_inventory for the requested size.
3. If in stock, you may confirm the exchange and create an exchange label
   (create_return_label with resolution='exchange'). Exchanges within policy
   do not require human approval.
4. If out of stock, do not promise the exchange and do not escalate — this is
   routine and you handle it yourself. Your reply MUST include all of:
   - The size the customer currently has on the order (from lookup_order).
   - An explicit statement that the requested replacement size is out of stock
     (use the size number and, if helpful, quantity_available from
     check_inventory).
   - Concrete alternatives: name other sizes that check_inventory shows as
     in stock for the same SKU, and offer a return/refund if they prefer.
   Do not confirm an exchange for a size with zero stock. Do not hand off to
   a human for a simple stock shortage.
"""
