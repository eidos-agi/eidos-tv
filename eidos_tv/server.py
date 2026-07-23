"""Generic eidos-tv HTTP server.

Serves light/dark themes, QR deep-links for insights, and /api/board from a
station provider module.

Station layout (EIDOS_TV_ROOT/stations/<id>/):
  provider.py   — must define fetch_board() -> dict
  station.json  — brand, publicBase, optional segments
  static/       — optional overrides
  data/         — progress/insights/week artifacts
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8799"))
PKG = Path(__file__).resolve().parent
DEFAULT_STATIC = PKG / "static"
ROOT = Path(os.environ.get("EIDOS_TV_ROOT", Path.cwd()))
STATION_ID = os.environ.get("EIDOS_TV_STATION", "demo")
CACHE_TTL = int(os.environ.get("TV_CACHE_TTL", "60"))

_cache: dict = {"t": 0.0, "payload": None}


def station_dir() -> Path:
    # prefer local stations/, then package-relative ../../stations
    candidates = [
        ROOT / "stations" / STATION_ID,
        PKG.parent / "stations" / STATION_ID,
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def load_station_config() -> dict:
    p = station_dir() / "station.json"
    if p.is_file():
        return json.loads(p.read_text())
    return {
        "id": STATION_ID,
        "brand": "EIDOS",
        "brandSub": "STATION · TV",
        "publicBase": f"http://{HOST}:{PORT}",
    }


def load_provider():
    path = station_dir() / "provider.py"
    if not path.is_file():
        raise FileNotFoundError(f"No provider.py in {station_dir()}")
    spec = importlib.util.spec_from_file_location(f"station_{STATION_ID}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    if not hasattr(mod, "fetch_board"):
        raise RuntimeError("provider.py must define fetch_board() -> dict")
    return mod


def board_payload() -> dict:
    now = time.time()
    if _cache["payload"] is not None and (now - _cache["t"]) < CACHE_TTL:
        return _cache["payload"]
    cfg = load_station_config()
    mod = load_provider()
    body = mod.fetch_board()
    body.setdefault("bug", cfg.get("brand", "EIDOS TV"))
    body.setdefault("generated_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    body["station"] = cfg
    # optional insights file
    ins = station_dir() / "data" / "insights.json"
    if ins.is_file() and "insights" not in body:
        try:
            body["insights"] = json.loads(ins.read_text())
        except Exception:
            pass
    week = station_dir() / "data" / "week.json"
    if week.is_file() and "week" not in body:
        try:
            body["week"] = json.loads(week.read_text())
        except Exception:
            pass
    _cache.update(t=now, payload=body)
    return body


def get_insight(iid: str) -> dict | None:
    body = board_payload()
    doc = body.get("insights") or {}
    for ins in doc.get("insights") or []:
        if ins.get("id") == iid:
            return ins
    # file fallback
    path = station_dir() / "data" / "insights.json"
    if path.is_file():
        doc = json.loads(path.read_text())
        for ins in doc.get("insights") or []:
            if ins.get("id") == iid:
                return ins
    return None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        # prefer station static, else package board
        static = station_dir() / "static"
        if not static.is_dir():
            static = DEFAULT_STATIC
        super().__init__(*a, directory=str(static), **k)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _redirect(self, loc: str):
        self.send_response(308)
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_board(self):
        # inject station config into board.html
        cfg = load_station_config()
        board_path = DEFAULT_STATIC / "board.html"
        station_board = station_dir() / "static" / "index.html"
        if station_board.is_file():
            html = station_board.read_text()
        else:
            html = board_path.read_text()
        inject = (
            "<script>window.EIDOS_TV = Object.assign(%s, window.EIDOS_TV || {});</script>\n"
            % json.dumps(
                {
                    "publicBase": cfg.get("publicBase") or f"http://{HOST}:{PORT}",
                    "brand": cfg.get("brand", "EIDOS"),
                    "brandSub": cfg.get("brandSub", "STATION · TV"),
                    "livePrefix": cfg.get("livePrefix", "LIVE"),
                    "stationId": STATION_ID,
                }
            )
        )
        if "window.EIDOS_TV = Object.assign" in html and "<script>window.EIDOS_TV = Object.assign" not in html[:800]:
            # prepend inject before first script that sets defaults
            html = html.replace("<script>", inject + "<script>", 1)
        elif inject.strip() not in html:
            html = html.replace("<script>", inject + "<script>", 1)
        raw = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        raw = self.path.split("?", 1)[0]
        path = raw.rstrip("/") or "/"

        if path in ("/api/board", "/api/board.json"):
            try:
                body = board_payload()
            except Exception as e:
                traceback.print_exc()
                body = {"live": False, "error": f"{type(e).__name__}: {e}", "markets": {"series": [], "quotes": []}}
            rawb = json.dumps(body, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(rawb)))
            self.end_headers()
            self.wfile.write(rawb)
            return

        if path in ("/api/insights", "/api/insights.json"):
            body = board_payload().get("insights") or {"insights": []}
            if isinstance(body, list):
                body = {"insights": body, "count": len(body)}
            rawb = json.dumps(body, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(rawb)))
            self.end_headers()
            self.wfile.write(rawb)
            return

        if path.startswith("/api/insight/"):
            iid = path.split("/api/insight/", 1)[-1].strip("/")
            ins = get_insight(iid)
            if not ins:
                self.send_error(404, "insight not found")
                return
            rawb = json.dumps(ins, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(rawb)))
            self.end_headers()
            self.wfile.write(rawb)
            return

        if path in ("/", ""):
            return self._redirect("/dark/")
        if path in ("/dark", "/light") or path.startswith("/dark/i/") or path.startswith("/light/i/"):
            return self._serve_board()
        if path in ("/index.html", "/board.html"):
            return self._serve_board()

        return super().do_GET()


def main():
    d = station_dir()
    print(
        f"eidos-tv station={STATION_ID} dir={d} http://{HOST}:{PORT}/  themes=/dark/ /light/",
        flush=True,
    )
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
