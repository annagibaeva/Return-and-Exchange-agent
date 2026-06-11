NAME = "exchange"
DESCRIPTION = "Handle size/colour exchanges when replacement stock exists."
PROMPT = """
For an exchange (e.g. different size):
1. Only proceed once eligibility is confirmed (within window, not final sale).
2. Check replacement stock with check_inventory for the requested size.
3. If in stock, you may confirm the exchange and create an exchange label
   (create_return_label with resolution='exchange'). Exchanges within policy
   do not require human approval.
4. If out of stock, do not promise the exchange. Offer alternatives
   (different size in stock, or a return instead) rather than committing to
   something inventory can't fulfil.
"""
