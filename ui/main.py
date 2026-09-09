#!/usr/bin/env python3
from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

try:
    from .server import UIServer
except ImportError:
    from server import UIServer


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Task Runner local UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--allow-remote", action="store_true", help="Allow binding the unauthenticated local UI to a non-loopback address")
    args = parser.parse_args()

    server = UIServer(Path(__file__).resolve().parents[1], args.host, args.port, allow_remote=args.allow_remote)
    url = f"http://{args.host}:{server.port}/"
    print(f"AI Task Runner UI: {url}")
    if args.allow_remote and args.host not in {"127.0.0.1", "::1", "localhost"}:
        print("WARNING: remote UI binding is enabled; expose it only on a trusted network.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
