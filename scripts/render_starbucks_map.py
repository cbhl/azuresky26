#!/usr/bin/env python3
"""Render GTA Starbucks visit map to a static SVG from starbucks.json.

City-level basemap (major roads, water, place labels) comes from
data/starbucks/basemap.json (OpenStreetMap via fetch_starbucks_basemap.py).

Markers: standalone unvisited, standalone visited, visited non-standalone.

Usage:
    python3 scripts/render_starbucks_map.py
    python3 scripts/render_starbucks_map.py -i data/starbucks/starbucks.json -o static/images/starbucks-map.svg
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "starbucks" / "starbucks.json"
DEFAULT_OUTPUT = ROOT / "static" / "images" / "starbucks-map.svg"
BASEMAP_PATH = ROOT / "data" / "starbucks" / "basemap.json"

WIDTH = 720
HEIGHT = 420
PAD = 14

BG = "#dce6ef"
LAND = "#f3efe6"
WATER_FILL = "#b9d0e4"
BORDER = "#a8b2bc"

ROAD_MOTORWAY = "#c4a574"
ROAD_TRUNK = "#cbb892"
ROAD_PRIMARY = "#b0b8c0"
ROAD_SECONDARY = "#c5ccd4"

LABEL_FILL = "#4a5560"
LABEL_HALO = "#f3efe6"

VISITED_FILL = "#1a7f4b"
VISITED_STROKE = "#0d4d2c"
UNVISITED_FILL = "#c5ccd4"
UNVISITED_STROKE = "#6b7280"
# Visited licensed / grocery / embedded — distinct from standalone green.
NONSTAND_VISITED_FILL = "#2b6cb0"
NONSTAND_VISITED_STROKE = "#1a365d"

DEFAULT_BBOX = {
    "lat_min": 43.30,
    "lat_max": 44.12,
    "lng_min": -80.05,
    "lng_max": -78.50,
}


def project(
    lat: float,
    lon: float,
    bbox: dict,
    x0: float,
    y0: float,
    plot_w: float,
    plot_h: float,
) -> tuple[float, float]:
    x = x0 + (lon - bbox["lng_min"]) / (bbox["lng_max"] - bbox["lng_min"]) * plot_w
    y = y0 + (bbox["lat_max"] - lat) / (bbox["lat_max"] - bbox["lat_min"]) * plot_h
    return x, y


def in_bbox(lat: float, lon: float, bbox: dict, margin: float = 0.05) -> bool:
    return (
        bbox["lat_min"] - margin <= lat <= bbox["lat_max"] + margin
        and bbox["lng_min"] - margin <= lon <= bbox["lng_max"] + margin
    )


def polyline_d(
    coords: list,
    bbox: dict,
    x0: float,
    y0: float,
    plot_w: float,
    plot_h: float,
) -> str:
    parts: list[str] = []
    for i, pt in enumerate(coords):
        lon, lat = float(pt[0]), float(pt[1])
        x, y = project(lat, lon, bbox, x0, y0, plot_w, plot_h)
        parts.append(f"{'M' if i == 0 else 'L'} {x:.2f} {y:.2f}")
    return " ".join(parts)


def polygon_d(
    rings: list,
    bbox: dict,
    x0: float,
    y0: float,
    plot_w: float,
    plot_h: float,
) -> str:
    chunks: list[str] = []
    for ring in rings:
        if len(ring) < 3:
            continue
        parts: list[str] = []
        for i, pt in enumerate(ring):
            lon, lat = float(pt[0]), float(pt[1])
            x, y = project(lat, lon, bbox, x0, y0, plot_w, plot_h)
            parts.append(f"{'M' if i == 0 else 'L'} {x:.2f} {y:.2f}")
        parts.append("Z")
        chunks.append(" ".join(parts))
    return " ".join(chunks)


def render_basemap(
    basemap: dict,
    bbox: dict,
    x0: float,
    y0: float,
    plot_w: float,
    plot_h: float,
) -> tuple[str, str, str]:
    water_paths: list[str] = []
    for feat in basemap.get("water") or []:
        rings = feat.get("coords") or []
        d = polygon_d(rings, bbox, x0, y0, plot_w, plot_h)
        if d:
            water_paths.append(f'<path d="{d}"/>')

    road_layers = {
        "secondary": [],
        "primary": [],
        "trunk": [],
        "motorway": [],
    }
    stroke = {
        "secondary": (ROAD_SECONDARY, 0.7),
        "primary": (ROAD_PRIMARY, 1.0),
        "trunk": (ROAD_TRUNK, 1.35),
        "motorway": (ROAD_MOTORWAY, 1.7),
    }
    for road in basemap.get("roads") or []:
        cls = road.get("class") or "secondary"
        if cls not in road_layers:
            cls = "secondary"
        coords = road.get("coords") or []
        if len(coords) < 2:
            continue
        # Skip if entirely outside (cheap check on endpoints)
        ends_in = any(
            in_bbox(float(pt[1]), float(pt[0]), bbox, 0.02) for pt in (coords[0], coords[-1])
        )
        if not ends_in:
            mid = coords[len(coords) // 2]
            if not in_bbox(float(mid[1]), float(mid[0]), bbox, 0.02):
                continue
        d = polyline_d(coords, bbox, x0, y0, plot_w, plot_h)
        if d:
            road_layers[cls].append(f'<path d="{d}"/>')

    water_svg = ""
    if water_paths:
        water_svg = (
            f'<g class="water" fill="{WATER_FILL}" stroke="none">'
            f'{"".join(water_paths)}</g>'
        )

    roads_svg_parts: list[str] = []
    for cls in ("secondary", "primary", "trunk", "motorway"):
        paths = road_layers[cls]
        if not paths:
            continue
        color, width = stroke[cls]
        roads_svg_parts.append(
            f'<g class="roads-{cls}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">'
            f'{"".join(paths)}</g>'
        )
    roads_svg = "".join(roads_svg_parts)

    label_parts: list[str] = []
    for lab in basemap.get("labels") or []:
        lat = lab.get("lat")
        lon = lab.get("lon")
        name = lab.get("name") or ""
        if lat is None or lon is None or not name:
            continue
        if not in_bbox(float(lat), float(lon), bbox, 0.0):
            continue
        x, y = project(float(lat), float(lon), bbox, x0, y0, plot_w, plot_h)
        place = lab.get("place") or "town"
        size = 11 if place == "city" else 9
        weight = "600" if place == "city" else "500"
        safe = escape(name)
        # Halo via paint-order stroke under fill
        label_parts.append(
            f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="{size}" '
            f'font-weight="{weight}" fill="{LABEL_FILL}" stroke="{LABEL_HALO}" '
            f'stroke-width="3" paint-order="stroke" opacity="0.92">{safe}</text>'
        )
    labels_svg = f'<g class="labels">{"".join(label_parts)}</g>' if label_parts else ""

    return water_svg, roads_svg, labels_svg


def store_marker(
    store: dict, bbox: dict, x0: float, y0: float, plot_w: float, plot_h: float
) -> str | None:
    lat = store.get("lat")
    lon = store.get("lon")
    if lat is None or lon is None:
        return None
    if not in_bbox(float(lat), float(lon), bbox, margin=0.0):
        return None
    x, y = project(float(lat), float(lon), bbox, x0, y0, plot_w, plot_h)
    name = store.get("name") or "Starbucks"
    region = store.get("region") or ""
    standalone = bool(store.get("standalone"))
    visited = bool(store.get("visited"))
    visits = int(store.get("visits") or 0)

    if standalone and visited:
        title = f"{name} ({region}) — {visits} visit{'s' if visits != 1 else ''}"
        r, fill, stroke, sw = 4.5, VISITED_FILL, VISITED_STROKE, 1.1
        kind = "standalone-visited"
    elif standalone:
        title = f"{name} ({region}) — not visited yet"
        r, fill, stroke, sw = 3.0, UNVISITED_FILL, UNVISITED_STROKE, 0.85
        kind = "standalone-unvisited"
    elif visited:
        title = f"{name} ({region}) — licensed/embedded · {visits} visit{'s' if visits != 1 else ''}"
        r, fill, stroke, sw = 3.6, NONSTAND_VISITED_FILL, NONSTAND_VISITED_STROKE, 1.0
        kind = "non-standalone-visited"
    else:
        return None

    return (
        kind,
        (
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}">'
            f"<title>{escape(title)}</title></circle>"
        ),
    )


def legend_svg(x0: float, y0: float, plot_w: float, plot_h: float) -> str:
    lx = x0 + 8
    ly = y0 + plot_h - 52
    items = [
        (VISITED_FILL, VISITED_STROKE, "Standalone visited"),
        (UNVISITED_FILL, UNVISITED_STROKE, "Standalone remaining"),
        (NONSTAND_VISITED_FILL, NONSTAND_VISITED_STROKE, "Other visited"),
    ]
    parts = [
        f'<rect x="{lx - 6:.1f}" y="{ly - 12:.1f}" width="168" height="58" '
        f'rx="3" fill="{LAND}" fill-opacity="0.92" stroke="{BORDER}" stroke-width="0.6"/>'
    ]
    for i, (fill, stroke, label) in enumerate(items):
        cy = ly + i * 14
        parts.append(
            f'<circle cx="{lx + 6:.1f}" cy="{cy:.1f}" r="3.2" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="0.9"/>'
            f'<text x="{lx + 16:.1f}" y="{cy + 3.2:.1f}" font-family="system-ui,sans-serif" '
            f'font-size="9" fill="{LABEL_FILL}">{escape(label)}</text>'
        )
    return f'<g class="legend">{"".join(parts)}</g>'


def render_starbucks_map(map_data: dict, output_path: Path, basemap: dict | None) -> bool:
    stores = map_data.get("stores") or []
    if not stores:
        return False

    bbox = dict(DEFAULT_BBOX)
    raw_bbox = map_data.get("bbox") or {}
    for key in DEFAULT_BBOX:
        if key in raw_bbox:
            bbox[key] = float(raw_bbox[key])

    x0 = PAD
    y0 = PAD
    plot_w = WIDTH - 2 * PAD
    plot_h = HEIGHT - 2 * PAD

    water_svg = roads_svg = labels_svg = ""
    if basemap:
        water_svg, roads_svg, labels_svg = render_basemap(
            basemap, bbox, x0, y0, plot_w, plot_h
        )

    buckets = {
        "standalone-unvisited": [],
        "non-standalone-visited": [],
        "standalone-visited": [],
    }
    for store in stores:
        result = store_marker(store, bbox, x0, y0, plot_w, plot_h)
        if not result:
            continue
        kind, mark = result
        buckets[kind].append(mark)

    # Draw order: unvisited under non-standalone under standalone visited
    layers = (
        f'<g class="standalone-unvisited">{"".join(buckets["standalone-unvisited"])}</g>'
        f'<g class="non-standalone-visited">{"".join(buckets["non-standalone-visited"])}</g>'
        f'<g class="standalone-visited">{"".join(buckets["standalone-visited"])}</g>'
    )

    legend = legend_svg(x0, y0, plot_w, plot_h)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-label="Starbucks stores visited across the Greater Toronto Area">
  <defs>
    <clipPath id="plot-clip">
      <rect x="{x0}" y="{y0}" width="{plot_w}" height="{plot_h}"/>
    </clipPath>
  </defs>
  <rect width="100%" height="100%" fill="{BG}"/>
  <rect x="{x0}" y="{y0}" width="{plot_w}" height="{plot_h}" fill="{LAND}" stroke="{BORDER}" stroke-width="0.75"/>
  <g clip-path="url(#plot-clip)">
  {water_svg}
  {roads_svg}
  {layers}
  {labels_svg}
  </g>
  {legend}
  <rect x="{x0}" y="{y0}" width="{plot_w}" height="{plot_h}" fill="none" stroke="{BORDER}" stroke-width="0.75"/>
</svg>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "-b",
        "--basemap",
        type=Path,
        default=BASEMAP_PATH,
        help="OSM basemap JSON (optional; map still renders without it)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 1

    payload = json.loads(args.input.read_text())
    map_data = payload.get("map")
    if not map_data:
        print("error: no map data in input", file=sys.stderr)
        return 1

    basemap = None
    if args.basemap.exists():
        basemap = json.loads(args.basemap.read_text())
    else:
        print(f"warning: basemap not found ({args.basemap}); roads/water omitted", file=sys.stderr)

    if not render_starbucks_map(map_data, args.output, basemap):
        print("error: nothing to render", file=sys.stderr)
        return 1

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
