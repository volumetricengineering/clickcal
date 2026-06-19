"""Run the clickcal HTTP server.

Usage:
    python -m clickcal            # serve on 0.0.0.0:8000
    CLICKCAL_PORT=9000 python -m clickcal
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("CLICKCAL_HOST", "0.0.0.0")
    port = int(os.environ.get("CLICKCAL_PORT", "8000"))
    uvicorn.run("clickcal.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
