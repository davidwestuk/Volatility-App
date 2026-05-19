"""
bloomberg/event_handler.py
--------------------------
Factory that returns a plain callable suitable for blpapi.Session's
eventHandler parameter.

blpapi 3.24+ passes (event, session) directly to the callable — no
base-class inheritance is required.  This avoids any dependency on
AbstractSessionEventHandler, which was removed in recent SDK versions.
"""

import queue
import logging

import blpapi
import pandas as pd

from bloomberg.constants import (
    BID_IV, MID_IV, ASK_IV, STRIKE, EXPIRY, PUT_CALL,
    OPT_BID, OPT_MID, OPT_ASK, DELTA, VEGA, THETA,
)

log = logging.getLogger(__name__)


def make_event_handler(update_queue: queue.Queue):
    """
    Return an event-handler callable bound to *update_queue*.

    Each subscription tick is parsed into a flat dict and enqueued.
    The OptionChain consumer thread merges these dicts into the live
    data store.
    """

    def _handle_data(msg) -> None:
        ticker = str(msg.correlationId().value())

        def _f(name):
            try:
                return msg.getElementAsFloat(name) if msg.hasElement(name) else None
            except Exception:
                return None

        def _s(name):
            try:
                return msg.getElementAsString(name) if msg.hasElement(name) else None
            except Exception:
                return None

        expiry_str = _s(EXPIRY)
        update_queue.put({
            "ticker":   ticker,
            "bid_vol":  _f(BID_IV),
            "mid_vol":  _f(MID_IV),
            "ask_vol":  _f(ASK_IV),
            "strike":   _f(STRIKE),
            "put_call": _s(PUT_CALL),
            "opt_bid":  _f(OPT_BID),
            "opt_mid":  _f(OPT_MID),
            "opt_ask":  _f(OPT_ASK),
            "delta":    _f(DELTA),
            "vega":     _f(VEGA),
            "theta":    _f(THETA),
            "expiry":   pd.to_datetime(expiry_str, errors="coerce")
                        if expiry_str else None,
        })

    def handler(event, session) -> None:
        etype = event.eventType()
        if etype == blpapi.Event.SUBSCRIPTION_DATA:
            for msg in event:
                _handle_data(msg)
        elif etype in (
            blpapi.Event.SUBSCRIPTION_STATUS,
            blpapi.Event.SESSION_STATUS,
            blpapi.Event.SERVICE_STATUS,
        ):
            for msg in event:
                log.info("%s", msg)

    return handler
