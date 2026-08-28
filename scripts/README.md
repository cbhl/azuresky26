# Scripts

| Script | Purpose |
|--------|---------|
| [`flighty_import.py`](flighty_import.py) | Flighty CSV → `data/flights.json` + map SVG |
| [`render_travel_map.py`](render_travel_map.py) | `data/flights.json` → `static/images/travel-map.svg` (also called by import) |
| [`starbucks_fetch.py`](starbucks_fetch.py) | Live session → `data/starbucks/all-items.json` + `receipts.json` (incremental) |
| [`starbucks_import.py`](starbucks_import.py) | `data/starbucks/receipts.json` + `all-items.json` + `stores-gta.json` → `starbucks.json` |
| [`fetch_starbucks_basemap.py`](fetch_starbucks_basemap.py) | Overpass OSM → `data/starbucks/basemap.json` (roads, water, labels; rare refresh) |
| [`render_starbucks_map.py`](render_starbucks_map.py) | `starbucks.json` + basemap → `static/images/starbucks-map.svg` |

Data flow for Starbucks: receipts + locator stores → `starbucks_import.py` → `starbucks.json` (+ `to_visit` list) → `render_starbucks_map.py` → SVG. Map shows all standalone stores plus visited non-standalone (blue). Remaining count links to `/starbucks/to-visit/`.

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

Basemap (roads/water/labels) is committed as `data/starbucks/basemap.json`.
Refresh rarely:

```bash
python3 scripts/fetch_starbucks_basemap.py
python3 scripts/render_starbucks_map.py
```
