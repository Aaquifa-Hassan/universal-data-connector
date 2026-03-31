"""
Business Rules Engine
=====================
Simple, readable rules that determine how customer issues are resolved.
These rules are used by the mock API server to decide the outcome of
product expiry/damage checks and ticket priority.
"""

from typing import List, Dict, Any


# ── Resolution Rules ───────────────────────────────────────────────────────────

# Products in these categories always get a refund (perishable / health risk)
REFUND_CATEGORIES = {"food", "pharma", "grocery", "dairy", "beverage"}

# Products in these categories get exchanged (durable goods)
EXCHANGE_CATEGORIES = {"electronics", "appliances", "gadgets", "hardware"}

# Maximum days since purchase to be eligible for any resolution
MAX_ELIGIBLE_DAYS = 90


def decide_resolution(
    category: str,
    days_since_purchase: int,
    customer_segment: str = "Standard",
) -> Dict[str, str]:
    """
    Decide whether a customer gets a refund, exchange, or rejection.

    Rules (in order of priority):
    1. If purchased > 90 days ago → reject (too old)
    2. Premium customers get +30 days grace period
    3. Food / pharma / grocery → refund
    4. Electronics / appliances / gadgets → exchange
    5. Anything else → refund (safe default)

    Returns:
        {"resolution": "refund" | "exchange" | "reject", "reason": str}
    """
    limit = MAX_ELIGIBLE_DAYS
    if customer_segment == "Premium":
        limit += 30  # Premium customers get 120-day window

    if days_since_purchase > limit:
        return {
            "resolution": "reject",
            "reason": f"Purchase is over {limit} days old — outside the eligible window.",
        }

    cat = category.lower().strip()

    if cat in REFUND_CATEGORIES:
        return {
            "resolution": "refund",
            "reason": "Perishable or health product — refund policy applies.",
        }

    if cat in EXCHANGE_CATEGORIES:
        return {
            "resolution": "exchange",
            "reason": "Durable product — replacement/exchange policy applies.",
        }

    # Safe default for unknown categories
    return {
        "resolution": "refund",
        "reason": "Standard refund policy.",
    }


# ── Ticket Priority Rules ─────────────────────────────────────business_rules─────────────────

def get_ticket_priority(customer_segment: str) -> int:
    """
    Decide the priority for a new support ticket based on customer segment.

    Priority levels (Freshdesk convention):
        1 = urgent  |  2 = high  |  3 = medium  |  4 = low

    Rules:
    - Premium  → high (2)
    - Standard → medium (3)
    - Basic    → medium (3)
    """
    if customer_segment == "Premium":
        return 2  # high
    return 3      # medium


# ── Voice Utility ──────────────────────────────────────────────────────────────

def apply_voice_limits(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Limit results to 3 items — prevents overwhelming TTS output."""
    return data[:3]
