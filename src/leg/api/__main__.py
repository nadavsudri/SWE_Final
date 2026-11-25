"""python -m leg.api [--port 8000]: the API plus the built UI (ui/dist) on one local port."""
from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from leg.api import create_app


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m leg.api")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--ui", default="ui/dist", help="built UI folder to serve at /")
    a = p.parse_args()
    ui = Path(a.ui)
    if not ui.is_dir():
        print(f"no built UI at {ui}: serving the API only (build it with: npm --prefix ui run build)")
    print(f"LEG data fetcher on http://{a.host}:{a.port}/")
    uvicorn.run(create_app(static_dir=ui), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
