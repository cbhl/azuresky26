# Scripts

| Script | Purpose |
|--------|---------|
| [`flighty_import.py`](flighty_import.py) | Flighty CSV → `data/flights.json` + map SVG |
| [`render_travel_map.py`](render_travel_map.py) | `data/flights.json` → `static/images/travel-map.svg` (also called by import) |
| [`starbucks_fetch.py`](starbucks_fetch.py) | Live session → `data/starbucks/all-items.json` + `receipts.json` (incremental) |
| [`starbucks_browser_fetch.py`](starbucks_browser_fetch.py) | Cookie-free alternative to `starbucks_fetch.py`: browser-use + Bitwarden drive starbucks.ca, record the page's own history/receipt responses, and merge only new activity into `history.json` |
| [`starbucks_import.py`](starbucks_import.py) | `data/starbucks/receipts.json` + `all-items.json` + `stores-gta.json` → `starbucks.json` |
| [`starbucks_caffeine.py`](starbucks_caffeine.py) | Ledger visits → daily and hour-of-day caffeine estimate (`caffeine` block in `starbucks.json`; called by import). Edit its `RULES`/`TABLES` to change the estimate |
| [`fetch_starbucks_basemap.py`](fetch_starbucks_basemap.py) | Overpass OSM → `data/starbucks/basemap.json` (roads, water, labels; rare refresh) |
| [`render_starbucks_map.py`](render_starbucks_map.py) | `starbucks.json` + basemap → `static/images/starbucks-map.svg` |

Data flow for Starbucks: receipts + locator stores → `starbucks_import.py` → `starbucks.json` (+ `to_visit` list) → `render_starbucks_map.py` → SVG. Map shows all standalone stores plus visited non-standalone (blue). Remaining count links to `/starbucks/to-visit/`.

`starbucks_import.py` does a full rebuild when the raw `receipts.json` is present. Without it (it is gitignored), the script refreshes only the ledger-derived `caffeine` block of the committed `starbucks.json` in place and leaves every other field as committed, so the caffeine estimate can be updated on a machine that lacks the full data.

## Travel section

See [`travel-section.md`](travel-section.md) for architecture, design decisions, and how the `/travel/` page is built.

Raw Flighty export instructions: [`../data/flighty/README.md`](../data/flighty/README.md).

## Updating Starbucks data

`data/starbucks/history.json` is the committed canonical ledger. It may retain
source observation IDs for reconciliation, but generated
`data/starbucks/starbucks.json` and the rendered HTML must not expose source
IDs or native API history IDs. Keep CIR exports, the session cookie, and raw
fetch artifacts private and uncommitted.

For a report import, provide the private USA and/or Canada Customer Information
Report paths explicitly:

```bash
python3 scripts/starbucks_history.py \
  --us-report /private/path/usa-report.csv \
  --ca-report /private/path/canada-report.csv \
  --receipts data/starbucks/receipts.json \
  --output data/starbucks/history.json
```

The API session is refreshed separately. Update the cookie in repo-root
`get-transaction-history.sh` if needed (the `-b '...'` value), but do not
execute that file. Then fetch history and any new Redemption receipts:

```bash
python3 scripts/starbucks_fetch.py
```

The fetch is incremental for receipts and merges the current API export into
the existing canonical ledger without deleting report history. Rebuild derived
data and the site afterward:

```bash
python3 scripts/starbucks_import.py
python3 scripts/render_starbucks_map.py
zola check
zola build
```

Verify that public artifacts contain no source identifiers before publishing:

```bash
rg -n 'source_observation_ids|historyId|visit_id' data/starbucks/starbucks.json public/starbucks
```

The verification command should produce no matches. Receipt fetches are
incremental: already-saved `historyId`s in `receipts.json` are skipped on later
runs.

### Browser-driven refresh (no copied cookie)

`scripts/starbucks_browser_fetch.py` replaces the cookie step above. It uses
[browser-use](https://docs.browser-use.com) to open a Browser Use Cloud
browser, signs in with the Bitwarden CLI (item `com.starbucks.mobilecard` by
default, `--bw-item` to change), opens `/account/history`, clicks "Show more
activity" and each "View receipt", and records the JSON responses the page
itself requests. The session cookie never leaves the browser.

One-time setup: `uv tool install browser-use`, `browser-use skill install
--target claude` (and `--target opencode`), `browser-use auth login
--api-key-stdin` with `BROWSER_USE_API_KEY`, and an unlocked Bitwarden vault
(`BW_SESSION` exported).

```bash
python3 scripts/starbucks_browser_fetch.py --start-browser --stop-browser
python3 scripts/starbucks_import.py
python3 scripts/render_starbucks_map.py
zola check
zola build
```

It is incremental: only activity newer than the ledger's latest visit (one-day
overlap) is paged and only those receipts are opened. Use `--full` to re-pull
everything and `--name NAME` to reuse an already-running daemon. A cloud
browser bills until stopped, so use `--stop-browser` (or stop it yourself).
Sign-in stops with an error if Starbucks asks for MFA or a captcha.

Basemap (roads/water/labels) is committed as `data/starbucks/basemap.json`.
Refresh rarely:

```bash
python3 scripts/fetch_starbucks_basemap.py
python3 scripts/render_starbucks_map.py
```
