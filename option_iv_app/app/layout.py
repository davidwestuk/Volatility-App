"""
app/layout.py
-------------
Defines app.layout and the empty_figure() helper.
Imports the shared Dash app instance from app_instance so that
callbacks.py registers against the same object.
"""

import plotly.graph_objects as go
from dash import dcc, html

from app.app_instance import app
from app.styles import (
    BG, PANEL, BORDER, TEXT, MUTED, ACCENT,
    input_style, label_style, divider,
)


def empty_figure(msg: str = "") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor=PANEL, plot_bgcolor=PANEL,
        font=dict(family="'IBM Plex Mono', monospace", color=TEXT),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        annotations=[dict(
            text=msg, x=0.5, y=0.5, xref="paper", yref="paper",
            showarrow=False, font=dict(size=14, color=MUTED),
        )],
        margin=dict(l=40, r=40, t=40, b=40),
    )
    return fig


app.layout = html.Div(
    style={
        "backgroundColor": BG, "minHeight": "100vh", "color": TEXT,
        "fontFamily": "'IBM Plex Mono','Courier New',monospace",
        "padding": "32px", "boxSizing": "border-box",
    },
    children=[

        # ── header ─────────────────────────────────────────────────────────────
        html.Div(
            style={
                "marginBottom": "28px",
                "borderBottom": f"1px solid {BORDER}",
                "paddingBottom": "20px",
            },
            children=[
                html.Div(
                    style={"display": "flex", "alignItems": "baseline", "gap": "12px"},
                    children=[
                        html.H1("OPT IV", style={
                            "margin": 0, "fontSize": "28px", "fontWeight": "700",
                            "color": ACCENT, "letterSpacing": "2px",
                        }),
                        html.Span("IMPLIED VOLATILITY VIEWER", style={
                            "fontSize": "11px", "color": MUTED, "letterSpacing": "3px",
                        }),
                    ],
                ),
                html.P(
                    "Bloomberg live subscription  ·  any equity or index",
                    style={"margin": "6px 0 0", "fontSize": "12px", "color": MUTED},
                ),
            ],
        ),

        # ── ticker + filter controls ────────────────────────────────────────────
        html.Div(
            style={
                "display": "flex", "alignItems": "center",
                "gap": "12px", "marginBottom": "20px", "flexWrap": "wrap",
            },
            children=[
                html.Label("Underlying", style=label_style()),
                dcc.Input(
                    id="ticker-input", type="text",
                    placeholder="e.g. SX5E Index, SPX Index, AAPL US Equity",
                    debounce=False, value="BNP FP Equity",
                    style=input_style("300px"),
                ),

                html.Div(style=divider()),

                html.Label("Source", style=label_style()),
                dcc.RadioItems(
                    id="chain-source-radio",
                    options=[
                        {"label": "Cache / Bloomberg", "value": "cache"},
                        {"label": "Bloomberg only",    "value": "bloomberg"},
                        {"label": "File",              "value": "file"},
                    ],
                    value="cache",
                    labelStyle={
                        "display": "inline-block",
                        "marginRight": "12px",
                        "fontSize": "12px",
                        "color": TEXT,
                        "cursor": "pointer",
                    },
                    inputStyle={"marginRight": "4px"},
                ),
                dcc.Input(
                    id="user-file-input", type="text",
                    placeholder="path/to/chain.csv  (File source only)",
                    debounce=False, value="",
                    style=input_style("260px"),
                ),

                html.Div(style=divider()),

                html.Label("Max expiry", style=label_style()),
                dcc.Input(
                    id="max-expiry-input", type="text",
                    placeholder="YYYY-MM-DD  (blank = all)",
                    debounce=False, value="",
                    style=input_style("160px"),
                ),

                html.Div(style=divider()),

                html.Label("Specific expiry", style=label_style()),
                dcc.Input(
                    id="specific-expiry-input", type="text",
                    placeholder="YYYY-MM-DD  (exact match)",
                    debounce=False, value="",
                    style=input_style("160px"),
                ),

                html.Div(style=divider()),

                html.Label("Strike modulus", style=label_style()),
                dcc.Input(
                    id="modulus-input", type="number",
                    placeholder="e.g. 50  (blank = all)",
                    debounce=False, min=1, value=None,
                    style=input_style("130px"),
                ),

                html.Div(style=divider()),

                html.Label("Max subscriptions", style=label_style()),
                dcc.Input(
                    id="max-subs-input", type="number",
                    placeholder="default 1000",
                    debounce=False, min=1, value=1000,
                    style=input_style("120px"),
                ),

                html.Div(style=divider()),

                html.Button(
                    "⬇  LOAD & SUBSCRIBE",
                    id="load-btn", n_clicks=0,
                    style={
                        "backgroundColor": ACCENT, "color": BG,
                        "border": "none", "borderRadius": "4px",
                        "padding": "10px 22px", "fontSize": "12px",
                        "fontFamily": "inherit", "fontWeight": "700",
                        "letterSpacing": "1.5px", "cursor": "pointer",
                    },
                ),
            ],
        ),

        # ── expiry dropdown + status ────────────────────────────────────────────
        html.Div(
            style={
                "display": "flex", "alignItems": "center",
                "gap": "16px", "marginBottom": "28px", "flexWrap": "wrap",
            },
            children=[
                html.Label("Expiry", style={**label_style(), "marginRight": "4px"}),
                dcc.Dropdown(
                    id="expiry-dropdown",
                    placeholder="Select expiry ...",
                    options=[], value=None, clearable=False,
                    style={"width": "220px", "fontSize": "13px"},
                    className="dark-dropdown",
                ),
                html.Div(
                    id="status-text",
                    style={"fontSize": "12px", "color": MUTED, "marginLeft": "4px"},
                ),
            ],
        ),

        # ── vol smile chart ─────────────────────────────────────────────────────
        html.Div(
            style={
                "backgroundColor": PANEL, "border": f"1px solid {BORDER}",
                "borderRadius": "8px", "padding": "8px", "marginBottom": "24px",
            },
            children=[dcc.Graph(
                id="vol-chart", style={"height": "480px"},
                config={"displayModeBar": True, "displaylogo": False},
                figure=empty_figure("Enter a ticker and click Load & Subscribe"),
            )],
        ),

        dcc.Interval(id="refresh-interval", interval=5_000, disabled=True),
        html.Div(id="table-container"),
        dcc.Store(id="active-ticker",    data=""),
        dcc.Store(id="subscribed-flag",  data=False),
    ],
)
