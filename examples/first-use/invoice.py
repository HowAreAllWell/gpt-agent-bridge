"""Synthetic teaching fixture: intentionally incorrect invoice cents conversion.

No files, network, accounts or services are accessed. See README.md for the
acceptance contract. This baseline is expected to fail its isolated tests.
"""

from collections.abc import Iterable


def total_cents(amounts: Iterable[str]) -> int:
    """Return a total; this intentionally flawed baseline is not production code."""
    return sum(int(float(amount or "0") * 100) for amount in amounts)
