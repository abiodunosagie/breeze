"""Breeze helper: `python breeze.py serve --port 8767` (the Breeze Mac app starts this)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import secrets
import sys

from server import serve

DEFAULT_PORT = 8767


def main() -> None:
    parser = argparse.ArgumentParser(prog="breeze")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="run the helper for the Mac app")
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve_parser.add_argument("--parent-pid", type=int, help="exit when this process exits (set by the Mac app)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.parent_pid is not None and args.parent_pid <= 0:
        sys.exit("--parent-pid must be a real process id")
    token = os.environ.get("BREEZE_TOKEN")
    if not token:
        # Run by hand: make a token so the server is never open, and say what it is.
        token = secrets.token_urlsafe(24)
        print(f"Clients must send the header X-Breeze-Token: {token}", flush=True)
    try:
        asyncio.run(serve(args.port, token, args.parent_pid))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
