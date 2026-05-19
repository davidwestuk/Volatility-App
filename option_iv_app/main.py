"""
main.py
-------
Entry point.  Run with:

    python main.py

Imports layout and callbacks so their module-level code executes
(layout sets app.layout; callbacks registers @app.callback decorators).
Both modules import the shared app instance from app.app_instance.
"""

import logging

import app.layout    # noqa: F401  — sets app.layout as a side-effect
import app.callbacks # noqa: F401  — registers all @app.callback decorators

from app.app_instance import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)

if __name__ == "__main__":
    # debug=False avoids Dash's reloader forking the process, which would
    # attempt to open a second Bloomberg session.
    app.run(debug=False)
