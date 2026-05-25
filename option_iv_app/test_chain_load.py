"""
test_chain_load.py
------------------
Standalone smoke-test for Bloomberg option chain loading.
Run from the option_iv_app/ directory.

No Dash dependency — purely tests the bloomberg/ and data/ layers.
"""

import argparse
import logging
import re
from datetime import date
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)

CACHE_DIR = Path("option_chain_cache")
CACHE_DIR.mkdir(exist_ok=True)


def ticker_to_cache_path(ticker: str) -> Path:
    safe = re.sub(r"[^\w]", "_", ticker.strip())
    return CACHE_DIR / f"{safe}.parquet"


def print_summary(ticker, total, subscribed, source,
                  max_expiry, specific_expiry, strike_modulus, max_subscriptions):
    print(f"\n{'─' * 60}")
    print(f"  Ticker            : {ticker}")
    print(f"  Source            : {source}")
    print(f"  Total in chain    : {total:,}")
    print(f"  Subscribed        : {subscribed:,}")
    print(f"  Specific expiry   : {specific_expiry or '—'}")
    print(f"  Max expiry        : {max_expiry or '—'}")
    print(f"  Strike modulus    : {strike_modulus or '—'}")
    print(f"  Max subs cap      : {max_subscriptions:,}")
    print(f"{'─' * 60}\n")


def print_chain_snapshot(chain):
    import pandas as pd
    df = chain.df
    if df.empty:
        print("No data received — check your Bloomberg connection.")
        return

    filled = df["mid_vol"].notna().sum()
    print(f"Rows with mid_vol populated : {filled:,} / {len(df):,}")
    print(f"\nExpiries available ({df['expiry'].nunique()}):")
    for exp, grp in df.groupby("expiry"):
        n_calls = (grp["put_call"] == "Call").sum()
        n_puts  = (grp["put_call"] == "Put").sum()
        iv_ok   = grp["mid_vol"].notna().sum()
        print(f"  {pd.Timestamp(exp).strftime('%d %b %Y')}  "
              f"calls={n_calls}  puts={n_puts}  iv_populated={iv_ok}")

    first_expiry = df["expiry"].dropna().min()
    sample = (
        df[df["expiry"] == first_expiry]
        [["put_call", "strike", "bid_vol", "mid_vol", "ask_vol", "delta"]]
        .head(10)
    )
    print(f"\nSample rows for {pd.Timestamp(first_expiry).strftime('%d %b %Y')}:")
    print(sample.to_string(index=False))


def run(ticker, source_str, user_file, max_expiry, specific_expiry,
        strike_modulus, max_subscriptions, listen_seconds):
    from bloomberg.option_chain import OptionChain, ticker_to_option_data_path
    from data.cache import ChainSource

    try:
        chain_source = ChainSource(source_str)
    except ValueError:
        log.error("Invalid source '%s'. Choose: cache, bloomberg, file", source_str)
        return

    # Auto-derive file path when not explicitly supplied.
    if chain_source == ChainSource.FILE and user_file is None:
        user_file = ticker_to_option_data_path(ticker)
        log.info("Auto-derived file path: %s", user_file)

    chain = OptionChain()

    log.info("Loading chain for: %s  (source=%s)", ticker, chain_source.value)
    total, subscribed, source = chain.load(
        ticker,
        cache_path=ticker_to_cache_path(ticker),
        chain_source=chain_source,
        user_file_path=user_file,
        max_expiry=max_expiry,
        specific_expiry=specific_expiry,
        strike_modulus=strike_modulus,
        max_subscriptions=max_subscriptions,
    )

    print_summary(ticker, total, subscribed, source,
                  max_expiry, specific_expiry, strike_modulus, max_subscriptions)

    if chain_source == ChainSource.FILE:
        import pandas as pd
        df = chain.df
        if df.empty:
            print("No data loaded from file.")
        else:
            print(f"Loaded {len(df):,} options from file.\n")
            display_cols = [c for c in
                            ["put_call", "exercise_style", "strike", "expiry",
                             "exchange", "ticker"]
                            if c in df.columns]
            print(df[display_cols].head(10).to_string(index=False))
    else:
        import time
        print(f"Listening for {listen_seconds}s for live ticks ...", flush=True)
        time.sleep(listen_seconds)
        print_chain_snapshot(chain)

    chain.unload()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Bloomberg option chain loading")
    parser.add_argument("--ticker",          default="BNP FP Equity")
    parser.add_argument("--source",          default="file",
                        choices=["cache", "bloomberg", "file"])
    parser.add_argument("--user-file",       default=None)
    parser.add_argument("--specific-expiry", default=None)
    parser.add_argument("--max-expiry",      default=None)
    parser.add_argument("--modulus",         type=float, default=None)
    parser.add_argument("--max-subs",        type=int, default=1000)
    parser.add_argument("--listen",          type=int, default=10)
    args = parser.parse_args()

    run(
        ticker=args.ticker,
        source_str=args.source,
        user_file=Path(args.user_file) if args.user_file else None,
        max_expiry=date.fromisoformat(args.max_expiry) if args.max_expiry else None,
        specific_expiry=date.fromisoformat(args.specific_expiry) if args.specific_expiry else None,
        strike_modulus=args.modulus,
        max_subscriptions=args.max_subs,
        listen_seconds=args.listen,
    )
