"""Input and result types for the basket solver."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SellerCertainty = Literal["direct", "marketplace", "unknown"]

# Prices that count toward a free-shipping threshold.
# Unknown is payable but excluded. Marketplace is payable and counts,
# but it is never treated as direct.
THRESHOLD_CERTAINTIES = frozenset({"direct", "marketplace"})


@dataclass(frozen=True)
class Membership:
    """Optional store membership.

    ``period`` is a label such as ``"year"`` or ``"P1Y"``. The solver does not
    interpret it; break-even is reported in orders of this basket.
    ``covers_shipping`` waives that store's shipping fee when the membership
    is applied. It does not waive the per-order fee.
    """

    price_cents: int
    period: str
    covers_shipping: bool


@dataclass(frozen=True)
class Store:
    id: str
    currency: str
    free_shipping_threshold_cents: int
    shipping_fee_cents: int
    per_order_fee_cents: int
    membership: Membership | None = None


@dataclass(frozen=True)
class Offer:
    store_id: str
    price_cents: int
    seller_certainty: SellerCertainty


@dataclass(frozen=True)
class Item:
    id: str
    offers: tuple[Offer, ...]


@dataclass(frozen=True)
class Assignment:
    item_id: str
    store_id: str
    price_cents: int
    seller_certainty: SellerCertainty


@dataclass(frozen=True)
class StoreBreakdown:
    store_id: str
    currency: str
    item_ids: tuple[str, ...]
    items_cents: int
    qualifying_cents: int
    unknown_cents: int
    threshold_cents: int
    threshold_crossed: bool
    threshold_reason: str
    shipping_cents: int
    shipping_reason: str
    per_order_fee_cents: int
    store_total_cents: int
    seller_certainties: tuple[SellerCertainty, ...]


@dataclass(frozen=True)
class SingleStoreOption:
    store_id: str
    total_cents: int
    feasible: bool
    reason: str


@dataclass(frozen=True)
class SingleStoreBaseline:
    """Cheapest way to put the whole basket in one store, no membership."""

    best_store_id: str | None
    total_cents: int | None
    per_store: tuple[SingleStoreOption, ...]


@dataclass(frozen=True)
class MembershipVerdict:
    store_id: str
    period: str
    membership_price_cents: int
    without_membership_total_cents: int
    with_membership_before_price_cents: int
    with_membership_total_cents: int
    """Positive when buying the membership makes this basket cheaper."""
    cost_difference_cents: int
    gross_savings_cents: int
    pays_for_itself: bool
    """Orders of this same basket needed to recover the membership price.
    None when this basket saves nothing, so the price is never recovered.
    """
    break_even_orders: int | None


@dataclass(frozen=True)
class Solution:
    split: tuple[Assignment, ...]
    total_cents: int
    currency: str
    needs_seller_verification: bool
    all_direct: bool
    stores: tuple[StoreBreakdown, ...]
    single_store_baseline: SingleStoreBaseline
    membership: tuple[MembershipVerdict, ...]
    """True when the headline total is the no-membership optimum."""
    membership_applied: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)
