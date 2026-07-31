"""Run the Syriac Studies Network app (FastAPI + static site) locally.

Usage:
    uv run main.py
    uv run main.py --port 8080 --no-browser
    uv run main.py --reload          # auto-restart on code changes (development)
"""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Syriac Studies Network app locally.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to use (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (development)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    display_host = "localhost" if args.host in {"127.0.0.1", "0.0.0.0"} else args.host
    url = f"http://{display_host}:{args.port}"

    print(f"Serving the Syriac Studies Network app (API + site) from {ROOT}")
    print(f"Open {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(ROOT),
    )


if __name__ == "__main__":
    main()
