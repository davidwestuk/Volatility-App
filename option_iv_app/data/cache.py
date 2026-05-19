"""
data/cache.py
-------------
Read, write and validate the per-ticker parquet cache.

Only static fields (ticker, strike, expiry, put_call) are persisted.
Live vol / greek fields are always populated by the Bloomberg subscription.

Cache expiry policy
-------------------
The default policy is 'daily' — the cache is valid only on the calendar day
it was written, which suits live trading sessions where the option chain
changes each morning.

The policy can be changed via CACHE_EXPIRY_POLICY, either by editing the
constant below or by setting the environment variable CACHE_EXPIRY_POLICY:

    never        — never expires; always use the cached file if it exists
    daily        — valid only on the day written (default)
    days:<N>     — valid for N calendar days from write time (e.g. "days:5")
    hourly       — valid for 1 hour from write time
    hours:<N>    — valid for N hours from write time (e.g. "hours:6")
    minutes:<N>  — valid for N minutes from write time (e.g. "minutes:30")

Environment variable example:
    CACHE_EXPIRY_POLICY=minutes:30 python main.py
    CACHE_EXPIRY_POLICY=never python main.py
"""

import logging
import os
import threading
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# ── Cache expiry policy ────────────────────────────────────────────────────────
# Edit this constant or set the CACHE_EXPIRY_POLICY environment variable.
CACHE_EXPIRY_POLICY: str = os.environ.get("CACHE_EXPIRY_POLICY", "daily")

class ChainSource(str, Enum):
    """
    Controls where the option chain static data is loaded from.

    BLOOMBERG  — always fetch from Bloomberg (ignores cache and user file)
    CACHE      — use the parquet cache if valid, fall back to Bloomberg
    FILE       — load from a user-supplied file (CSV, parquet, or Excel)
    """
    BLOOMBERG = "bloomberg"
    CACHE     = "cache"
    FILE      = "file"


_STATIC_KEYS = ("ticker", "strike", "expiry", "put_call")

_EMPTY_LIVE: dict = {
    "bid_vol": None, "mid_vol": None, "ask_vol": None,
    "opt_bid": None, "opt_mid": None, "opt_ask": None,
    "delta":   None, "vega":    None, "theta":   None,
}


def _is_expired(mtime: datetime, policy: str) -> bool:
    now = datetime.now()

    if policy == "never":
        return False

    if policy == "daily":
        return mtime.date() != date.today()

    if policy == "hourly":
        return (now - mtime) > timedelta(hours=1)

    if policy.startswith("days:"):
        try:
            days = int(policy.split(":")[1])
            if days < 1:
                raise ValueError
            return (now - mtime) > timedelta(days=days)
        except (IndexError, ValueError):
            log.warning("Invalid CACHE_EXPIRY_POLICY '%s' — falling back to 'daily'", policy)
            return mtime.date() != date.today()

    if policy.startswith("hours:"):
        try:
            hours = int(policy.split(":")[1])
            if hours < 1:
                raise ValueError
            return (now - mtime) > timedelta(hours=hours)
        except (IndexError, ValueError):
            log.warning("Invalid CACHE_EXPIRY_POLICY '%s' — falling back to 'daily'", policy)
            return mtime.date() != date.today()

    if policy.startswith("minutes:"):
        try:
            minutes = int(policy.split(":")[1])
            if minutes < 1:
                raise ValueError
            return (now - mtime) > timedelta(minutes=minutes)
        except (IndexError, ValueError):
            log.warning("Invalid CACHE_EXPIRY_POLICY '%s' — falling back to 'daily'", policy)
            return mtime.date() != date.today()

    log.warning("Unknown CACHE_EXPIRY_POLICY '%s' — falling back to 'daily'", policy)
    return mtime.date() != date.today()


def cache_valid(cache_path: Path, policy: str = CACHE_EXPIRY_POLICY) -> bool:
    if not cache_path.exists():
        return False
    mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
    if _is_expired(mtime, policy):
        log.info(
            "Cache %s written at %s is expired under policy '%s' — will refresh",
            cache_path.name, mtime.strftime("%Y-%m-%d %H:%M:%S"), policy,
        )
        return False
    log.info(
        "Cache %s is valid (policy='%s', written %s)",
        cache_path.name, policy, mtime.strftime("%Y-%m-%d %H:%M:%S"),
    )
    return True


def load_from_cache(
    cache_path: Path,
    data: dict[str, dict],
    lock: threading.Lock,
) -> None:
    df = pd.read_parquet(cache_path)
    with lock:
        for _, row in df.iterrows():
            ticker = row["ticker"]
            data[ticker] = {
                "ticker":   ticker,
                "strike":   row.get("strike"),
                "expiry":   row.get("expiry"),
                "put_call": row.get("put_call"),
                **_EMPTY_LIVE,
            }
    log.info("Cache loaded: %d options from %s", len(data), cache_path.name)


def save_cache(
    cache_path: Path,
    data: dict[str, dict],
    lock: threading.Lock,
    label: str = "",
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        rows = [
            {k: v for k, v in rec.items() if k in _STATIC_KEYS}
            for rec in data.values()
        ]
    df = pd.DataFrame(rows)
    df["expiry"] = pd.to_datetime(df["expiry"])
    df.to_parquet(cache_path, index=False)
    log.info("[%s] Cache written to %s (%d rows)", label, cache_path.name, len(df))


def load_user_file(
    file_path: Path,
    data: dict[str, dict],
    lock: threading.Lock,
) -> None:
    """
    Load a user-supplied option chain file into *data* in-place under *lock*.

    Supported formats: .parquet, .csv, .xlsx, .xls
    Required columns: ticker, strike, expiry, put_call (case-insensitive)
    """
    if not file_path.exists():
        raise FileNotFoundError(f"User file not found: {file_path}")

    suffix = file_path.suffix.lower()

    if suffix == ".parquet":
        df = pd.read_parquet(file_path)
    elif suffix == ".csv":
        df = pd.read_csv(file_path)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(file_path, sheet_name=0)
    else:
        raise ValueError(
            f"Unsupported file format '{suffix}'. "
            "Expected .parquet, .csv, .xlsx, or .xls."
        )

    df.columns = [c.strip().lower() for c in df.columns]

    missing = [c for c in _STATIC_KEYS if c not in df.columns]
    if missing:
        raise ValueError(
            f"User file is missing required columns: {missing}. "
            f"Found columns: {list(df.columns)}"
        )

    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce")
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")

    with lock:
        for _, row in df.iterrows():
            ticker = str(row["ticker"]).strip()
            data[ticker] = {
                "ticker":   ticker,
                "strike":   row.get("strike"),
                "expiry":   row.get("expiry"),
                "put_call": row.get("put_call"),
                **_EMPTY_LIVE,
            }

    log.info("User file loaded: %d options from %s", len(data), file_path.name)
