"""Demo station — synthetic board so eidos-tv runs with zero deps."""
from __future__ import annotations

import time
from datetime import datetime, timezone


def fetch_board() -> dict:
    import os
    preset = os.environ.get("EIDOS_TV_PRESET", "full")

    now = int(time.time())
    # rising bronze bars + quality line
    series = []
    bronze = 400
    quality = 3.2
    for i in range(12):
        bronze += 40 + (i % 3) * 15
        quality = min(6.5, quality + 0.08 + (0.04 if i % 2 == 0 else 0))
        t = now - (11 - i) * 600  # 10-min steps
        series.append({
            "t": t,
            "label": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%H:%MZ"),
            "bronze": float(bronze),
            "quality": round(quality, 2),
            "v": float(bronze),
            "kind": "sample",
        })

    insights = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audience": ["ceo", "cfo"],
        "count": 2,
        "insights": [
            {
                "id": "ins_demo_margin",
                "kind": "demo_margin",
                "score": 0.9,
                "headline": "Demo: contribution after cost fell while volume held",
                "body": "This is sample insight text. Replace with a real station provider that reads your warehouse or APIs.",
                "why_interesting": "Shows the insight card + QR deep-link pattern.",
                "evidence": {"demo": True},
                "url": {
                    "dark": "http://127.0.0.1:8799/dark/i/ins_demo_margin",
                    "light": "http://127.0.0.1:8799/light/i/ins_demo_margin",
                },
                "paths": {"dark": "/dark/i/ins_demo_margin", "light": "/light/i/ins_demo_margin"},
            },
            {
                "id": "ins_demo_lob",
                "kind": "demo_lob",
                "score": 0.85,
                "headline": "Demo: one product line up 20% while the total looked flat",
                "body": "Mix shifts hide under flat totals. Your station should surface those from live metrics.",
                "why_interesting": "LOB mix is a classic CEO/CFO conversation.",
                "evidence": {"demo": True},
                "url": {
                    "dark": "http://127.0.0.1:8799/dark/i/ins_demo_lob",
                    "light": "http://127.0.0.1:8799/light/i/ins_demo_lob",
                },
                "paths": {"dark": "/dark/i/ins_demo_lob", "light": "/light/i/ins_demo_lob"},
            },
        ],
        "note": "Demo insights — not live data.",
    }

    week = {
        "generated_at": insights["generated_at"],
        "days_list": [
            {"date": "2026-07-23", "weekday": "Thu", "headline": "Demo day — ship the station toolkit", "commit_count": 12, "bullets": ["Open-sourced eidos-tv", "Demo provider online"]},
            {"date": "2026-07-22", "weekday": "Wed", "headline": "Demo day — quiet", "commit_count": 0, "bullets": ["Quiet day"]},
        ],
    }

    return {
        "live": True,
        "source": "demo",
        "bug": "EIDOS TV",
        "live_label": "DEMO",
        "markets": {
            "title": "PROGRESS · QUALITY",
            "subtitle": "BRONZE BARS · QUALITY LINE · 10-MIN SAMPLES",
            "chart": "bronze_bars_quality_line",
            "unit": "cells",
            "series": series,
            "quotes": [
                {"sym": "BRONZE", "title": "Progress metric", "last": bronze, "pct": 42.0, "unit": "cells", "note": "demo"},
                {"sym": "QUAL", "title": "Quality mean", "last": round(quality, 2), "pct": 0, "unit": "score", "note": "demo"},
                {"sym": "UP", "title": "Good moves", "last": 3, "pct": 0, "unit": "", "note": "demo"},
                {"sym": "WATCH", "title": "Watch items", "last": 1, "pct": 0, "unit": "", "note": "demo"},
            ],
        },
        "stories": [
            {"tag": "TOOLKIT", "text": "eidos-tv is the open-source station kit — segments, themes, QR insights, live adapters.", "href": "https://github.com/eidos-agi/eidos-tv"},
            {"tag": "CAST", "text": "Build once, cast to a wall display, scan QR for the insight on your phone.", "href": "https://github.com/eidos-agi/eidos-tv"},
            {"tag": "DATA", "text": "Swap stations/demo/provider.py for your warehouse, ERP, or API.", "href": "https://github.com/eidos-agi/eidos-tv"},
            {"tag": "THEMES", "text": "Dark and light themes share one board; deep links pin an insight.", "href": "https://github.com/eidos-agi/eidos-tv"},
        ],
        "special": {
            "kicker": "SPECIAL · EIDOS TV",
            "headline": "An open toolkit for building TV stations like Greenmark Ops Board.",
            "bullets": [
                "Segments rotate; pause/play pie; scrub charts.",
                "Insights are first-class with scannable IDs.",
                "Station providers are just Python fetch_board() modules.",
            ],
            "href": "https://github.com/eidos-agi/eidos-tv",
        },
        "upcoming": [],
        "insights": insights,
        "week": week,
        "ticker": [
            "EIDOS-TV DEMO",
            "SEGMENTS · INSIGHTS · QR",
            "LIGHT + DARK THEMES",
            "10-MIN PROGRESS SAMPLES",
            "github.com/eidos-agi/eidos-tv",
        ],
        "health": {"git_sha_short": "demo", "status": "ok"},
        "preset": preset,
        "preferred_segment": {
            "full": None,
            "insights": "DATA INSIGHTS",
            "week": "THIS WEEK",
        }.get(preset),
    }
