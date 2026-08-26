"""Entry point used by the double-click launcher.

Kept separate from `app.server` so the launcher can pass a port and still let
`python -m app.server` work on its own.
"""

from __future__ import annotations

import argparse

from app.server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local mlev web app.")
    parser.add_argument("--port", type=int, default=8733)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--lan", action="store_true",
        help="Also listen on the local network so a phone can connect.",
    )
    args = parser.parse_args()
    serve(
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        lan=args.lan,
    )


if __name__ == "__main__":
    main()
