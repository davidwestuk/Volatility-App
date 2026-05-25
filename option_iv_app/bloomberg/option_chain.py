"""
bloomberg/option_chain.py
-------------------------
OptionChain — manages two blpapi sessions and a thread-safe live data store.

Two dedicated sessions are used to keep event models cleanly separate:
    _ref_session  synchronous (no eventHandler) — //blp/refdata only
                  nextEvent() called directly; safe, no EventQueue workaround.
    _mkt_session  async (eventHandler)          — //blp/mktdata only
                  subscription ticks delivered to the handler thread.

Bloomberg requests made per load() call:
    1 × ReferenceDataRequest  OPT_CHAIN         (skipped when cache is valid)
    N × ReferenceDataRequest  static fields      (skipped when cache is valid)
    1 × subscribe()           all filtered tickers (always)
"""

import queue
import threading
import logging
from datetime import date
from pathlib import Path

import blpapi
import pandas as pd

from bloomberg.constants import SUBSCRIPTION_FIELDS, REFERENCE_FIELDS
from bloomberg.event_handler import make_event_handler
from data.cache import ChainSource, cache_valid, load_from_cache, load_user_file, save_cache
from data.filters import filter_chain

log = logging.getLogger(__name__)


def ticker_to_option_data_path(ticker: str) -> Path:
    """Return the conventional optiondata_*.csv path for a given ticker."""
    filename = "optiondata_" + ticker.strip().replace(" ", "_") + ".csv"
    return Path(__file__).parent.parent / filename


class OptionChain:
    """
    Generic Bloomberg option chain loader for any equity or index.

    Usage:
        chain = OptionChain()
        chain.load("SX5E Index")   # or "SPX Index", "AAPL US Equity", ...
        chain.load("SPX Index")    # switches underlying; stops old subscription
        chain.unload()             # clean shutdown
    """

    def __init__(self, host: str = "localhost", port: int = 8194):
        self.host = host
        self.port = port

        self.underlying: str = ""
        self._cache_path: Path | None = None

        self._ref_session: blpapi.Session | None = None  # //blp/refdata, synchronous
        self._mkt_session: blpapi.Session | None = None  # //blp/mktdata, async + handler
        self._subscriptions: blpapi.SubscriptionList | None = None
        self._update_q: queue.Queue = queue.Queue()
        self._consumer_thread: threading.Thread | None = None
        self._running = False
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ── public ─────────────────────────────────────────────────────────────────

    def load(
        self,
        ticker: str,
        cache_path: Path,
        chain_source: ChainSource = ChainSource.FILE,
        user_file_path: Path | None = None,
        max_expiry: date | None = None,
        specific_expiry: date | None = None,
        strike_modulus: float | None = None,
        max_subscriptions: int | None = 1000,
        exchange: str | None = None,
    ) -> tuple[int, int, str]:
        """
        Switch to a new underlying, stopping any existing subscription first.

        Filters are applied after static chain data is resolved but before
        subscribing, so only filtered tickers consume subscription slots.

        Args:
            ticker              Bloomberg ticker, e.g. "SX5E Index"
            cache_path          Path to the parquet cache file for this ticker
            chain_source        Where to load static chain data from:
                                  ChainSource.CACHE      — parquet cache if valid,
                                                           fall back to Bloomberg
                                  ChainSource.BLOOMBERG  — always fetch from Bloomberg
                                  ChainSource.FILE       — load from user_file_path
            user_file_path      Path to a user-supplied chain file (.csv, .parquet,
                                .xlsx). Required when chain_source=FILE.
            max_expiry          Exclude options expiring after this date.
                                Ignored if specific_expiry is set.
                                For Bloomberg source: passed as CHAIN_EXPIRY_OVERRIDE.
            specific_expiry     Keep only options expiring on exactly this date.
                                For Bloomberg source: passed as CHAIN_EXP_DT_OVRD.
                                Takes precedence over max_expiry.
            strike_modulus      Keep only strikes divisible by this value
            max_subscriptions   Hard cap after other filters (default 1 000)
            exchange            Restrict chain to a single exchange via
                                CHAIN_EXCH_OVRD (Bloomberg source only).

        Returns:
            (total_in_chain, subscribed_count, source)
            source is 'bloomberg', 'cache', or 'file'
        """
        if not ticker:
            raise ValueError("Ticker cannot be empty")

        if chain_source == ChainSource.FILE and user_file_path is None:
            user_file_path = ticker_to_option_data_path(ticker)

        if self._mkt_session is not None:
            self._stop_subscription()

        self.underlying  = ticker
        self._cache_path = cache_path

        with self._lock:
            self._data.clear()
        self._update_q = queue.Queue()

        self._ensure_ref_session()
        self._ensure_mkt_session()

        if chain_source == ChainSource.FILE:
            load_user_file(user_file_path, self._data, self._lock)
            source = "file"
            log.info("[%s] Loaded from user file: %s", ticker, user_file_path)

        elif chain_source == ChainSource.BLOOMBERG or not cache_valid(cache_path):
            all_tickers = self._fetch_chain(
                max_expiry=max_expiry,
                specific_expiry=specific_expiry,
                exchange=exchange,
            )
            self._seed_static(all_tickers)
            save_cache(cache_path, self._data, self._lock, ticker)
            source = "bloomberg"
            log.info("[%s] Fetched from Bloomberg", ticker)

        else:
            load_from_cache(cache_path, self._data, self._lock)
            source = "cache"
            log.info("[%s] Loaded from cache", ticker)

        total = len(self._data)

        with self._lock:
            subscribe_tickers = filter_chain(
                self._data,
                max_expiry=max_expiry,
                specific_expiry=specific_expiry,
                strike_modulus=strike_modulus,
                max_subscriptions=max_subscriptions,
            )

        log.info(
            "[%s] Filtered %d → %d options "
            "(specific_expiry=%s, max_expiry=%s, modulus=%s, max_subs=%s)",
            ticker, total, len(subscribe_tickers),
            specific_expiry, max_expiry, strike_modulus, max_subscriptions,
        )

        self._subscribe(subscribe_tickers)
        self._start_consumer()
        return total, len(subscribe_tickers), source

    def unload(self) -> None:
        """Stop subscription, consumer thread, and both Bloomberg sessions cleanly."""
        self._stop_subscription()
        for attr in ("_mkt_session", "_ref_session"):
            sess = getattr(self, attr)
            if sess is not None:
                try:
                    sess.stop()
                except Exception:
                    pass
                setattr(self, attr, None)
        log.info("Bloomberg sessions stopped")

    @property
    def df(self) -> pd.DataFrame:
        """Thread-safe snapshot of the live data store."""
        with self._lock:
            if not self._data:
                return pd.DataFrame()
            df = pd.DataFrame(self._data.values())
        df["expiry"]    = pd.to_datetime(df["expiry"], errors="coerce")
        df["iv_spread"] = (df["ask_vol"] - df["bid_vol"]).round(4)
        return df.sort_values(["expiry", "put_call", "strike"]).reset_index(drop=True)

    @property
    def expiry_options(self) -> list[dict]:
        """Dash-ready dropdown options for all available expiries."""
        df = self.df
        if df.empty:
            return []
        expiries = df["expiry"].dropna().sort_values().unique()
        return [
            {"label": pd.Timestamp(e).strftime("%d %b %Y"), "value": str(e)}
            for e in expiries
        ]

    # ── sessions ───────────────────────────────────────────────────────────────

    def _ensure_ref_session(self) -> None:
        """Start the synchronous reference-data session (idempotent)."""
        if self._ref_session is not None:
            return
        opts = blpapi.SessionOptions()
        opts.setServerHost(self.host)
        opts.setServerPort(self.port)
        self._ref_session = blpapi.Session(opts)  # no eventHandler — sync mode
        if not self._ref_session.start():
            self._ref_session = None
            raise RuntimeError("Bloomberg ref session failed to start")
        if not self._ref_session.openService("//blp/refdata"):
            self._ref_session.stop()
            self._ref_session = None
            raise RuntimeError("Could not open //blp/refdata")
        log.info("Bloomberg ref session open")

    def _ensure_mkt_session(self) -> None:
        """Start the async market-data session (idempotent)."""
        if self._mkt_session is not None:
            return
        opts = blpapi.SessionOptions()
        opts.setServerHost(self.host)
        opts.setServerPort(self.port)
        self._mkt_session = blpapi.Session(
            opts, eventHandler=make_event_handler(self._update_q)
        )
        if not self._mkt_session.start():
            self._mkt_session = None
            raise RuntimeError("Bloomberg mkt session failed to start")
        if not self._mkt_session.openService("//blp/mktdata"):
            self._mkt_session.stop()
            self._mkt_session = None
            raise RuntimeError("Could not open //blp/mktdata")
        log.info("Bloomberg mkt session open")

    def _stop_subscription(self) -> None:
        """Unsubscribe from mkt data and stop the consumer thread.
        Both sessions remain open and are reused on the next load()."""
        self._running = False
        if self._mkt_session and self._subscriptions:
            try:
                self._mkt_session.unsubscribe(self._subscriptions)
            except Exception:
                pass
            self._subscriptions = None
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=2)

    # ── Bloomberg reference data ────────────────────────────────────────────────

    def _fetch_chain(
        self,
        max_expiry: date | None = None,
        specific_expiry: date | None = None,
        exchange: str | None = None,
    ) -> list[str]:
        """
        One ReferenceDataRequest → list of option tickers via CHAIN_TICKERS.

        CHAIN_TICKERS (unlike OPT_CHAIN) honours expiry overrides server-side:
            specific_expiry  → CHAIN_EXP_DT_OVRD    (exact single expiry)
            max_expiry       → CHAIN_EXPIRY_OVERRIDE  (on or before this date)

        specific_expiry takes precedence; when it is set, max_expiry is ignored
        here because Bloomberg will already return only that one expiry.

        CHAIN_POINTS_OVRD is always set to 3000 to raise Bloomberg's default
        cap on the number of tickers returned (typically 500).
        """
        svc     = self._ref_session.getService("//blp/refdata")
        request = svc.createRequest("ReferenceDataRequest")
        request.getElement("securities").appendValue(self.underlying)
        request.getElement("fields").appendValue("CHAIN_TICKERS")
        overrides = request.getElement("overrides")

        def _add_override(field_id: str, value: str) -> None:
            o = overrides.appendElement()
            o.setElement("fieldId", field_id)
            o.setElement("value", value)

        _add_override("CHAIN_POINTS_OVRD", "3000")

        if exchange:
            _add_override("CHAIN_EXCH_OVRD", exchange.strip().upper())
            log.info("[%s] CHAIN_EXCH_OVRD=%s", self.underlying, exchange.strip().upper())

        if specific_expiry is not None:
            _add_override("CHAIN_EXP_DT_OVRD", specific_expiry.strftime("%Y%m%d"))
            log.info("[%s] CHAIN_EXP_DT_OVRD=%s", self.underlying, specific_expiry)
        elif max_expiry is not None:
            _add_override("CHAIN_EXPIRY_OVERRIDE", max_expiry.strftime("%Y%m%d"))
            log.info("[%s] CHAIN_EXPIRY_OVERRIDE=%s", self.underlying, max_expiry)

        self._ref_session.sendRequest(request)

        tickers: list[str] = []
        while True:
            event = self._ref_session.nextEvent(timeout=5000)
            for msg in event:
                if msg.hasElement("securityData"):
                    sd = msg.getElement("securityData").getValueAsElement(0)
                    fd = sd.getElement("fieldData")
                    if fd.hasElement("CHAIN_TICKERS"):
                        arr = fd.getElement("CHAIN_TICKERS")
                        for i in range(arr.numValues()):
                            tickers.append(arr.getValueAsString(i).strip())
            if event.eventType() == blpapi.Event.RESPONSE:
                break

        if not tickers:
            raise ValueError(
                f"No option chain returned for '{self.underlying}'. "
                "Check the ticker format (e.g. 'SX5E Index', 'AAPL US Equity')."
            )
        return tickers

    def _seed_static(self, tickers: list[str], chunk_size: int = 200) -> None:
        """Bulk ReferenceDataRequest for static fields, populates self._data."""
        svc = self._ref_session.getService("//blp/refdata")
        for i in range(0, len(tickers), chunk_size):
            chunk   = tickers[i : i + chunk_size]
            request = svc.createRequest("ReferenceDataRequest")
            for t in chunk:
                request.getElement("securities").appendValue(t)
            for f in REFERENCE_FIELDS:
                request.getElement("fields").appendValue(f)
            self._ref_session.sendRequest(request)

            while True:
                event = self._ref_session.nextEvent(timeout=5000)
                for msg in event:
                    if not msg.hasElement("securityData"):
                        continue
                    sec_arr = msg.getElement("securityData")
                    for j in range(sec_arr.numValues()):
                        sec        = sec_arr.getValueAsElement(j)
                        ticker     = sec.getElementAsString("security")
                        fd         = sec.getElement("fieldData")
                        expiry_str = (
                            fd.getElementAsString("OPT_EXPIRE_DT")
                            if fd.hasElement("OPT_EXPIRE_DT") else None
                        )
                        with self._lock:
                            self._data[ticker] = {
                                "ticker":   ticker,
                                "strike":   fd.getElementAsFloat("STRIKE_PX")
                                            if fd.hasElement("STRIKE_PX") else None,
                                "expiry":   pd.to_datetime(expiry_str, errors="coerce")
                                            if expiry_str else None,
                                "put_call": fd.getElementAsString("OPT_PUT_CALL")
                                            if fd.hasElement("OPT_PUT_CALL") else None,
                                "bid_vol": None, "mid_vol": None, "ask_vol": None,
                                "opt_bid": None, "opt_mid": None, "opt_ask": None,
                                "delta":   None, "vega":    None, "theta":   None,
                            }
                if event.eventType() == blpapi.Event.RESPONSE:
                    break

    # ── subscription ───────────────────────────────────────────────────────────

    def _subscribe(self, tickers: list[str]) -> None:
        self._subscriptions = blpapi.SubscriptionList()
        for ticker in tickers:
            self._subscriptions.add(
                topic=ticker,
                fields=SUBSCRIPTION_FIELDS,
                correlationId=blpapi.CorrelationId(ticker),
            )
        self._mkt_session.subscribe(self._subscriptions)
        log.info("[%s] Subscribed to %d options", self.underlying, len(tickers))

    def _start_consumer(self) -> None:
        """Drain the update queue into self._data in a background thread."""
        self._running = True

        def _run():
            while self._running:
                try:
                    rec    = self._update_q.get(timeout=0.5)
                    ticker = rec["ticker"]
                    with self._lock:
                        if ticker in self._data:
                            self._data[ticker].update(
                                {k: v for k, v in rec.items() if v is not None}
                            )
                        else:
                            self._data[ticker] = rec
                except queue.Empty:
                    continue

        self._consumer_thread = threading.Thread(target=_run, daemon=True)
        self._consumer_thread.start()
