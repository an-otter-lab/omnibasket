"""Deterministic basket splitter.

Monetary amounts are integer minor units (cents). The optimiser enumerates
every feasible assignment of items to stores, so totals are exact and
reproducible from the inputs.
"""

from solver.optimize import ROMANIAN_STORE_IDS, SolverError, solve, store_if_fees_resolved
from solver.types import Item, Membership, Offer, Solution, Store

__all__ = [
    "Item",
    "Membership",
    "Offer",
    "ROMANIAN_STORE_IDS",
    "Solution",
    "SolverError",
    "Store",
    "solve",
    "store_if_fees_resolved",
]
