#!/usr/bin/env python3
"""Render flight routes to a static SVG using Web Mercator and great-circle arcs.

Usage:
    python3 scripts/render_travel_map.py
    python3 scripts/render_travel_map.py -i data/flights.json -o static/images/travel-map.svg
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "flights.json"
DEFAULT_OUTPUT = ROOT / "static" / "images" / "travel-map.svg"
LAND_PATH = ROOT / "data" / "ne_110m_land.geojson"
COASTLINE_PATH = ROOT / "data" / "ne_110m_coastline.geojson"

WIDTH = 720
HEIGHT = 360
VIEW_MIN_LAT = -58.0  # crop Antarctica
VIEW_MAX_LAT = 72.0  # crop Arctic (routes peak ~64°N)
ROUTE_SAMPLES = 64

# Light palette that reads on the site's dark and light backgrounds.
OCEAN = "#d8e6f2"
LAND_FILL = "#ebe7df"
COAST_STROKE = "#8b949c"
ROUTE_STROKE = "#0070e0"
AIRPORT_FILL = "#0070e0"
AIRPORT_STROKE = "#004080"
GRATICULE = "rgba(0,0,0,0.08)"


def normalize_lon(lon: float) -> float:
    return ((lon + 180) % 360) - 180


def mercator_y(lat: float) -> float:
    lat = max(min(lat, VIEW_MAX_LAT), VIEW_MIN_LAT)
    lat_rad = math.radians(lat)
    return math.log(math.tan(math.pi / 4 + lat_rad / 2))


_Y_MAX = mercator_y(VIEW_MAX_LAT)
_Y_MIN = mercator_y(VIEW_MIN_LAT)
_Y_SPAN = _Y_MAX - _Y_MIN


def project_x(lon: float) -> float:
    if lon >= 180:
        return float(WIDTH)
    if lon <= -180:
        return 0.0
    return (normalize_lon(lon) + 180) / 360 * WIDTH


def project(lat: float, lon: float) -> tuple[float, float]:
    lat = max(min(lat, VIEW_MAX_LAT), VIEW_MIN_LAT)
    x = project_x(lon)
    y = (1 - (mercator_y(lat) - _Y_MIN) / _Y_SPAN) * HEIGHT
    return x, y


def latlon_to_xyz(lat: float, lon: float) -> tuple[float, float, float]:
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    return (
        math.cos(lat_r) * math.cos(lon_r),
        math.cos(lat_r) * math.sin(lon_r),
        math.sin(lat_r),
    )


def xyz_to_latlon(x: float, y: float, z: float) -> tuple[float, float]:
    lat = math.degrees(math.atan2(z, math.sqrt(x * x + y * y)))
    lon = math.degrees(math.atan2(y, x))
    return lat, normalize_lon(lon)


def great_circle_points(
    lat1: float, lon1: float, lat2: float, lon2: float, samples: int = ROUTE_SAMPLES
) -> list[tuple[float, float]]:
    x1, y1, z1 = latlon_to_xyz(lat1, lon1)
    x2, y2, z2 = latlon_to_xyz(lat2, lon2)
    dot = max(-1.0, min(1.0, x1 * x2 + y1 * y2 + z1 * z2))
    d = math.acos(dot)
    if d < 1e-12:
        return [(lat1, normalize_lon(lon1))]

    points: list[tuple[float, float]] = []
    sin_d = math.sin(d)
    for i in range(samples + 1):
        f = i / samples
        a = math.sin((1 - f) * d) / sin_d
        b = math.sin(f * d) / sin_d
        x = a * x1 + b * x2
        y = a * y1 + b * y2
        z = a * z1 + b * z2
        points.append(xyz_to_latlon(x, y, z))
    return points


def split_at_antimeridian(points: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    if not points:
        return []

    segments: list[list[tuple[float, float]]] = [[points[0]]]
    for lat, lon in points[1:]:
        lon = normalize_lon(lon)
        prev_lat, prev_lon = segments[-1][-1]
        prev_lon = normalize_lon(prev_lon)

        lon_u = lon
        while lon_u - prev_lon > 180:
            lon_u -= 360
        while lon_u - prev_lon < -180:
            lon_u += 360

        if lon_u > 180 or lon_u < -180:
            boundary = 180.0 if lon_u > prev_lon else -180.0
            t = (boundary - prev_lon) / (lon_u - prev_lon)
            cross_lat = prev_lat + t * (lat - prev_lat)
            segments[-1].append((cross_lat, boundary))
            # Same meridian, opposite map edge (±180 project to right/left).
            segments.append([(cross_lat, -boundary), (lat, lon)])
        elif abs(lon - prev_lon) > 180:
            boundary = 180.0 if lon > prev_lon else -180.0
            t = (boundary - prev_lon) / (lon - prev_lon)
            cross_lat = prev_lat + t * (lat - prev_lat)
            segments[-1].append((cross_lat, boundary))
            segments.append([(cross_lat, -boundary), (lat, lon)])
        else:
            segments[-1].append((lat, lon))

    return segments


def path_for_segments(segments: Iterable[list[tuple[float, float]]], close: bool = False) -> str:
    parts: list[str] = []
    for segment in segments:
        if len(segment) < 2:
            continue
        subpaths: list[str] = []
        prev_x, prev_y = project(*segment[0])
        current = f"M {prev_x:.2f} {prev_y:.2f}"
        for lat, lon in segment[1:]:
            x, y = project(lat, lon)
            if abs(x - prev_x) > WIDTH * 0.5:
                if len(current) > 1:
                    subpaths.append(current)
                current = f"M {x:.2f} {y:.2f}"
            else:
                current += f" L {x:.2f} {y:.2f}"
            prev_x, prev_y = x, y
        if close and segment and len(segment) >= 3:
            current += " Z"
        if len(current) > 1:
            subpaths.append(current)
        parts.extend(subpaths)
    return " ".join(parts)


def latlon_ring(coords: list) -> list[tuple[float, float]]:
    return [
        (pt[1], normalize_lon(pt[0]))
        for pt in coords
        if VIEW_MIN_LAT <= pt[1] <= VIEW_MAX_LAT
    ]


def ring_outside_view(ring: list) -> bool:
    lats = [pt[1] for pt in ring]
    return max(lats) < VIEW_MIN_LAT or min(lats) > VIEW_MAX_LAT


def geometry_line_paths(geom: dict) -> list[str]:
    gtype = geom["type"]
    coords = geom["coordinates"]
    paths: list[str] = []

    if gtype == "LineString":
        linestrings = [coords]
    elif gtype == "MultiLineString":
        linestrings = coords
    else:
        return paths

    for line in linestrings:
        if ring_outside_view(line):
            continue
        ring = latlon_ring(line)
        if len(ring) < 2:
            continue
        for segment in split_at_antimeridian(ring):
            path = path_for_segments([segment])
            if path:
                paths.append(path)
    return paths


def geometry_land_paths(geom: dict) -> list[str]:
    gtype = geom["type"]
    coords = geom["coordinates"]
    polygons: list = []

    if gtype == "Polygon":
        polygons = [coords]
    elif gtype == "MultiPolygon":
        polygons = coords
    else:
        return []

    paths: list[str] = []
    for polygon in polygons:
        for ring in polygon:
            if ring_outside_view(ring):
                continue
            ring_pts = latlon_ring(ring)
            if len(ring_pts) < 2:
                continue
            for segment in split_at_antimeridian(ring_pts):
                path = path_for_segments([segment], close=len(segment) >= 3)
                if path:
                    paths.append(path)
    return paths


def load_land_paths() -> list[str]:
    if not LAND_PATH.exists():
        return []
    data = json.loads(LAND_PATH.read_text())
    paths: list[str] = []
    for feature in data.get("features", []):
        paths.extend(geometry_land_paths(feature["geometry"]))
    return paths


def load_coastline_paths() -> list[str]:
    if not COASTLINE_PATH.exists():
        return []
    data = json.loads(COASTLINE_PATH.read_text())
    paths: list[str] = []
    for feature in data.get("features", []):
        paths.extend(geometry_line_paths(feature["geometry"]))
    return paths


def graticule_paths() -> str:
    lines: list[str] = []
    for lon in range(-180, 181, 30):
        x, _ = project(0, lon)
        lines.append(f'M {x:.2f} 0 L {x:.2f} {HEIGHT:.2f}')
    for lat in range(-60, 73, 30):
        _, y = project(lat, 0)
        lines.append(f'M 0 {y:.2f} L {WIDTH:.2f} {y:.2f}')
    return " ".join(lines)


def render_travel_map(map_data: dict, output_path: Path) -> bool:
    routes = map_data.get("routes") or []
    airports = map_data.get("airports") or []
    if not routes:
        return False

    route_paths: list[str] = []
    for route in routes:
        points = great_circle_points(route["lat1"], route["lon1"], route["lat2"], route["lon2"])
        for segment in split_at_antimeridian(points):
            path = path_for_segments([segment])
            if path:
                route_paths.append(path)

    airport_dots: list[str] = []
    for airport in airports:
        x, y = project(airport["lat"], airport["lon"])
        title = airport["code"]
        if airport.get("city"):
            title = f"{airport['code']} ({airport['city']})"
        airport_dots.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" fill="{AIRPORT_FILL}" '
            f'stroke="{AIRPORT_STROKE}" stroke-width="1">'
            f"<title>{escape(title)}</title></circle>"
        )

    land_paths = load_land_paths()
    coastline_paths = load_coastline_paths()
    land_layer = ""
    if land_paths:
        land_layer = (
            f'<g fill="{LAND_FILL}" fill-rule="evenodd" stroke="none">'
            f'<path d="{" ".join(land_paths)}"/></g>'
        )
    coast_layer = ""
    if coastline_paths:
        coast_layer = (
            f'<g fill="none" stroke="{COAST_STROKE}" stroke-width="0.6">'
            f'{" ".join(f"<path d=\"{path}\"/>" for path in coastline_paths)}</g>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-label="Great-circle flight routes on a Web Mercator world map">
  <rect width="100%" height="100%" fill="{OCEAN}"/>
  {land_layer}
  {coast_layer}
  <g stroke="{GRATICULE}" stroke-width="0.5" fill="none">{graticule_paths()}</g>
  <g stroke="{ROUTE_STROKE}" stroke-width="1.25" stroke-opacity="0.55" fill="none">
    {" ".join(f'<path d="{path}"/>' for path in route_paths)}
  </g>
  <g>
    {"".join(airport_dots)}
  </g>
</svg>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 1

    payload = json.loads(args.input.read_text())
    map_data = payload.get("map")
    if not map_data:
        print("error: no map data in input", file=sys.stderr)
        return 1

    if not render_travel_map(map_data, args.output):
        print("error: nothing to render", file=sys.stderr)
        return 1

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
