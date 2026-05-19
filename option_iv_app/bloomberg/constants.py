"""
bloomberg/constants.py
----------------------
All blpapi.Name objects and field-list constants used across the app.
Defined once here so they are created only on import and never duplicated.
"""

import blpapi

# ── Subscription field names ───────────────────────────────────────────────────
BID_IV   = blpapi.Name("BID_IV")
MID_IV   = blpapi.Name("MID_IV")
ASK_IV   = blpapi.Name("ASK_IV")
STRIKE   = blpapi.Name("STRIKE_PX")
EXPIRY   = blpapi.Name("OPT_EXPIRE_DT")
PUT_CALL = blpapi.Name("OPT_PUT_CALL")
OPT_BID  = blpapi.Name("PX_BID")
OPT_MID  = blpapi.Name("PX_MID")
OPT_ASK  = blpapi.Name("PX_ASK")
DELTA    = blpapi.Name("DELTA")
VEGA     = blpapi.Name("VEGA")
THETA    = blpapi.Name("THETA")

# ── Field lists used in Bloomberg requests ─────────────────────────────────────
SUBSCRIPTION_FIELDS: list[str] = [
    "BID_IV", "MID_IV", "ASK_IV",
    "STRIKE_PX", "OPT_EXPIRE_DT", "OPT_PUT_CALL",
    "PX_BID", "PX_MID", "PX_ASK",
    "OPEN_INT", "DELTA", "VEGA", "THETA",
]

REFERENCE_FIELDS: list[str] = [
    "STRIKE_PX", "OPT_EXPIRE_DT", "OPT_PUT_CALL",
]
