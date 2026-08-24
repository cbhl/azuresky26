#!/usr/bin/env python3
"""Convert Starbucks receipts + GTA catalog into data/starbucks/starbucks.json.

Usage:
    python3 scripts/starbucks_import.py
    python3 scripts/starbucks_import.py -i data/starbucks/receipts.json -o data/starbucks/starbucks.json

Matches receipt store names to the GTA catalog (name-first, storeNumber when
aligned, fuzzy fallback), computes visit/item stats, and embeds a map block
for render_starbucks_map.py. Raw receipts stay gitignored; commit the JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECEIPTS = ROOT / "data" / "starbucks" / "receipts.json"
DEFAULT_ALL_ITEMS = ROOT / "data" / "starbucks" / "all-items.json"
DEFAULT_CATALOG = ROOT / "data" / "starbucks" / "stores-gta.json"
DEFAULT_STANDALONE = ROOT / "data" / "starbucks" / "stores-gta-standalone.json"
DEFAULT_OUTPUT = ROOT / "data" / "starbucks" / "starbucks.json"
DEFAULT_UNMATCHED = ROOT / "data" / "starbucks" / "unmatched-receipts.json"
RECENT_LIMIT = 20
TOP_LIST_LIMIT = 8
FUZZY_THRESHOLD = 0.85

# Covers full GTA standalone set including southern Halton (Burlington).
BBOX = {
    "lat_min": 43.30,
    "lat_max": 44.12,
    "lng_min": -80.05,
    "lng_max": -78.50,
}

ALIASES: dict[str, str] = {}

try:
    from rapidfuzz import fuzz as _rf_fuzz

    def _similarity(a: str, b: str) -> float:
        return _rf_fuzz.ratio(a, b) / 100.0

except ImportError:

    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\band\b", "and", text)
    return text


def normalize_item_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def item_display(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def build_catalog_index(catalog: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_number: dict[str, dict] = {}
    by_norm: dict[str, dict] = {}
    for store in catalog:
        sn = (store.get("storeNumber") or "").strip()
        if sn:
            by_number[sn] = store
        norm = normalize_name(store.get("name") or "")
        if norm and norm not in by_norm:
            by_norm[norm] = store
        amp = normalize_name((store.get("name") or "").replace(" and ", " & "))
        if amp and amp not in by_norm:
            by_norm[amp] = store
    return by_number, by_norm


def match_store(
    receipt_name: str,
    receipt_number: str,
    by_number: dict[str, dict],
    by_norm: dict[str, dict],
    catalog: list[dict],
) -> dict | None:
    sn = (receipt_number or "").strip()
    if sn and sn in by_number:
        return by_number[sn]

    norm = normalize_name(receipt_name)
    if not norm:
        return None

    alias_target = ALIASES.get(norm)
    if alias_target:
        alias_norm = normalize_name(alias_target)
        if alias_norm in by_norm:
            return by_norm[alias_norm]
        for store in catalog:
            if normalize_name(store.get("name") or "") == alias_norm:
                return store

    if norm in by_norm:
        return by_norm[norm]

    best_score = 0.0
    best_store: dict | None = None
    for store in catalog:
        cand = normalize_name(store.get("name") or "")
        if not cand:
            continue
        score = _similarity(norm, cand)
        if score > best_score:
            best_score = score
            best_store = store
    if best_store is not None and best_score >= FUZZY_THRESHOLD:
        return best_store
    return None


def import_receipts(
    receipts: list[dict],
    catalog: list[dict],
    standalone_total: int,
    history_count: int = 0,
) -> tuple[dict, list[dict]]:
    by_number, by_norm = build_catalog_index(catalog)
    match_cache: dict[tuple[str, str], dict | None] = {}

    store_visits: Counter[str] = Counter()
    store_meta: dict[str, dict] = {}
    item_counts: Counter[str] = Counter()
    item_display_forms: dict[str, str] = {}
    visited_keys: set[str] = set()
    standalone_visited_keys: set[str] = set()
    recent_rows: list[dict] = []
    unmatched_first: dict[str, dict] = {}
    matched_count = 0

    for receipt in receipts:
        store_name = (receipt.get("storeName") or "").strip()
        store_number = (receipt.get("storeNumber") or "").strip()
        cache_key = (store_name, store_number)
        if cache_key not in match_cache:
            match_cache[cache_key] = match_store(
                store_name, store_number, by_number, by_norm, catalog
            )
        matched = match_cache[cache_key]

        raw_date = receipt.get("date") or ""
        day = raw_date[:10] if len(raw_date) >= 10 else raw_date

        item_names: list[str] = []
        for purchased in receipt.get("purchasedItems") or []:
            name = purchased.get("name")
            if not name:
                continue
            display = item_display(name)
            key = normalize_item_key(name)
            if not key:
                continue
            item_counts[key] += 1
            item_display_forms.setdefault(key, display)
            item_names.append(display)

        if matched is None:
            if store_name not in unmatched_first:
                unmatched_first[store_name] = {
                    "storeName": store_name,
                    "storeNumber": store_number,
                    "firstSeen": day,
                }
            recent_rows.append(
                {
                    "date": day,
                    "store": store_name or "Unknown",
                    "standalone": False,
                    "region": None,
                    "items": item_names,
                    "_sort": raw_date,
                }
            )
            continue

        matched_count += 1
        key = matched.get("storeNumber") or matched.get("name") or store_name
        store_visits[key] += 1
        if key not in store_meta:
            store_meta[key] = matched
        visited_keys.add(key)
        if matched.get("standalone"):
            standalone_visited_keys.add(key)

        recent_rows.append(
            {
                "date": day,
                "store": matched.get("name") or store_name,
                "standalone": bool(matched.get("standalone")),
                "region": matched.get("region"),
                "items": item_names,
                "_sort": raw_date,
            }
        )

    recent_rows.sort(key=lambda row: row["_sort"], reverse=True)
    recent = [
        {
            "date": row["date"],
            "store": row["store"],
            "standalone": row["standalone"],
            "region": row["region"],
            "items": row["items"],
        }
        for row in recent_rows[:RECENT_LIMIT]
    ]

    top_stores = []
    for key, visits in store_visits.most_common(TOP_LIST_LIMIT):
        meta = store_meta[key]
        top_stores.append(
            {
                "name": meta.get("name") or key,
                "visits": visits,
                "region": meta.get("region"),
            }
        )

    top_items = [
        {"item": item_display_forms[key], "count": count}
        for key, count in item_counts.most_common(TOP_LIST_LIMIT)
    ]

    standalone_visited = len(standalone_visited_keys)
    stores_all = len(visited_keys)

    visited_by_number = {
        (store_meta[k].get("storeNumber") or ""): True for k in visited_keys
    }
    visited_by_name = {
        normalize_name(store_meta[k].get("name") or ""): True for k in visited_keys
    }

    standalone_total_by_region: Counter[str] = Counter()
    standalone_visited_by_region: Counter[str] = Counter()
    for store in catalog:
        if not store.get("standalone"):
            continue
        region = store.get("region") or "Other"
        standalone_total_by_region[region] += 1
        sn = (store.get("storeNumber") or "").strip()
        if (sn and sn in visited_by_number) or normalize_name(
            store.get("name") or ""
        ) in visited_by_name:
            standalone_visited_by_region[region] += 1

    region_order = ["Toronto", "Peel", "York Region", "Halton", "Durham"]
    region_names = [r for r in region_order if r in standalone_total_by_region]
    region_names += [
        r for r in standalone_total_by_region if r not in set(region_names)
    ]
    by_region = [
        {
            "region": region,
            "total": standalone_total_by_region[region],
            "visited": standalone_visited_by_region[region],
        }
        for region in region_names
    ]

    dated = sorted(
        (r.get("date") or "")[:10] for r in receipts if (r.get("date") or "").startswith("20")
    )
    date_range = {"min": dated[0], "max": dated[-1]} if dated else {}

    top_stores = []
    for key, visits in store_visits.most_common(TOP_LIST_LIMIT):
        meta = store_meta[key]
        top_stores.append(
            {
                "name": meta.get("name") or key,
                "storeNumber": meta.get("storeNumber") or "",
                "count": visits,
                "type": "standalone" if meta.get("standalone") else "other",
            }
        )

    top_items = [
        {"item": item_display_forms[key], "count": count}
        for key, count in item_counts.most_common(TOP_LIST_LIMIT)
    ]

    visited_stores = sorted(
        (store_meta[k].get("name") or k)
        for k in standalone_visited_keys
    )

    map_stores = []
    to_visit = []
    for store in catalog:
        sn = (store.get("storeNumber") or "").strip()
        is_standalone = bool(store.get("standalone"))
        visited = bool(
            (sn and sn in visited_by_number)
            or normalize_name(store.get("name") or "") in visited_by_name
        )
        visit_key = sn if sn and sn in store_visits else (store.get("name") or "")
        visits = int(store_visits.get(visit_key) or 0)
        if is_standalone and not visited:
            to_visit.append(
                {
                    "id": sn or (store.get("name") or ""),
                    "name": store.get("name") or "",
                    "street": store.get("street") or "",
                    "city": store.get("city") or "",
                    "region": store.get("region") or "",
                    "address": store.get("address") or "",
                    "lat": store.get("lat"),
                    "lon": store.get("lng"),
                }
            )
        # Map: all standalone + any visited non-standalone only.
        if not is_standalone and not visited:
            continue
        map_stores.append(
            {
                "name": store.get("name") or "",
                "lat": store.get("lat"),
                "lon": store.get("lng"),
                "standalone": is_standalone,
                "visited": visited,
                "visits": visits,
                "region": store.get("region"),
            }
        )

    region_rank = {name: i for i, name in enumerate(region_order)}
    to_visit.sort(
        key=lambda row: (
            region_rank.get(row.get("region") or "", 99),
            (row.get("city") or "").lower(),
            (row.get("name") or "").lower(),
        )
    )

    payload = {
        "generated_at": date.today().isoformat(),
        "date_range": date_range,
        "history_count": history_count,
        "receipt_count": len(receipts),
        "standalone": {
            "total": standalone_total,
            "visited": standalone_visited,
            "remaining": standalone_total - standalone_visited,
        },
        "by_region": by_region,
        "top_items": top_items,
        "top_stores": top_stores,
        "visited_stores": visited_stores,
        "to_visit": to_visit,
        "unmatched": [],
        "recent": recent,
        "map": {
            "bbox": dict(BBOX),
            "stores": map_stores,
        },
    }

    unmatched = sorted(
        unmatched_first.values(),
        key=lambda row: (row.get("firstSeen") or "", row.get("storeName") or ""),
    )
    payload["unmatched"] = unmatched
    return payload, unmatched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", "--input", type=Path, default=DEFAULT_RECEIPTS)
    parser.add_argument(
        "-a",
        "--all-items",
        type=Path,
        default=DEFAULT_ALL_ITEMS,
        dest="all_items",
        help="Full flattened history (all-items.json); used for history_count. Optional.",
    )
    parser.add_argument("-c", "--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--standalone", type=Path, default=DEFAULT_STANDALONE, dest="standalone_path"
    )
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--unmatched", type=Path, default=DEFAULT_UNMATCHED, dest="unmatched_path"
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"error: receipts not found: {args.input}", file=sys.stderr)
        return 1
    if not args.catalog.exists():
        print(f"error: catalog not found: {args.catalog}", file=sys.stderr)
        return 1

    receipts = json.loads(args.input.read_text())
    catalog = json.loads(args.catalog.read_text())
    if args.standalone_path.exists():
        standalone_total = len(json.loads(args.standalone_path.read_text()))
    else:
        standalone_total = sum(1 for s in catalog if s.get("standalone"))

    history_count = 0
    if args.all_items.exists():
        all_items = json.loads(args.all_items.read_text())
        history_count = len(all_items) if isinstance(all_items, list) else 0

    payload, unmatched = import_receipts(
        receipts, catalog, standalone_total, history_count=history_count
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    args.unmatched_path.write_text(json.dumps(unmatched, indent=2) + "\n")

    stats = payload["standalone"]
    print(
        f"Wrote {args.output}: {payload['receipt_count']} transactions, "
        f"{stats['visited']}/{stats['total']} standalone, "
        f"{payload['history_count']} history rows, "
        f"{len(payload['by_region'])} regions, "
        f"{len(payload['top_items'])} top items"
    )
    print(f"Wrote {args.unmatched_path}: {len(unmatched)} unmatched store names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
