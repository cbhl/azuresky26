# Flighty export

Place your raw Flighty CSV export here as `export.csv`. This path is gitignored.

## Export from Flighty (iOS)

1. Open **Flighty** → **Profile** → **Settings** (gear)
2. **Manage** → **Account Data** → **Export Your Flights**
3. Save or share the file (often `FlightyExport-YYYY-MM-DD.csv`)

Do not edit the CSV manually.

## Import into the site

From the repo root:

```bash
python3 scripts/flighty_import.py
```

This writes sanitized flight data to `data/flights.json` (committed). Re-run after each new export.

Optional flags: `-i path/to/export.csv` and `-o path/to/flights.json`.
