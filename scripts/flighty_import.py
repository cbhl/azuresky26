#!/usr/bin/env python3
"""Convert a Flighty CSV export to data/flights.json for the travel section.

Usage:
    python3 scripts/flighty_import.py
    python3 scripts/flighty_import.py -i data/flighty/export.csv -o data/flights.json

Reads Flighty export columns (Date, Airline, Flight, From, To, etc.), skips
canceled flights, and writes sanitized stats plus a recent-flight table.
Raw CSV should stay gitignored; commit only the generated JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "flighty" / "export.csv"
DEFAULT_OUTPUT = ROOT / "data" / "flights.json"
AIRPORTS_PATH = ROOT / "data" / "airports.json"
RECENT_LIMIT = 20
TOP_LIST_LIMIT = 5


def pick(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def is_canceled(row: dict[str, str]) -> bool:
    return pick(row, "Canceled").lower() in {"true", "1", "yes", "y"}


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_miles * math.asin(math.sqrt(a))


def load_airports() -> dict[str, dict]:
    if not AIRPORTS_PATH.exists():
        print(f"warning: {AIRPORTS_PATH} not found; miles and countries may be incomplete", file=sys.stderr)
        return {}
    return json.loads(AIRPORTS_PATH.read_text())


def flight_from_row(row: dict[str, str]) -> dict | None:
    from_code = pick(row, "From")
    to_code = pick(row, "To") or pick(row, "Diverted To")
    flight_date = pick(row, "Date")
    if not from_code or not to_code or not flight_date:
        return None
    flight = {
        "date": flight_date[:10] if len(flight_date) >= 10 else flight_date,
        "airline": pick(row, "Airline"),
        "flight": pick(row, "Flight"),
        "from": from_code,
        "to": to_code,
    }
    aircraft = pick(row, "Aircraft Type Name")
    if aircraft:
        flight["aircraft"] = aircraft
    return flight


def import_csv(input_path: Path, airports: dict[str, dict]) -> dict:
    flights: list[dict] = []
    route_counts: Counter[str] = Counter()
    airline_counts: Counter[str] = Counter()
    aircraft_counts: Counter[str] = Counter()
    airport_visit_counts: Counter[str] = Counter()
    airport_codes: set[str] = set()
    country_codes: set[str] = set()
    total_miles = 0.0
    miles_known = 0

    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if is_canceled(row):
                continue
            flight = flight_from_row(row)
            if not flight:
                continue
            flights.append(flight)
            route = f"{flight['from']}-{flight['to']}"
            route_counts[route] += 1
            if flight["airline"]:
                airline_counts[flight["airline"]] += 1
            if flight.get("aircraft"):
                aircraft_counts[flight["aircraft"]] += 1
            for code in (flight["from"], flight["to"]):
                airport_codes.add(code)
                airport_visit_counts[code] += 1
                info = airports.get(code)
                if info and info.get("country"):
                    country_codes.add(info["country"])
            origin = airports.get(flight["from"])
            dest = airports.get(flight["to"])
            if origin and dest:
                total_miles += haversine_miles(
                    origin["lat"], origin["lon"], dest["lat"], dest["lon"]
                )
                miles_known += 1

    flights.sort(key=lambda f: f["date"], reverse=True)

    top_routes = [
        {"route": route, "count": count}
        for route, count in route_counts.most_common(TOP_LIST_LIMIT)
    ]
    top_airlines = [
        {"airline": airline, "count": count}
        for airline, count in airline_counts.most_common(TOP_LIST_LIMIT)
    ]
    top_aircraft = [
        {"aircraft": aircraft, "count": count}
        for aircraft, count in aircraft_counts.most_common(TOP_LIST_LIMIT)
    ]
    top_airports = [
        {"airport": airport, "count": count}
        for airport, count in airport_visit_counts.most_common(TOP_LIST_LIMIT)
    ]

    map_airports = []
    for code in sorted(airport_codes):
        info = airports.get(code)
        if info:
            entry = {"code": code, "lat": info["lat"], "lon": info["lon"]}
            if info.get("city"):
                entry["city"] = info["city"]
            map_airports.append(entry)

    route_segments: set[tuple[str, str]] = set()
    map_routes = []
    for flight in flights:
        segment = (flight["from"], flight["to"])
        if segment in route_segments:
            continue
        origin = airports.get(flight["from"])
        dest = airports.get(flight["to"])
        if not origin or not dest:
            continue
        route_segments.add(segment)
        map_routes.append(
            {
                "from": flight["from"],
                "to": flight["to"],
                "lat1": origin["lat"],
                "lon1": origin["lon"],
                "lat2": dest["lat"],
                "lon2": dest["lon"],
            }
        )

    return {
        "generated_at": date.today().isoformat(),
        "stats": {
            "flights": len(flights),
            "airports": len(airport_codes),
            "countries": len(country_codes),
            "miles": round(total_miles),
            "top_routes": top_routes,
            "top_airports": top_airports,
            "top_airlines": top_airlines,
            "top_aircraft": top_aircraft,
        },
        "map": {
            "airports": map_airports,
            "routes": map_routes,
        },
        "recent": flights[:RECENT_LIMIT],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        print("Export from Flighty and save as data/flighty/export.csv", file=sys.stderr)
        return 1

    airports = load_airports()
    payload = import_csv(args.input, airports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")

    stats = payload["stats"]
    print(
        f"Wrote {args.output}: {stats['flights']} flights, "
        f"{stats['airports']} airports, {stats['countries']} countries, "
        f"{stats['miles']:,} mi"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
