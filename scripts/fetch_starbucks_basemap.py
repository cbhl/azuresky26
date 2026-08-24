#!/usr/bin/env python3
"""Fetch simplified GTA basemap features from OpenStreetMap (Overpass API).

Writes data/starbucks/basemap.json for render_starbucks_map.py:
  - major roads (motorway/trunk/primary/secondary)
  - water polygons (lakes, large waterways)
  - place labels (city/town)

Usage:
    python3 scripts/fetch_starbucks_basemap.py
    python3 scripts/fetch_starbucks_basemap.py --bbox 43.30,44.12,-80.05,-78.50
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "starbucks" / "basemap.json"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Match starbucks_import.BBOX
DEFAULT_BBOX = (43.30, 44.12, -80.05, -78.50)

USER_AGENT = "michael-chang.ca-starbucks-map/1.0 (personal static site)"


def overpass_query(lat_min: float, lat_max: float, lng_min: float, lng_max: float) -> str:
    # south,west,north,east
    bbox = f"{lat_min},{lng_min},{lat_max},{lng_max}"
    return f"""
[out:json][timeout:180];
(
  way["highway"~"^(motorway|trunk|primary)$"]({bbox});
  way["natural"="water"]["name"]({bbox});
  relation["natural"="water"]["name"]({bbox});
  node["place"~"^(city|town)$"]({bbox});
);
out body;
>;
out skel qt;
"""


def overpass_queries(lat_min: float, lat_max: float, lng_min: float, lng_max: float) -> list[tuple[str, str]]:
    """Split queries so public Overpass mirrors are less likely to 504."""
    bbox = f"{lat_min},{lng_min},{lat_max},{lng_max}"
    return [
        (
            "roads",
            f'[out:json][timeout:120];way["highway"~"^(motorway|trunk|primary)$"]({bbox});out body;>;out skel qt;',
        ),
        (
            "water",
            f'[out:json][timeout:120];(way["natural"="water"]["name"]({bbox});relation["natural"="water"]["name"]({bbox}););out body;>;out skel qt;',
        ),
        (
            "labels",
            f'[out:json][timeout:60];node["place"~"^(city|town)$"]({bbox});out body;',
        ),
    ]


def fetch_overpass(query: str) -> dict:
    data = query.encode("utf-8")
    last_err: Exception | None = None
    for url in (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ):
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
            continue
    assert last_err is not None
    raise last_err


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def simplify_line(coords: list[list[float]], tolerance: float) -> list[list[float]]:
    """Ramer–Douglas–Peucker on open [lon, lat] polylines."""
    if len(coords) < 3:
        return coords
    pts = [(float(c[0]), float(c[1])) for c in coords]

    def rdp(points: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
        if len(points) < 3:
            return points
        start, end = points[0], points[-1]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        denom = math.hypot(dx, dy) or 1.0
        max_d = -1.0
        idx = 0
        for i in range(1, len(points) - 1):
            px, py = points[i]
            d = abs(dy * px - dx * py + end[0] * start[1] - end[1] * start[0]) / denom
            if d > max_d:
                max_d = d
                idx = i
        if max_d > eps:
            left = rdp(points[: idx + 1], eps)
            right = rdp(points[idx:], eps)
            return left[:-1] + right
        return [start, end]

    simplified = rdp(pts, tolerance)
    out: list[list[float]] = []
    for lon, lat in simplified:
        if not out or _dist((out[-1][0], out[-1][1]), (lon, lat)) > 1e-9:
            out.append([lon, lat])
    return out


def simplify_ring(coords: list[list[float]], tolerance: float) -> list[list[float]]:
    """Simplify a closed ring; open it first so RDP is not given start==end."""
    if len(coords) < 4:
        return coords
    closed = coords[0] == coords[-1] or _dist(
        (float(coords[0][0]), float(coords[0][1])),
        (float(coords[-1][0]), float(coords[-1][1])),
    ) < 1e-9
    open_coords = coords[:-1] if closed else coords
    simplified = simplify_line(open_coords, tolerance)
    if len(simplified) < 3:
        return coords if closed else simplified
    if closed:
        simplified = simplified + [simplified[0][:]]
    return simplified


def path_length(coords: list[list[float]]) -> float:
    total = 0.0
    for a, b in zip(coords, coords[1:]):
        total += _dist((a[0], a[1]), (b[0], b[1]))
    return total


def _endpoint_key(pt: list[float], decimals: int = 4) -> tuple[float, float]:
    """Snap endpoints so adjacent OSM ways join (≈11m at GTA latitude)."""
    return (round(float(pt[0]), decimals), round(float(pt[1]), decimals))


def merge_road_segments(segments: list[dict]) -> list[dict]:
    """Join OSM way stubs that share endpoints into continuous polylines.

    Uses endpoint hashing + iterative degree-2 chaining (linear-ish), not
    pairwise search — OSM motorways arrive as thousands of short ways.
    """
    if not segments:
        return []

    by_class: dict[str, list[dict]] = {}
    for seg in segments:
        by_class.setdefault(seg.get("class") or "primary", []).append(seg)

    merged: list[dict] = []
    for cls, group in by_class.items():
        # Each chain is a list of points; track free ends in a hash map.
        chains: list[list[list[float]] | None] = []
        names: list[str] = []
        ends: dict[tuple[float, float], list[tuple[int, str]]] = {}

        def add_end(cid: int, which: str, pt: list[float]) -> None:
            ends.setdefault(_endpoint_key(pt), []).append((cid, which))

        def remove_end(cid: int, which: str, pt: list[float]) -> None:
            k = _endpoint_key(pt)
            lst = ends.get(k)
            if not lst:
                return
            ends[k] = [e for e in lst if e != (cid, which)]
            if not ends[k]:
                del ends[k]

        for seg in group:
            coords = [list(p) for p in seg["coords"]]
            if len(coords) < 2:
                continue
            cid = len(chains)
            chains.append(coords)
            names.append(seg.get("name") or "")
            add_end(cid, "start", coords[0])
            add_end(cid, "end", coords[-1])

        changed = True
        while changed:
            changed = False
            for key, occupants in list(ends.items()):
                if len(occupants) < 2:
                    continue
                # Join first two live ends at this node.
                (i, ei), (j, ej) = occupants[0], occupants[1]
                if i == j:
                    continue
                pi, pj = chains[i], chains[j]
                if pi is None or pj is None:
                    continue

                # Detach old endpoints.
                remove_end(i, "start", pi[0])
                remove_end(i, "end", pi[-1])
                remove_end(j, "start", pj[0])
                remove_end(j, "end", pj[-1])

                if ei == "end" and ej == "start":
                    new_pts = pi + pj[1:]
                elif ei == "start" and ej == "end":
                    new_pts = pj + pi[1:]
                elif ei == "end" and ej == "end":
                    new_pts = pi + list(reversed(pj))[1:]
                else:  # start + start
                    new_pts = list(reversed(pj)) + pi[1:]

                chains[i] = new_pts
                chains[j] = None
                if names[j] and not names[i]:
                    names[i] = names[j]
                add_end(i, "start", new_pts[0])
                add_end(i, "end", new_pts[-1])
                changed = True
                break

        for i, pts in enumerate(chains):
            if pts is not None and len(pts) >= 2:
                merged.append({"class": cls, "name": names[i], "coords": pts})
    return merged


def finalize_roads(segments: list[dict]) -> list[dict]:
    """Merge stubs, gently simplify, drop tiny leftovers."""
    merged = merge_road_segments(segments)
    # Gentle RDP — keep curvature of freeways/arterials visible at city scale.
    tol = {"motorway": 0.0008, "trunk": 0.0009, "primary": 0.0012}
    min_len = {"motorway": 0.008, "trunk": 0.01, "primary": 0.015}
    out: list[dict] = []
    for seg in merged:
        cls = seg.get("class") or "primary"
        coords = simplify_line(seg["coords"], tolerance=tol.get(cls, 0.001))
        if len(coords) < 2:
            continue
        if path_length(coords) < min_len.get(cls, 0.015):
            continue
        out.append({"class": cls, "name": seg.get("name") or "", "coords": coords})
    return out


def elements_to_basemap(payload: dict) -> dict:
    nodes: dict[int, tuple[float, float]] = {}
    ways: dict[int, dict] = {}
    relations: list[dict] = []

    for el in payload.get("elements") or []:
        et = el.get("type")
        if et == "node":
            nodes[el["id"]] = (float(el["lon"]), float(el["lat"]))
        elif et == "way":
            # Prefer versions that still carry tags (body over skel).
            prev = ways.get(el["id"])
            if prev is None or (el.get("tags") and not prev.get("tags")):
                ways[el["id"]] = el
            elif prev is not None and el.get("nodes") and not prev.get("nodes"):
                ways[el["id"]] = el
        elif et == "relation":
            relations.append(el)

    road_segments: list[dict] = []
    water: list[dict] = []
    labels: list[dict] = []

    road_classes = {
        "motorway": "motorway",
        "trunk": "trunk",
        "primary": "primary",
    }

    for way in ways.values():
        tags = way.get("tags") or {}
        nds = way.get("nodes") or []
        coords = []
        for nid in nds:
            if nid in nodes:
                lon, lat = nodes[nid]
                coords.append([lon, lat])
        if len(coords) < 2:
            continue

        highway = tags.get("highway")
        if highway in road_classes:
            # Keep full geometry here; merge + simplify in finalize_roads.
            road_segments.append(
                {
                    "class": road_classes[highway],
                    "name": tags.get("name") or tags.get("ref") or "",
                    "coords": coords,
                }
            )
            continue

        if tags.get("natural") == "water" or tags.get("water") in {
            "lake",
            "reservoir",
            "pond",
            "bay",
        }:
            if coords[0] != coords[-1]:
                coords = coords + [coords[0]]
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            if (max(lons) - min(lons)) * (max(lats) - min(lats)) < 3e-4:
                continue
            simplified = simplify_ring(coords, tolerance=0.003)
            if len(simplified) >= 4:
                water.append({"coords": [simplified]})

    roads = finalize_roads(road_segments)

    # Relations: outer rings only for water
    for rel in relations:
        tags = rel.get("tags") or {}
        if not (
            tags.get("natural") == "water"
            or tags.get("water") in {"lake", "reservoir", "pond", "bay"}
        ):
            continue
        rings: list[list[list[float]]] = []
        for member in rel.get("members") or []:
            if member.get("type") != "way" or member.get("role") not in ("outer", ""):
                continue
            way = ways.get(member.get("ref"))
            if not way:
                continue
            coords = []
            for nid in way.get("nodes") or []:
                if nid in nodes:
                    lon, lat = nodes[nid]
                    coords.append([lon, lat])
            if len(coords) < 3:
                continue
            if coords[0] != coords[-1]:
                coords = coords + [coords[0]]
            simplified = simplify_ring(coords, tolerance=0.002)
            if len(simplified) >= 4:
                rings.append(simplified)
        if rings:
            water.append({"coords": rings})

    # Place labels from nodes that have tags (original nodes with place=*)
    for el in payload.get("elements") or []:
        if el.get("type") != "node":
            continue
        tags = el.get("tags") or {}
        place = tags.get("place")
        name = tags.get("name")
        if place not in ("city", "town") or not name:
            continue
        labels.append(
            {
                "name": name,
                "place": place,
                "lon": float(el["lon"]),
                "lat": float(el["lat"]),
            }
        )

    # Prefer cities; drop dense towns that collide by name proximity
    labels.sort(key=lambda L: (0 if L["place"] == "city" else 1, L["name"]))
    kept: list[dict] = []
    for lab in labels:
        too_close = False
        for k in kept:
            if _dist((k["lon"], k["lat"]), (lab["lon"], lab["lat"])) < 0.08:
                too_close = True
                break
        if not too_close:
            kept.append(lab)

    return {"roads": roads, "water": water, "labels": kept}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bbox",
        type=str,
        default=",".join(str(x) for x in DEFAULT_BBOX),
        help="lat_min,lat_max,lng_min,lng_max",
    )
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    parts = [float(x) for x in args.bbox.split(",")]
    if len(parts) != 4:
        print("error: bbox must be lat_min,lat_max,lng_min,lng_max", file=sys.stderr)
        return 1
    lat_min, lat_max, lng_min, lng_max = parts

    query_parts = overpass_queries(lat_min, lat_max, lng_min, lng_max)
    print("Fetching Overpass basemap (split queries)…", flush=True)
    merged: dict = {"elements": []}
    try:
        for name, query in query_parts:
            print(f"  {name}…", flush=True)
            part = fetch_overpass(query)
            merged["elements"].extend(part.get("elements") or [])
    except urllib.error.HTTPError as exc:
        print(f"error: Overpass HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"error: Overpass request failed: {exc.reason}", file=sys.stderr)
        return 1

    basemap = elements_to_basemap(merged)
    basemap["bbox"] = {
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lng_min": lng_min,
        "lng_max": lng_max,
    }
    basemap["source"] = "OpenStreetMap contributors (Overpass)"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(basemap, separators=(",", ":")) + "\n")
    print(
        f"Wrote {args.output}: {len(basemap['roads'])} roads, "
        f"{len(basemap['water'])} water, {len(basemap['labels'])} labels"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
