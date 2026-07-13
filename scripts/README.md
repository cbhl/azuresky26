# Scripts

| Script | Purpose |
|--------|---------|
| [`flighty_import.py`](flighty_import.py) | Flighty CSV → `data/flights.json` + map SVG |
| [`render_travel_map.py`](render_travel_map.py) | `data/flights.json` → `static/images/travel-map.svg` (also called by import) |

## Travel section

See [`travel-section.md`](travel-section.md) for architecture, design decisions, and how the `/travel/` page is built.

Raw Flighty export instructions: [`../data/flighty/README.md`](../data/flighty/README.md).
