"""
app/styles.py
-------------
Colour palette and reusable style dicts for the Dash layout and table.
"""

# ── Colour palette ─────────────────────────────────────────────────────────────
BG     = "#0d1117"
PANEL  = "#161b22"
BORDER = "#30363d"
TEXT   = "#e6edf3"
MUTED  = "#8b949e"
ACCENT = "#58a6ff"
GREEN  = "#3fb950"
RED    = "#f85149"

# ── Reusable table cell styles ─────────────────────────────────────────────────
TABLE_HEADER: dict = {
    "backgroundColor": BG,
    "color": MUTED,
    "fontSize": "11px",
    "fontWeight": "700",
    "letterSpacing": "1px",
    "padding": "8px 12px",
    "borderBottom": f"1px solid {BORDER}",
    "textAlign": "right",
}

TABLE_CELL: dict = {
    "fontSize": "12px",
    "padding": "6px 12px",
    "borderBottom": f"1px solid {BORDER}",
    "textAlign": "right",
}

# ── Shared input style ─────────────────────────────────────────────────────────
def input_style(width: str = "160px") -> dict:
    return {
        "width": width,
        "backgroundColor": PANEL,
        "border": f"1px solid {BORDER}",
        "borderRadius": "4px",
        "color": TEXT,
        "fontFamily": "inherit",
        "fontSize": "13px",
        "padding": "9px 12px",
        "outline": "none",
    }


def label_style() -> dict:
    return {
        "fontSize": "11px",
        "color": MUTED,
        "letterSpacing": "1px",
        "fontWeight": "700",
    }


def divider() -> dict:
    """Vertical rule between control groups."""
    return {"width": "1px", "height": "32px", "backgroundColor": BORDER, "margin": "0 4px"}
