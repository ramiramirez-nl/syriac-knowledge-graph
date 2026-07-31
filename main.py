"""Run the Syriac Studies Network static site locally.

Usage:
    uv run main.py
    uv run main.py --port 8080 --no-browser
"""

from __future__ import annotations

import argparse
import functools
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE_DIR = ROOT / "site"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the Syriac Studies Network locally.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to use (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not SITE_DIR.is_dir():
        raise SystemExit(f"Site directory not found: {SITE_DIR}")

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(SITE_DIR))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    display_host = "localhost" if args.host in {"127.0.0.1", "0.0.0.0"} else args.host
    url = f"http://{display_host}:{server.server_port}"

    print(f"Serving {SITE_DIR}")
    print(f"Open {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
