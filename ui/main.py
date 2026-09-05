#!/usr/bin/env python3
from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from server import UIServer


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Task Runner local UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = UIServer(Path(__file__).resolve().parents[1], args.host, args.port)
    url = f"http://{args.host}:{server.port}/"
    print(f"AI Task Runner UI: {url}")
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
