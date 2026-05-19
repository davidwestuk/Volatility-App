"""
app/app_instance.py
-------------------
Creates the single shared Dash application instance and the single
shared OptionChain instance.

Both layout.py and callbacks.py import from here so they operate on
the same objects without circular imports.
"""

import dash
from bloomberg.option_chain import OptionChain

app   = dash.Dash(__name__)
app.title = "Option IV Viewer"

chain = OptionChain()
