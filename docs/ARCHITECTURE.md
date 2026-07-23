# Architecture

```
Browser (cast / wall)
   │  /dark/  /light/  /dark/i/{ins_id}
   ▼
eidos_tv.server  (stdlib HTTP)
   │  /api/board  /api/insights  /api/insight/{id}
   ▼
stations/<id>/provider.fetch_board()
   │
   ├─ warehouse / ERP / APIs  (your code)
   └─ data/*.json             (optional caches)
```

## Design rules

1. **Station owns data.** The toolkit owns chrome, rotation, themes, QR, deep links.
2. **Insights must be interesting.** Providers/engines should reject dull restatements.
3. **No secrets in git.** Env files and vaults stay outside the repo.
4. **10-minute progress samples** fit wall displays without hammering backends.

## Relationship to Northstar / Greenmark boards

The interaction model (segments, pie pause, scrub, lower-third, crawl) was proven on live boards, then extracted here so the next station is a provider — not a rewrite.


## Channel changer

`channels.json` at the project root lists channels. Each entry maps a **channel number** to a **station** provider and optional **preset** (e.g. start on insights). The board treats this like a real TV: guide overlay, CH+/CH−, and a short-lived channel banner. The server resolves `?ch=` / `?station=` on `/api/board` without restarting the process.
