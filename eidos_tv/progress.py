"""Campaign progress series: bronze bars + quality line, sampled ~every 10 min."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
STORE = ROOT / "data" / "progress.json"
MIN_INTERVAL = int(os.environ.get("TV_PROGRESS_INTERVAL", str(10 * 60)))  # seconds
MAX_POINTS = int(os.environ.get("TV_PROGRESS_MAX", "500"))

# Historical campaign checkpoints (bronze_shipped narrative) — seed once so
# the board shows upward columns before 10-min sampling accumulates.
# quality_mean is approximate until live samples exist (null-safe on chart).
SEED_CHECKPOINTS = [
    ("2026-07-01T12:00:00Z", 625, 3.40),
    ("2026-07-05T12:00:00Z", 688, 3.55),
    ("2026-07-10T12:00:00Z", 812, 3.70),
    ("2026-07-14T12:00:00Z", 967, 3.90),
    ("2026-07-16T12:00:00Z", 1219, 4.05),
    ("2026-07-18T12:00:00Z", 1243, 4.10),
    ("2026-07-22T12:00:00Z", 1333, 4.20),
    ("2026-07-23T07:30:00Z", 1438, 4.30),
    ("2026-07-23T16:00:00Z", 1481, 4.34),
]


def _parse_ts(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def _load() -> dict[str, Any]:
    if STORE.is_file():
        try:
            return json.loads(STORE.read_text())
        except Exception:
            pass
    return {"points": [], "seeded": False}


def _save(doc: dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    tmp.replace(STORE)


def ensure_seed(doc: dict[str, Any]) -> dict[str, Any]:
    if doc.get("seeded") and doc.get("points"):
        return doc
    pts = [
        {
            "t": _parse_ts(ts),
            "label": ts[:10],
            "bronze": float(b),
            "quality": float(q),
            "kind": "checkpoint",
        }
        for ts, b, q in SEED_CHECKPOINTS
    ]
    # merge with any live points
    live = [p for p in doc.get("points") or [] if p.get("kind") == "sample"]
    doc = {"points": pts + live, "seeded": True}
    _save(doc)
    return doc


def record_sample(bronze: float, quality: float, force: bool = False) -> dict[str, Any]:
    """Append a live sample if MIN_INTERVAL elapsed (or force)."""
    doc = ensure_seed(_load())
    pts = list(doc.get("points") or [])
    now = int(time.time())
    last = next((p for p in reversed(pts) if p.get("kind") == "sample"), None)
    if not force and last and (now - int(last["t"])) < MIN_INTERVAL:
        return doc
    pts.append(
        {
            "t": now,
            "label": datetime.now(timezone.utc).strftime("%m-%d %H:%MZ"),
            "bronze": float(bronze),
            "quality": float(quality),
            "kind": "sample",
        }
    )
    # cap
    if len(pts) > MAX_POINTS:
        # keep all checkpoints + newest samples
        cps = [p for p in pts if p.get("kind") == "checkpoint"]
        samples = [p for p in pts if p.get("kind") == "sample"][-(MAX_POINTS - len(cps)) :]
        pts = cps + samples
    doc["points"] = pts
    doc["seeded"] = True
    doc["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save(doc)
    return doc


def series_for_chart() -> list[dict[str, Any]]:
    doc = ensure_seed(_load())
    pts = doc.get("points") or []
    # normalize for chart: bronze bars + quality line
    out = []
    for p in pts:
        out.append(
            {
                "t": int(p["t"]),
                "label": p.get("label") or "",
                "bronze": float(p.get("bronze") or 0),
                "quality": float(p.get("quality") or 0),
                "kind": p.get("kind") or "sample",
                # back-compat for old chart field
                "v": float(p.get("bronze") or 0),
            }
        )
    return out
