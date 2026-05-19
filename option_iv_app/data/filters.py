"""
data/filters.py
---------------
filter_chain() — reduces the set of option tickers before subscribing.

No Bloomberg or Dash dependency; pure Python + pandas for easy unit testing.
"""

import logging
from datetime import date

import pandas as pd

log = logging.getLogger(__name__)


def filter_chain(
    static_data: dict[str, dict],
    max_expiry: date | None = None,
    specific_expiry: date | None = None,
    strike_modulus: float | None = None,
    max_subscriptions: int | None = 1000,
) -> list[str]:
    """
    Return the subset of tickers from *static_data* that pass all filters.

    Filters are applied in order; max_subscriptions is the final hard cap.

    Args:
        static_data         Dict keyed by ticker, each value contains at least
                            'expiry' (Timestamp | None) and 'strike' (float | None).
        max_expiry          Drop options expiring after this date.
                            Ignored if specific_expiry is set.
        specific_expiry     Keep only options expiring on exactly this date.
                            Takes precedence over max_expiry if both are provided.
        strike_modulus      Keep only strikes where round(strike % modulus) == 0.
                            e.g. modulus=50 keeps 4800, 4850 ... and drops 4825.
        max_subscriptions   Hard cap on returned tickers. Options are sorted by
                            expiry then strike before truncating so that the
                            nearest expiries are always preferred.
                            Default 1 000; pass None for no cap.

    Returns:
        List of ticker strings that passed all filters.
    """
    kept: list[str] = []

    for ticker, rec in static_data.items():
        expiry = rec.get("expiry")
        strike = rec.get("strike")

        if expiry is not None:
            exp_date = expiry.date() if hasattr(expiry, "date") else expiry

            if specific_expiry is not None:
                if exp_date != specific_expiry:
                    continue
            elif max_expiry is not None:
                if exp_date > max_expiry:
                    continue

        if strike_modulus is not None and strike is not None:
            if round(strike % strike_modulus) != 0:
                continue

        kept.append(ticker)

    if max_subscriptions is not None and len(kept) > max_subscriptions:
        def _sort_key(t: str):
            rec    = static_data[t]
            expiry = rec.get("expiry") or pd.Timestamp.max
            strike = rec.get("strike") or 0.0
            return (expiry, strike)

        kept.sort(key=_sort_key)
        kept = kept[:max_subscriptions]
        log.info("Capped to %d subscriptions", max_subscriptions)

    return kept
