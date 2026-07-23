# eidos-tv

**Open-source toolkit for building castable TV stations** — operations walls, executive boards, and walk-up displays that rotate segments, scrub charts, pause on demand, and deep-link insights via QR.

Born from real station work (segment rotation, light/dark themes, bronze progress columns + quality line, CEO/CFO insights with scannable IDs). Generalized so any team can stand up a station with a small Python provider.

## Channel changer + TV guide

Cable-style overlays shipped in the board chrome:

| Control | Action |
|---------|--------|
| **CH+ / CH−** | Next / previous channel |
| **GUIDE** or **G** | On-screen TV guide |
| **↑ ↓** in guide | Move selection |
| **Enter** | Tune |
| **Esc** | Close guide |
| **PageUp / PageDown** | Channel up / down |

Channels are declared in root `channels.json` (number, station, callsign, program, preset). Tuning calls `/api/board?ch=<num>` and swaps the live station/preset. A classic **channel banner OSD** appears for a few seconds after each tune.

## Features

| Feature | What it is |
|---------|------------|
| **Segments** | Rotating board: markets, insights, stories, special, week |
| **Themes** | `/dark/` and `/light/` |
| **Progress chart** | Rising **columns** + **quality line** (10‑minute samples) |
| **Insights** | High-signal cards with stable `ins_…` IDs |
| **QR deep links** | Scan to open the current insight on a phone |
| **Stations** | Pluggable `provider.py` + `station.json` |

## Quick start

```bash
git clone https://github.com/eidos-agi/eidos-tv.git
cd eidos-tv
python3 -m pip install -e .

eidos-tv serve --station demo --port 8799
# open http://127.0.0.1:8799/dark/
#     http://127.0.0.1:8799/light/
#     http://127.0.0.1:8799/dark/i/ins_demo_margin
```

Or without install:

```bash
PYTHONPATH=. python3 -m eidos_tv.cli serve --station demo --root .
```

## Build your own station

```
stations/myco/
  station.json      # brand, publicBase URL for QR
  provider.py       # def fetch_board() -> dict
  data/             # optional insights.json, week.json, progress.json
  static/           # optional index.html override
```

`fetch_board()` should return at least:

```python
{
  "markets": {
    "title": "...",
    "subtitle": "BRONZE BARS · QUALITY LINE",
    "chart": "bronze_bars_quality_line",
    "series": [
      {"t": 1710000000, "label": "…", "bronze": 1200, "quality": 4.2, "v": 1200}
    ],
    "quotes": [{"sym": "X", "last": 1, "pct": 0, "note": ""}]
  },
  "stories": [...],
  "special": {"kicker": "", "headline": "", "bullets": [], "href": ""},
  "insights": {"insights": [{"id": "ins_…", "headline": "", "body": "", "score": 0.9, ...}]},
  "week": {"days_list": [...]},
  "ticker": ["…"]
}
```

Point `publicBase` at the public URL of the station (used in QR codes).

## Greenmark

The Greenmark Ops Board that drove this toolkit runs as a private station adapter (warehouse + gold metrics + auth door). Patterns live here; production credentials never ship in this repo.

## License

MIT — see [LICENSE](./LICENSE).

## Status

`0.1.0` — usable toolkit + demo station. Expect API polish as more stations land.
