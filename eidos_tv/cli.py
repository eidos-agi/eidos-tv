"""CLI: eidos-tv serve [--station demo] [--port 8799]"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="eidos-tv", description="Eidos TV station toolkit")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run a station HTTP server")
    s.add_argument("--station", default="demo", help="Station id under stations/")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8799)
    s.add_argument("--root", type=Path, default=None, help="Project root containing stations/")

    sub.add_parser("version", help="Print version")

    args = p.parse_args(argv)
    if args.cmd == "version":
        from eidos_tv import __version__
        print(__version__)
        return
    if args.cmd == "serve":
        os.environ["HOST"] = args.host
        os.environ["PORT"] = str(args.port)
        if args.root:
            os.environ["EIDOS_TV_ROOT"] = str(args.root.resolve())
        os.environ["EIDOS_TV_STATION"] = args.station
        from eidos_tv.server import main as serve_main
        serve_main()


if __name__ == "__main__":
    main()
