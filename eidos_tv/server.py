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

def load_channels() -> dict:
    for p in (ROOT / "channels.json", PKG.parent / "channels.json"):
        if p.is_file():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    # fallback: one channel per station folder
    stations_root = ROOT / "stations"
    if not stations_root.is_dir():
        stations_root = PKG.parent / "stations"
    chans = []
    n = 2
    if stations_root.is_dir():
        for d in sorted(stations_root.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            cfg = {}
            sj = d / "station.json"
            if sj.is_file():
                try:
                    cfg = json.loads(sj.read_text())
                except Exception:
                    pass
            chans.append({
                "num": n,
                "station": d.name,
                "name": cfg.get("brand") or d.name.upper(),
                "callsign": (cfg.get("brand") or d.name)[:6].upper(),
                "program": cfg.get("brandSub") or "Live board",
                "desc": cfg.get("description") or f"Station {d.name}",
                "preset": "full",
            })
            n += 2
    if not chans:
        chans = [{"num": 2, "station": STATION_ID, "name": "EIDOS", "callsign": "EID-2",
                  "program": "Live", "desc": "Default station", "preset": "full"}]
    return {"guide_title": "TV GUIDE", "channels": chans}


def resolve_channel(ch: str | int | None = None, station: str | None = None) -> dict:
    """Resolve by explicit ``num`` field (Daniel-reassignable config), never list position."""
    cat = load_channels()
    chans = sorted(cat.get("channels") or [], key=lambda c: int(c.get("num") or 0))
    if ch is not None and str(ch).strip() != "":
        try:
            num = int(ch)
            for c in chans:
                if int(c.get("num", -1)) == num:
                    return c
        except ValueError:
            pass
        for c in chans:
            if str(c.get("station")) == str(ch) or str(c.get("callsign")) == str(ch):
                return c
    if station:
        for c in chans:
            if c.get("station") == station and (c.get("kind") or "station") != "guide":
                return c
        for c in chans:
            if c.get("station") == station:
                return c
    # Prefer configured content station (not guide) matching STATION_ID, else first non-guide
    for c in chans:
        if c.get("station") == STATION_ID and (c.get("kind") or "station") != "guide":
            return c
    for c in chans:
        if (c.get("kind") or "station") != "guide":
            return c
    return chans[0] if chans else {"num": 2, "station": STATION_ID, "name": "EIDOS", "preset": "full", "kind": "station"}


def station_dir_for(station_id: str) -> Path:
    candidates = [
        ROOT / "stations" / station_id,
        PKG.parent / "stations" / station_id,
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def load_provider_for(station_id: str):
    path = station_dir_for(station_id) / "provider.py"
    if not path.is_file():
        raise FileNotFoundError(f"No provider.py for station {station_id}")
    spec = importlib.util.spec_from_file_location(f"station_{station_id}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    if not hasattr(mod, "fetch_board"):
        raise RuntimeError(f"{station_id} provider must define fetch_board()")
    return mod


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


def board_payload(channel: dict | None = None) -> dict:
    ch = channel or resolve_channel(station=STATION_ID)
    # Guide is config chrome (CH 01 doctrine) — not a station provider
    kind = (ch.get("kind") or "station").lower()
    if kind == "guide" or (ch.get("station") or "").lower() == "guide":
        return {
            "live": True,
            "source": "guide",
            "bug": "GUIDE",
            "live_label": "GUIDE",
            "kind": "guide",
            "channel": ch,
            "channels": load_channels(),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "markets": {"title": "TV GUIDE", "subtitle": "SELECT A CHANNEL", "chart": "bronze_bars_quality_line", "series": [], "quotes": []},
            "stories": [],
            "special": {
                "kicker": "GUIDE",
                "headline": ch.get("program") or "TV Guide",
                "bullets": [c.get("desc") or c.get("name") for c in (load_channels().get("channels") or [])[:8]],
                "href": "/",
            },
            "insights": {"insights": [], "count": 0},
            "week": {"days_list": []},
            "ticker": ["TV GUIDE", "CH NUMBERS ARE CONFIG (num FIELD)", "TUNE WITH CH+/CH− OR GUIDE"],
            "station": {
                "id": "guide",
                "brand": "GUIDE",
                "brandSub": "CH 01 · CHANNEL CHANGER",
                "publicBase": f"http://{HOST}:{PORT}",
            },
        }

    station_id = ch.get("station") or STATION_ID
    preset = ch.get("preset") or "full"
    cache_key = f"{station_id}:{preset}:{ch.get('num')}"
    now = time.time()
    if (
        _cache.get("payload") is not None
        and _cache.get("key") == cache_key
        and (now - _cache["t"]) < CACHE_TTL
    ):
        return _cache["payload"]

    # station env for provider
    prev_station = os.environ.get("EIDOS_TV_STATION")
    prev_preset = os.environ.get("EIDOS_TV_PRESET")
    os.environ["EIDOS_TV_STATION"] = station_id
    os.environ["EIDOS_TV_PRESET"] = str(preset)
    try:
        sdir = station_dir_for(station_id)
        cfg_path = sdir / "station.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {
            "id": station_id, "brand": ch.get("name", "EIDOS"),
            "brandSub": ch.get("program", "STATION · TV"),
            "publicBase": f"http://{HOST}:{PORT}",
        }
        mod = load_provider_for(station_id)
        body = mod.fetch_board()
    finally:
        if prev_station is None:
            os.environ.pop("EIDOS_TV_STATION", None)
        else:
            os.environ["EIDOS_TV_STATION"] = prev_station
        if prev_preset is None:
            os.environ.pop("EIDOS_TV_PRESET", None)
        else:
            os.environ["EIDOS_TV_PRESET"] = prev_preset

    body.setdefault("bug", cfg.get("brand", "EIDOS TV"))
    body.setdefault("generated_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    body["station"] = cfg
    body["channel"] = ch
    body["channels"] = load_channels()
    # optional insights file
    ins = station_dir_for(station_id) / "data" / "insights.json"
    if ins.is_file() and "insights" not in body:
        try:
            body["insights"] = json.loads(ins.read_text())
        except Exception:
            pass
    week = station_dir_for(station_id) / "data" / "week.json"
    if week.is_file() and "week" not in body:
        try:
            body["week"] = json.loads(week.read_text())
        except Exception:
            pass
    _cache.update(t=now, payload=body, key=cache_key)
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

        if path in ("/api/channels", "/api/channels.json"):
            rawb = json.dumps(load_channels(), default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(rawb)))
            self.end_headers()
            self.wfile.write(rawb)
            return

        if path in ("/api/board", "/api/board.json"):
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                ch = (qs.get("ch") or qs.get("channel") or [None])[0]
                st = (qs.get("station") or [None])[0]
                channel = resolve_channel(ch=ch, station=st)
                body = board_payload(channel)
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
