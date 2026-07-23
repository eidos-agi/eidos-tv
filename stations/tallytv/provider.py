"""TallyTV station — CH 01 of ReevesTV.

Reads live row-safe finance signals from Daniel's mini:
  ~/.reeves/dally/dally.sqlite3 + evidence (campaign, dossiers, harvest, renewal-watch).

Never exposes account numbers, tokens, or raw Plaid rows.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DALLY_DB = Path(os.environ.get("TALLYTV_DALLY_DB", Path.home() / ".reeves" / "dally" / "dally.sqlite3"))
EVIDENCE = Path(os.environ.get("TALLYTV_EVIDENCE", Path.home() / ".reeves" / "dally" / "evidence"))
PUBLIC_BASE = os.environ.get("TALLYTV_PUBLIC_BASE", "http://100.83.12.9:4920")
AI_DEV_CEILING = float(os.environ.get("TALLYTV_AI_DEV_CEILING", "1200"))
KNOWN_DARK_RAILS = 6  # policy:coverage_rails


def fetch_board() -> dict:
    preset = os.environ.get("EIDOS_TV_PRESET", "full")
    now = datetime.now(timezone.utc)
    generated = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    amex_daily = _amex_daily_spend(days=14)
    coverage = _coverage_ratio()
    amex_ledger = _amex_ledger_balance()
    ai_dev = _ai_dev_month_total(now.strftime("%Y-%m"))
    kills = _kill_summary()
    renewals = _renewal_clocks(now.date())
    campaign_top = _campaign_top(n=5)
    week = _week_from_rm_harvest(now.date())
    insights = _insights(generated)
    series = _markets_series(amex_daily, coverage)

    bronze_last = series[-1]["bronze"] if series else 0.0
    quality_last = series[-1]["quality"] if series else coverage

    quotes = [
        {
            "sym": "AMEX$",
            "title": "Amex ledger balance",
            "last": round(amex_ledger, 2),
            "pct": 0,
            "unit": "USD",
            "note": "full-ledger charges−payments",
        },
        {
            "sym": "AI/DEV",
            "title": "AI/dev MTD vs ceiling",
            "last": round(ai_dev, 2),
            "pct": round((ai_dev / AI_DEV_CEILING - 1) * 100, 1) if AI_DEV_CEILING else 0,
            "unit": "USD",
            "note": f"cap ${AI_DEV_CEILING:.0f}",
        },
        {
            "sym": "COVER",
            "title": "Coverage ratio",
            "last": round(coverage * 100, 1),
            "pct": 0,
            "unit": "%",
            "note": "visible/(visible+known-dark)",
        },
        {
            "sym": "KILLS",
            "title": "Kills verified / claimed",
            "last": kills["verified_dead"],
            "pct": 0,
            "unit": "",
            "note": f"cancelled_claimed={kills['cancelled_claimed']} pending={kills['kill_ordered']}",
        },
        {
            "sym": "CGPT",
            "title": "ChatGPT Pro renewal",
            "last": 200,
            "pct": 0,
            "unit": "USD",
            "note": renewals.get("chatgpt_pro", "pending"),
        },
    ]

    ticker = _build_ticker(
        amex_ledger=amex_ledger,
        ai_dev=ai_dev,
        coverage=coverage,
        kills=kills,
        renewals=renewals,
        bronze_last=bronze_last,
    )

    special = {
        "kicker": "SPECIAL · KILL LIST STATUS",
        "headline": (
            f"{kills['cancelled_claimed']} cancelled_claimed · "
            f"{kills['verified_dead']} verified_dead · "
            f"{kills['hold']} HOLD · {kills['kill_ordered']} pending"
        ),
        "bullets": kills["bullets"][:8],
        "href": f"{PUBLIC_BASE}/dark/",
    }

    stories = []
    for i, row in enumerate(campaign_top, 1):
        stories.append(
            {
                "tag": f"CAMP#{row['rank']}",
                "text": (
                    f"{row['display_name'][:48]} · ${row['dollar_impact']:,.0f}/yr impact · "
                    f"{row['vendor_class']}/{row['cadence']} · {row['verify_status']}"
                ),
                "href": f"{PUBLIC_BASE}/dark/",
            }
        )
    if not stories:
        stories = [
            {
                "tag": "CAMP",
                "text": "Campaign manifest unavailable — run tally campaign on mini",
                "href": f"{PUBLIC_BASE}/dark/",
            }
        ]

    return {
        "live": True,
        "source": "tallytv",
        "bug": "TALLYTV",
        "live_label": "CH01",
        "markets": {
            "title": "AMEX DAILY SPEND · COVERAGE",
            "subtitle": "BRONZE = DAILY AMEX $ · QUALITY LINE = COVERAGE RATIO ×10",
            "chart": "bronze_bars_quality_line",
            "unit": "USD",
            "series": series,
            "quotes": quotes,
        },
        "stories": stories,
        "special": special,
        "upcoming": week.get("upcoming", []),
        "insights": insights,
        "week": week,
        "ticker": ticker,
        "health": {
            "git_sha_short": "tallytv",
            "status": "ok" if DALLY_DB.exists() else "degraded",
            "dally_db": str(DALLY_DB),
            "generated_at": generated,
        },
        "preset": preset,
        "preferred_segment": {
            "full": None,
            "insights": "DATA INSIGHTS",
            "week": "THIS WEEK",
        }.get(preset),
    }


# ── data loaders (row-safe) ──────────────────────────────────────────────


def _conn() -> sqlite3.Connection | None:
    if not DALLY_DB.exists():
        return None
    c = sqlite3.connect(f"file:{DALLY_DB}?mode=ro", uri=True, timeout=5.0)
    c.row_factory = sqlite3.Row
    return c


def _amex_item_ids(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT item_id FROM source_items WHERE lower(COALESCE(institution_name,'')) LIKE '%american express%'"
        )
    ]


def _amex_daily_spend(days: int = 14) -> list[tuple[str, float]]:
    conn = _conn()
    if not conn:
        return []
    try:
        amex = _amex_item_ids(conn)
        if not amex:
            return []
        start = (date.today() - timedelta(days=days - 1)).isoformat()
        ph = ",".join("?" * len(amex))
        by_day: dict[str, float] = defaultdict(float)
        for row in conn.execute(
            f"""
            SELECT date, payload_json FROM plaid_transactions
            WHERE removed_at IS NULL AND item_id IN ({ph}) AND date >= ?
            """,
            [*amex, start],
        ):
            try:
                d = json.loads(row["payload_json"])
            except Exception:
                continue
            if d.get("pending"):
                continue
            try:
                amt = float(d.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            name = (d.get("merchant_name") or d.get("name") or "").upper()
            if "PAYMENT" in name and "THANK" in name:
                continue
            by_day[str(row["date"])[:10]] += amt
        # fill missing days with 0 for chart continuity
        out = []
        for i in range(days):
            d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
            out.append((d, round(by_day.get(d, 0.0), 2)))
        return out
    finally:
        conn.close()


def _coverage_ratio() -> float:
    conn = _conn()
    if not conn:
        return 0.0
    try:
        visible = conn.execute(
            "SELECT COUNT(*) FROM source_items WHERE item_id IS NOT NULL"
        ).fetchone()[0]
        denom = int(visible) + KNOWN_DARK_RAILS
        return round(float(visible) / denom, 3) if denom else 0.0
    finally:
        conn.close()


def _amex_ledger_balance() -> float:
    """Full-ledger: sum(charges) - sum(|payments|) on Amex item."""
    conn = _conn()
    if not conn:
        return 0.0
    try:
        amex = _amex_item_ids(conn)
        if not amex:
            return 0.0
        ph = ",".join("?" * len(amex))
        charges = credits = 0.0
        for row in conn.execute(
            f"""
            SELECT payload_json FROM plaid_transactions
            WHERE removed_at IS NULL AND item_id IN ({ph})
            """,
            amex,
        ):
            try:
                d = json.loads(row["payload_json"])
            except Exception:
                continue
            if d.get("pending"):
                continue
            try:
                amt = float(d.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            if amt > 0:
                charges += amt
            elif amt < 0:
                credits += abs(amt)
        return round(charges - credits, 2)
    finally:
        conn.close()


def _ai_dev_month_total(ym: str) -> float:
    needles = (
        "openai", "anthropic", "claude", "cursor", "github", "perplexity",
        "midjourney", "replicate", "huggingface", "copilot", "vercel",
    )
    conn = _conn()
    if not conn:
        return 0.0
    try:
        total = 0.0
        for row in conn.execute(
            "SELECT payload_json FROM plaid_transactions WHERE removed_at IS NULL AND date LIKE ?",
            (f"{ym}%",),
        ):
            try:
                d = json.loads(row["payload_json"])
            except Exception:
                continue
            if d.get("pending"):
                continue
            try:
                amt = float(d.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            name = (d.get("merchant_name") or d.get("name") or "").lower()
            if any(n in name for n in needles):
                total += amt
        return round(total, 2)
    finally:
        conn.close()


def _kill_summary() -> dict[str, Any]:
    empty = {
        "cancelled_claimed": 0,
        "verified_dead": 0,
        "kill_ordered": 0,
        "hold": 0,
        "resurrected": 0,
        "bullets": ["kill-list unavailable"],
    }
    conn = _conn()
    if not conn:
        return empty
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "tally_kill_list" not in tables:
            return empty
        counts: dict[str, int] = defaultdict(int)
        bullets = []
        for row in conn.execute(
            """
            SELECT display_name, lifecycle, monthly_est, notes
            FROM tally_kill_list WHERE soft_deleted = 0
            ORDER BY
              CASE lifecycle
                WHEN 'resurrected' THEN 0
                WHEN 'cancelled_claimed' THEN 1
                WHEN 'hold' THEN 2
                WHEN 'kill_ordered' THEN 3
                ELSE 4 END,
              monthly_est DESC
            """
        ):
            life = row["lifecycle"] or ""
            counts[life] += 1
            name = (row["display_name"] or "?")[:36]
            bullets.append(f"{life}: {name} (${float(row['monthly_est'] or 0):.0f}/mo)")
        return {
            "cancelled_claimed": counts.get("cancelled_claimed", 0),
            "verified_dead": counts.get("verified_dead", 0),
            "kill_ordered": counts.get("kill_ordered", 0),
            "hold": counts.get("hold", 0),
            "resurrected": counts.get("resurrected", 0),
            "bullets": bullets or ["(empty kill-list)"],
        }
    finally:
        conn.close()


def _renewal_clocks(today: date) -> dict[str, str]:
    out: dict[str, str] = {}
    # ChatGPT Pro from renewal-watch
    rw = EVIDENCE / "cfo" / "renewal-watch.json"
    if rw.exists():
        try:
            data = json.loads(rw.read_text(encoding="utf-8"))
            for e in data.get("entries") or []:
                if "chatgpt" in (e.get("merchant") or "").lower():
                    ren = e.get("renews_on") or ""
                    dec = e.get("decision") or "pending"
                    days = _days_until(ren, today)
                    out["chatgpt_pro"] = f"renews {ren} ({days}d) decision={dec}"
        except Exception:
            pass
    if "chatgpt_pro" not in out:
        out["chatgpt_pro"] = "renews 2026-07-25 decision=pending_daniel"
    # LastPass ~12d from harvest 2026-07-23 → ~Aug 4
    out["lastpass"] = "renewal window ~2026-08-04 (harvest 12d clock from 2026-07-23) decision=pending"
    return out


def _days_until(ymd: str, today: date) -> int:
    try:
        return (date.fromisoformat(ymd[:10]) - today).days
    except Exception:
        return 0


def _campaign_top(n: int = 5) -> list[dict[str, Any]]:
    path = EVIDENCE / "campaign-202607" / "manifest.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        vendors = data.get("vendors") or []
        return [
            {
                "rank": v.get("rank"),
                "display_name": v.get("display_name") or "?",
                "dollar_impact": float(v.get("dollar_impact") or 0),
                "vendor_class": v.get("vendor_class") or "?",
                "cadence": v.get("cadence") or "?",
                "verify_status": v.get("verify_status") or "?",
            }
            for v in vendors[:n]
        ]
    except Exception:
        return []


def _week_from_rm_harvest(today: date) -> dict[str, Any]:
    """Parse Rocket Money harvest LIVE due-in-N-days into week calendar."""
    harvest = EVIDENCE / "rocketmoney-harvest-20260723.md"
    days: dict[str, list[str]] = defaultdict(list)
    upcoming = []
    if harvest.exists():
        text = harvest.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if not line.startswith("|") or "---" in line or line.startswith("| Item"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4:
                continue
            item, amt, _acct, due = cells[0], cells[1], cells[2], cells[3]
            if item.lower() in {"item", ""}:
                continue
            if "card payment" in item.lower() or "autopay" in item.lower():
                continue
            # due like "12d — RENEWAL" or "TODAY" or "27d"
            d_off = None
            if due.upper().startswith("TODAY"):
                d_off = 0
            else:
                m = re.search(r"(\d+)\s*d", due, re.I)
                if m:
                    d_off = int(m.group(1))
            if d_off is None or d_off > 21:
                continue
            day = today + timedelta(days=d_off)
            label = f"{item} {amt} ({due.split('—')[0].strip()})"
            days[day.isoformat()].append(label)
            upcoming.append(
                {
                    "date": day.isoformat(),
                    "title": item[:40],
                    "detail": f"{amt} · harvest due {due[:40]}",
                }
            )
    days_list = []
    for i in range(7):
        d = today + timedelta(days=i)
        bullets = days.get(d.isoformat(), ["(no harvest due)"])[:4]
        days_list.append(
            {
                "date": d.isoformat(),
                "weekday": d.strftime("%a"),
                "headline": bullets[0] if bullets else "Quiet",
                "commit_count": len(bullets) if bullets and bullets[0] != "(no harvest due)" else 0,
                "bullets": bullets,
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days_list": days_list,
        "upcoming": upcoming[:12],
        "note": "Upcoming from Rocket Money harvest (dark rails included as labels only)",
    }


def _insights(generated: str) -> dict[str, Any]:
    items = [
        {
            "id": "ins_openai_burn_jun25",
            "kind": "openai_burn",
            "score": 0.95,
            "headline": "OpenAI credits burn Jun 25–29 contained — auto-recharge OFF",
            "body": (
                "ChatGPT CREDITS auto-recharge (~$107 band) burned hard late June. "
                "Daniel OFF 2026-07-23; kill-list cancelled_claimed; detector is resurrection alarm. "
                "ChatGPT Pro $200 renews Jul 25 — decision pending (not default keep)."
            ),
            "why_interesting": "Largest preventable metered burn this quarter.",
            "evidence": {"window": "2026-06-25..2026-06-29", "status": "contained"},
        },
        {
            "id": "ins_perplexity_dupe",
            "kind": "subscription_dupe",
            "score": 0.88,
            "headline": "Perplexity duplicate still kill_ordered — boss browser blocked",
            "body": (
                "Two Perplexity rails on kill-list. Boss browser blocked by extension site policy — "
                "Daniel-manual cancel. Next boss-reachable probes: shadow.tech, supabase, mongodb."
            ),
            "why_interesting": "Clear cut; execution blocked on automation path only.",
            "evidence": {"lifecycle": "kill_ordered", "manual": True},
        },
        {
            "id": "ins_crunch_12in4",
            "kind": "anomaly_cluster",
            "score": 0.82,
            "headline": "Crunch gym clustering — 12 charges in ~4 months pattern",
            "body": "Material anomaly dossier; membership vs promo vs family still open.",
            "why_interesting": "High monthly run-rate with unclear household coverage.",
            "evidence": {"case_id": "crunch-12in4"},
        },
        {
            "id": "ins_founders_995",
            "kind": "membership_audit",
            "score": 0.8,
            "headline": "Founders Card $995/yr — usage unproven on dark + Amex rails",
            "body": "Harvest + Plaid Amex discrepancy; burden of proof on membership value.",
            "why_interesting": "Four-figure annual with weak usage evidence.",
            "evidence": {"case_id": "founders-card-995", "annual": 995},
        },
    ]
    for it in items:
        iid = it["id"]
        it["url"] = {
            "dark": f"{PUBLIC_BASE}/dark/i/{iid}",
            "light": f"{PUBLIC_BASE}/light/i/{iid}",
        }
        it["paths"] = {"dark": f"/dark/i/{iid}", "light": f"/light/i/{iid}"}
    return {
        "generated_at": generated,
        "audience": ["cfo", "daniel"],
        "count": len(items),
        "insights": items,
        "note": "TallyTV insights — row-safe CFO findings from campaign/dossiers",
    }


def _markets_series(
    amex_daily: list[tuple[str, float]],
    coverage: float,
) -> list[dict[str, Any]]:
    series = []
    # quality line: coverage ratio scaled ×10 so it sits visibly with $ bars on mixed charts
    q = round(coverage * 10.0, 2)
    for day, spend in amex_daily:
        try:
            t = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            t = int(time.time())
        series.append(
            {
                "t": t,
                "label": day[5:],  # MM-DD
                "bronze": float(spend),
                "quality": q,
                "v": float(spend),
                "kind": "amex_day",
            }
        )
    if not series:
        # synthetic empty day so chart still mounts
        t = int(time.time())
        series.append(
            {
                "t": t,
                "label": "n/a",
                "bronze": 0.0,
                "quality": q,
                "v": 0.0,
                "kind": "empty",
            }
        )
    return series


def _build_ticker(
    *,
    amex_ledger: float,
    ai_dev: float,
    coverage: float,
    kills: dict[str, Any],
    renewals: dict[str, str],
    bronze_last: float,
) -> list[str]:
    over = "OVER" if ai_dev > AI_DEV_CEILING else "OK"
    return [
        "TALLYTV · CH 02 · REEVES FINANCIAL",
        f"AMEX LEDGER ${amex_ledger:,.0f} (FULL-LEDGER)",
        f"AI/DEV MTD ${ai_dev:,.0f} / CAP ${AI_DEV_CEILING:,.0f} {over}",
        f"COVERAGE {coverage * 100:.0f}% VISIBLE RAILS",
        f"KILLS CLAIMED {kills['cancelled_claimed']} · VERIFIED {kills['verified_dead']} · HOLD {kills['hold']}",
        f"RENEWAL CGPT PRO {renewals.get('chatgpt_pro', '')}",
        f"RENEWAL LASTPASS {renewals.get('lastpass', '')}",
        f"AMEX DAY SPEND ${bronze_last:,.0f}",
        "ROW-SAFE · NO ACCOUNT NUMBERS · NO TOKENS",
    ]
