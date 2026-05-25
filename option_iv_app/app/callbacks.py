"""
app/callbacks.py
----------------
All Dash @app.callback functions.

Imports the shared app and chain instances from app_instance so that
decorators register against the same Dash server that layout.py uses.
"""

import logging
from datetime import datetime, date
from pathlib import Path
import re

import dash
from dash import dcc, html, Input, Output, State
import pandas as pd
import plotly.graph_objects as go

from app.app_instance import app, chain
from data.cache import ChainSource
from app.layout import empty_figure
from app.styles import (
    BG, PANEL, BORDER, TEXT, MUTED, ACCENT, GREEN,
    TABLE_HEADER, TABLE_CELL,
)

log = logging.getLogger(__name__)

CACHE_DIR = Path("option_chain_cache")
CACHE_DIR.mkdir(exist_ok=True)


def _normalise_ticker(raw: str) -> str:
    return " ".join(raw.strip().upper().split())


def _ticker_to_cache_path(ticker: str) -> Path:
    safe = re.sub(r"[^\w]", "_", ticker.strip())
    return CACHE_DIR / f"{safe}.parquet"


@app.callback(
    Output("subscribed-flag",  "data"),
    Output("active-ticker",    "data"),
    Output("expiry-dropdown",  "options"),
    Output("expiry-dropdown",  "value"),
    Output("status-text",      "children"),
    Output("refresh-interval", "disabled"),
    Input("load-btn",              "n_clicks"),
    State("ticker-input",          "value"),
    State("chain-source-radio",    "value"),
    State("user-file-input",       "value"),
    State("max-expiry-input",      "value"),
    State("specific-expiry-input", "value"),
    State("modulus-input",         "value"),
    State("max-subs-input",        "value"),
    State("exchange-input",        "value"),
    prevent_initial_call=True,
)
def load_and_subscribe(n_clicks, raw_ticker, chain_source_val, user_file_val,
                       max_expiry_str, specific_expiry_str, modulus_val,
                       max_subs_val, exchange_val):
    if not raw_ticker or not raw_ticker.strip():
        return False, "", [], None, "✗  Please enter a ticker", True

    ticker = _normalise_ticker(raw_ticker)

    try:
        chain_source = ChainSource(chain_source_val or "cache")
    except ValueError:
        chain_source = ChainSource.CACHE

    user_file_path = None
    if chain_source == ChainSource.FILE and user_file_val and user_file_val.strip():
        user_file_path = Path(user_file_val.strip())
    # If user_file_path is None and source is FILE, load() auto-derives the path
    # from the ticker: optiondata_{ticker}.csv in the working directory.

    max_expiry: date | None = None
    if max_expiry_str and max_expiry_str.strip():
        try:
            max_expiry = date.fromisoformat(max_expiry_str.strip())
        except ValueError:
            return False, "", [], None, "✗  Max expiry must be YYYY-MM-DD", True

    specific_expiry: date | None = None
    if specific_expiry_str and specific_expiry_str.strip():
        try:
            specific_expiry = date.fromisoformat(specific_expiry_str.strip())
        except ValueError:
            return False, "", [], None, "✗  Specific expiry must be YYYY-MM-DD", True

    strike_modulus: float | None = None
    if modulus_val is not None:
        try:
            strike_modulus = float(modulus_val)
            if strike_modulus <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return False, "", [], None, "✗  Strike modulus must be a positive number", True

    max_subscriptions: int | None = 1000
    if max_subs_val is not None:
        try:
            max_subscriptions = int(max_subs_val)
            if max_subscriptions < 1:
                raise ValueError
        except (ValueError, TypeError):
            return False, "", [], None, "✗  Max subscriptions must be a positive integer", True

    exchange: str | None = exchange_val.strip().upper() if exchange_val and exchange_val.strip() else None

    try:
        total, subscribed, source = chain.load(
            ticker,
            cache_path=_ticker_to_cache_path(ticker),
            chain_source=chain_source,
            user_file_path=user_file_path,
            max_expiry=max_expiry,
            specific_expiry=specific_expiry,
            strike_modulus=strike_modulus,
            max_subscriptions=max_subscriptions,
            exchange=exchange,
        )
        options   = chain.expiry_options
        first     = options[0]["value"] if options else None
        src_label = {"cache": "📁 cache", "bloomberg": "🌐 Bloomberg",
                     "file": "📂 file"}.get(source, source)

        filter_parts = []
        if specific_expiry:
            filter_parts.append(f"expiry = {specific_expiry}")
        elif max_expiry:
            filter_parts.append(f"exp ≤ {max_expiry}")
        if strike_modulus:
            filter_parts.append(f"mod {strike_modulus:g}")
        if max_subscriptions:
            filter_parts.append(f"cap {max_subscriptions:,}")
        if exchange:
            filter_parts.append(f"exch {exchange}")
        filter_str = "  ·  " + "  ·  ".join(filter_parts) if filter_parts else ""

        status = (
            f"✓  {ticker}  ·  {total:,} in chain  →  {subscribed:,} subscribed"
            f"{filter_str}  ·  {src_label}  ·  live every 5 s"
        )
        return True, ticker, options, first, status, False

    except Exception as exc:
        log.exception("load failed for %s", ticker)
        return False, "", [], None, f"✗  {exc}", True


@app.callback(
    Output("expiry-dropdown", "options", allow_duplicate=True),
    Input("refresh-interval", "n_intervals"),
    State("subscribed-flag",  "data"),
    prevent_initial_call=True,
)
def refresh_expiries(_, subscribed):
    if not subscribed:
        raise dash.exceptions.PreventUpdate
    return chain.expiry_options


@app.callback(
    Output("vol-chart",       "figure"),
    Output("table-container", "children"),
    Input("expiry-dropdown",  "value"),
    Input("refresh-interval", "n_intervals"),
    State("subscribed-flag",  "data"),
    State("active-ticker",    "data"),
    prevent_initial_call=True,
)
def update_chart(expiry_str, _, subscribed, active_ticker):
    if not subscribed or not expiry_str:
        return empty_figure("Select an expiry"), html.Div()

    df_all = chain.df
    if df_all.empty:
        return empty_figure("Waiting for data ..."), html.Div()

    expiry = pd.to_datetime(expiry_str)
    sub    = df_all[df_all["expiry"] == expiry].copy()
    if sub.empty:
        return empty_figure("No data for selected expiry"), html.Div()

    calls = sub[sub["put_call"] == "Call"].sort_values("strike")
    puts  = sub[sub["put_call"] == "Put"].sort_values("strike")
    fig   = go.Figure()

    for frame, color, name in [(calls, ACCENT, "Call"), (puts, GREEN, "Put")]:
        valid = frame.dropna(subset=["mid_vol"])
        if valid.empty:
            continue
        fig.add_trace(go.Scatter(
            x=pd.concat([valid["strike"], valid["strike"].iloc[::-1]]),
            y=pd.concat([valid["ask_vol"], valid["bid_vol"].iloc[::-1]]),
            fill="toself", fillcolor=color + "1a",
            line=dict(width=0), showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=valid["strike"], y=valid["mid_vol"],
            mode="lines+markers", name=f"{name} Mid Vol",
            line=dict(color=color, width=2), marker=dict(size=5),
            customdata=valid[["bid_vol", "ask_vol", "delta"]].values,
            hovertemplate=(
                f"<b>{name}</b><br>Strike: %{{x:.0f}}<br>"
                "Mid Vol: %{y:.2%}<br>Bid Vol: %{customdata[0]:.2%}<br>"
                "Ask Vol: %{customdata[1]:.2%}<br>Delta: %{customdata[2]:.3f}"
                "<extra></extra>"
            ),
        ))

    fig.update_layout(
        title=dict(
            text=(
                f"{active_ticker}  ·  Vol Smile  ·  "
                f"{expiry.strftime('%d %b %Y')}  ·  "
                f"{datetime.now().strftime('%H:%M:%S')}"
            ),
            font=dict(size=14, color=TEXT), x=0.02,
        ),
        paper_bgcolor=PANEL, plot_bgcolor=PANEL,
        font=dict(family="'IBM Plex Mono', monospace", color=TEXT, size=11),
        xaxis=dict(title="Strike", gridcolor=BORDER, zeroline=False, tickformat=","),
        yaxis=dict(title="Implied Vol", gridcolor=BORDER, zeroline=False,
                   tickformat=".0%"),
        legend=dict(bgcolor=BG, bordercolor=BORDER, borderwidth=1, font=dict(size=11)),
        hovermode="x unified",
        margin=dict(l=60, r=40, t=60, b=60),
    )

    tbl = sub[["put_call", "strike", "bid_vol", "mid_vol", "ask_vol",
               "iv_spread", "delta", "vega", "theta"]].copy()

    for col in ["bid_vol", "mid_vol", "ask_vol", "iv_spread"]:
        tbl[col] = tbl[col].map(lambda v: f"{v:.2%}" if pd.notna(v) else "—")
    for col in ["delta", "vega", "theta"]:
        tbl[col] = tbl[col].map(lambda v: f"{v:.4f}" if pd.notna(v) else "—")
    tbl["strike"] = tbl["strike"].map(lambda v: f"{v:,.0f}" if pd.notna(v) else "—")

    tbl = tbl.rename(columns={
        "put_call": "Type", "strike": "Strike",
        "bid_vol": "Bid Vol", "mid_vol": "Mid Vol", "ask_vol": "Ask Vol",
        "iv_spread": "IV Spread", "delta": "Delta", "vega": "Vega", "theta": "Theta",
    })

    table = html.Div(
        style={
            "backgroundColor": PANEL, "border": f"1px solid {BORDER}",
            "borderRadius": "8px", "overflow": "auto", "maxHeight": "360px",
        },
        children=[html.Table(
            style={"width": "100%", "borderCollapse": "collapse"},
            children=[
                html.Thead(html.Tr([
                    html.Th(c, style=TABLE_HEADER) for c in tbl.columns
                ])),
                html.Tbody([
                    html.Tr(
                        style={"backgroundColor": ACCENT + "0d"
                               if row["Type"] == "Call" else GREEN + "0d"},
                        children=[html.Td(row[c], style={
                            **TABLE_CELL,
                            "color": (
                                ACCENT if c == "Type" and row["Type"] == "Call"
                                else GREEN if c == "Type"
                                else TEXT
                            ),
                            "fontWeight": "600" if c == "Type" else "400",
                        }) for c in tbl.columns],
                    )
                    for _, row in tbl.iterrows()
                ]),
            ],
        )],
    )

    return fig, table
