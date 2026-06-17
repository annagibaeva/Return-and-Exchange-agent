"""
tools.py — mock systems of record.

In a real deployment these would be calls to an OMS, and shipping
provider or delivery company. Here they read from local JSON so the agent's control flow — the
*sequence* of calls and how it handles their results — is the thing on display,
not the integrations themselves.

Each tool returns plain dicts. The agent decides what to call and in what
order; nothing here enforces sequencing on its own (that's the agent's job,
checked by the supervisor and the evals).

Order lookup, eligibility, and label creation accept session_customer_email
(injected by agent.py from the auth layer). Without a verified match, PII is
redacted — the guarantee is structural, not prompt-only.
"""

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"


def _identity_redacted(order_id: str) -> dict:
    """Order exists but the requester is not verified — no PII or line items."""
    return {
        "found": True,
        "order_id": order_id.strip().upper(),
        "identity_verified": False,
        "message": "Order found. Verify the requester's email before sharing details.",
    }


def _identity_verified(order: dict, session_customer_email: str | None) -> bool:
    if session_customer_email is None:
        return False
    return (
        session_customer_email.strip().lower()
        == order["customer_email"].strip().lower()
    )


@lru_cache(maxsize=None)
def _load(name):
    """Load and cache a JSON data file.

    The mock data is read-only at runtime, so caching avoids re-reading and
    re-parsing the same file on every tool call.
    """
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


def lookup_order(order_id: str, session_customer_email: str | None = None) -> dict:
    """Fetch an order by ID.

    When session_customer_email is set (from the auth layer), full order details
    are returned only if it matches the order's customer_email; otherwise a
    redacted record is returned so the agent cannot leak PII through the tool.
    """
    orders = _load("orders.json")
    oid = order_id.strip().upper()
    order = orders.get(oid)
    if not order:
        return {"found": False, "order_id": order_id}
    if not _identity_verified(order, session_customer_email):
        return _identity_redacted(oid)
    return {"found": True, "identity_verified": True, **order}


def check_return_eligibility(
    order_id: str,
    sku: str,
    policy: dict,
    session_customer_email: str | None = None,
) -> dict:
    """
    Decide whether a specific item on an order can be returned/exchanged,
    against the policy. Returns a structured verdict the agent must respect.
    """
    order = lookup_order(order_id, session_customer_email=session_customer_email)
    if not order["found"]:
        return {"eligible": False, "reason": "order_not_found"}
    if not order.get("identity_verified"):
        return {"eligible": False, "reason": "identity_not_verified"}

    item = next((i for i in order["items"] if i["sku"] == sku.strip().upper()), None)
    if not item:
        return {"eligible": False, "reason": "item_not_on_order"}

    region = order.get("region", "default")
    window = policy["return_window_days"].get(region, policy["return_window_days"]["default"])
    delivered = datetime.strptime(order["delivered_date"], "%Y-%m-%d").date()
    days_since = (date.today() - delivered).days

    if item.get("final_sale") and not policy.get("final_sale_returnable", False):
        return {
            "eligible": False,
            "reason": "final_sale",
            "days_since_delivery": days_since,
            "requires_override": "override_final_sale",
        }

    if days_since > window:
        return {
            "eligible": False,
            "reason": "outside_window",
            "days_since_delivery": days_since,
            "window_days": window,
            "region": region,
            "requires_override": "override_return_window",
        }

    return {
        "eligible": True,
        "days_since_delivery": days_since,
        "window_days": window,
        "region": region,
        "item": item,
    }


def check_inventory(sku: str, size: str) -> dict:
    """Check replacement stock for an exchange."""
    inv = _load("inventory.json").get(sku.strip().upper())
    if not inv:
        return {"in_stock": False, "reason": "sku_not_found"}
    qty = inv["variants"].get(str(size).strip(), 0)
    return {
        "in_stock": qty > 0,
        "sku": sku,
        "size": size,
        "quantity_available": qty,
        "name": inv["name"],
    }


def create_return_label(
    order_id: str,
    sku: str,
    resolution: str,
    session_customer_email: str | None = None,
) -> dict:
    """
    Generate a return/exchange label. State-changing — in production this
    would be idempotent and logged. resolution is 'refund' or 'exchange'.
    """
    order = lookup_order(order_id, session_customer_email=session_customer_email)
    if not order["found"]:
        return {"label_created": False, "reason": "order_not_found"}
    if not order.get("identity_verified"):
        return {"label_created": False, "reason": "identity_not_verified"}
    return {
        "label_created": True,
        "order_id": order_id,
        "sku": sku,
        "resolution": resolution,
        "rma": f"RMA-{order_id[-5:]}-{sku[-3:]}",
        "carrier": "ShipFast",
    }


# ---- Tool schemas exposed to Claude -------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "lookup_order",
        "description": "Look up a customer order by its order ID. Always call this first before any eligibility or label action.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "The order ID, e.g. NW-10021"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "check_return_eligibility",
        "description": "Check whether a specific item (by SKU) on an order is eligible for return or exchange under policy. Call before creating any label.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "sku": {"type": "string", "description": "The SKU of the item to check"},
            },
            "required": ["order_id", "sku"],
        },
    },
    {
        "name": "check_inventory",
        "description": "Check replacement stock for an exchange, by SKU and requested size.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "size": {"type": "string"},
            },
            "required": ["sku", "size"],
        },
    },
    {
        "name": "create_return_label",
        "description": "Create a return or exchange shipping label. Only call after eligibility is confirmed. resolution must be 'refund' or 'exchange'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "sku": {"type": "string"},
                "resolution": {"type": "string", "enum": ["refund", "exchange"]},
            },
            "required": ["order_id", "sku", "resolution"],
        },
    },
]


# Dispatch table. check_return_eligibility needs the policy injected, handled in agent.py.
TOOL_FUNCTIONS = {
    "lookup_order": lookup_order,
    "check_return_eligibility": check_return_eligibility,
    "check_inventory": check_inventory,
    "create_return_label": create_return_label,
}


if __name__ == "__main__":
    print("tools.py is a module, not a runnable script.")
    print("Run golden-set checks with: python evals/test_golden_set.py")
    raise SystemExit(1)
