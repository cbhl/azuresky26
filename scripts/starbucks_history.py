#!/usr/bin/env python3
"""Parse Starbucks sources into the durable, source-preserving ledger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
NON_PURCHASES = {"reload balance", "automatic reload", "lsus", "lsca"}


def key(value: str | None) -> str:
    text = (value or "").strip().lower().replace("&", " and ")
    text = re.sub(r"\s+", " ", text)
    # Food Court is the stable spelling used by the catalogue/API aliases.
    return text.replace(" food c", " food court")


def stable_id(*values: object) -> str:
    raw = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return "evt_" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def api_time(value: str) -> tuple[str, str]:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    local = instant.astimezone(TORONTO)
    return local.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S"), local.date().isoformat()


def parse_report(path: Path, source: str, currency: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Return physical observations and derived report order groups."""
    observations: list[dict] = []
    rewards: list[dict] = []
    section = None
    previous: dict | None = None
    group_number = 0
    for line_number, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        row = [cell.strip() for cell in next(csv.reader([raw]))]
        heading = re.sub(r"[^a-z ]", "", raw.lower()).strip()
        if heading.startswith("purchase transactions"):
            section, previous = "purchases", None
            continue
        if heading.startswith("rewards transactions"):
            section, previous = "rewards", None
            continue
        # Reports have changed their introductory/header rows over time. Do
        # not rely on a fixed line number or on the header's exact spelling.
        if section == "purchases" and len(row) >= 4 and "date" in row[0].lower():
            continue
        if section == "rewards" and len(row) >= 3 and "date" in row[0].lower():
            continue
        if section == "purchases" and len(row) == 4:
            timestamp, store, amount, item = row
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", timestamp):
                continue
            item_key = key(item)
            activity = item_key if not store else None
            kind = "purchase_item" if store and item else ("account_activity" if activity in {"reload balance", "automatic reload"} else "unknown_account_activity")
            oid = f"{source}:line:{line_number}"
            observation = {
                "observation_id": oid, "record_type": "purchase_line", "source_kind": source,
                "source_row_number": line_number, "occurred_at": timestamp,
                "occurred_at_precision": "second", "time_basis": "local_wall",
                "local_date": timestamp[:10], "local_second": timestamp, "store_name_raw": store or None,
                "store_key": key(store) or None, "profile_country": "US" if source.startswith("us_") else "CA",
                "currency": currency, "kind": kind, "activity_type": activity,
                "raw_item_name": item or None, "line_amount": amount or None,
                "status": "active",
            }
            observations.append(observation)
            if kind == "purchase_item":
                group_key = (timestamp, key(store))
                if previous and previous["group_key"] == group_key:
                    previous["observations"].append(observation)
                else:
                    group_number += 1
                    previous = {"group_key": group_key, "observations": [observation], "source": source, "number": group_number}
            else:
                previous = None
        elif section == "rewards" and len(row) == 3:
            earned, amount, point_type = row
            if earned != "None" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", earned):
                continue
            try:
                delta = float(amount)
            except ValueError:
                continue
            rewards.append({
                "star_id": stable_id(source, line_number, earned, amount, point_type),
                "occurred_on": None if earned == "None" else earned, "occurred_on_precision": "day",
                "stars_delta": delta, "point_type": point_type, "source_kind": source,
                "source_observation_id": f"{source}:line:{line_number}", "status": "active",
            })
    groups = []
    for group in _report_groups(observations):
        rows = group["rows"]
        groups.append({
            "visit_id": stable_id(source, [r["observation_id"] for r in rows]), "status": "active",
            "occurred_at": rows[0]["occurred_at"], "occurred_at_precision": "second", "time_basis": "local_wall",
            "local_date": rows[0]["local_date"], "source_profile_countries": sorted({r["profile_country"] for r in rows}),
            "currency": rows[0]["currency"], "amount_lines_sum": _sum_amounts(r["line_amount"] for r in rows),
            "store": {"name_raw": rows[0]["store_name_raw"], "name_key": rows[0]["store_key"], "catalog_store_number": None,
                      "in_gta_catalog": False, "standalone": False, "region": None, "match_method": "unresolved"},
            "items": [{"name": r["raw_item_name"], "name_key": key(r["raw_item_name"]), "quantity": None} for r in rows],
            "source_kinds": [source], "source_observation_ids": [r["observation_id"] for r in rows],
            "dedupe": {"method": "adjacent_same_timestamp_and_store", "confidence": "heuristic"},
        })
    return observations, rewards, groups


def _report_groups(observations: list[dict]):
    current = None
    for observation in observations:
        if observation["kind"] != "purchase_item":
            current = None
            continue
        signature = (observation["occurred_at"], observation["store_key"])
        if current is None or current["signature"] != signature:
            current = {"signature": signature, "rows": []}
            yield current
        current["rows"].append(observation)


def _sum_amounts(values) -> str | None:
    try:
        return f"{sum(float(v) for v in values if v):.2f}"
    except (TypeError, ValueError):
        return None


def api_visits(receipts: list[dict]) -> tuple[list[dict], list[dict]]:
    observations, visits = [], []
    used_ids: set[str] = set()
    for receipt in receipts:
        hid = str(receipt.get("historyId") or "")
        occurred = receipt.get("date") or ""
        if not hid or not occurred:
            continue
        local_second, day = api_time(occurred)
        # historyId is the durable API identity. Include the receipt/check ID
        # when available, and disambiguate malformed exports deterministically.
        native_id = str(receipt.get("checkId") or receipt.get("receiptId") or hid)
        oid = f"api_export:history:{hid}" if native_id == hid else f"api_export:history:{hid}:receipt:{native_id}"
        if oid in used_ids:
            oid = f"{oid}:{stable_id(receipt)[:12]}"
        used_ids.add(oid)
        store = (receipt.get("storeName") or "").strip()
        observation = {"observation_id": oid, "record_type": "api_receipt", "source_kind": "api_export",
                       "occurred_at": occurred, "occurred_at_precision": "second", "time_basis": "utc",
                       "local_date": day, "local_second": local_second, "profile_country": "CA",
                       "currency": "CAD", "store_name_raw": store or None, "store_key": key(store),
                       "kind": "purchase_item", "status": "active",
                       "raw_item_names": [i.get("name") for i in receipt.get("purchasedItems", []) if i.get("name")]}
        observations.append(observation)
        items = [{"name": i["name"].strip(), "name_key": key(i["name"]), "quantity": None}
                 for i in receipt.get("purchasedItems", []) if i.get("name") and i["name"].strip()]
        # An API activity without product lines is retained as an observation,
        # but cannot be a canonical visit under the history contract.
        if not items:
            continue
        visits.append({"visit_id": stable_id("api", hid), "status": "active", "occurred_at": occurred,
                       "occurred_at_precision": "second", "time_basis": "utc", "local_date": day, "local_second": local_second,
                       "source_profile_countries": ["CA"], "currency": "CAD", "amount_lines_sum": None,
                       "amount_order_total": receipt.get("total"), "store": {"name_raw": store, "name_key": key(store),
                       "catalog_store_number": receipt.get("storeNumber"), "in_gta_catalog": False, "standalone": False,
                       "region": None, "match_method": "unresolved"},
                        "items": items,
                       "source_kinds": ["api_export"], "source_observation_ids": [oid],
                       "dedupe": {"method": "api_identity", "confidence": "exact"}})
    return observations, visits


def _merge(visits: list[dict]) -> list[dict]:
    result: list[dict] = []
    for visit in visits:
        ids = set(visit.get("source_observation_ids", []))
        match = next((old for old in result if ids & set(old.get("source_observation_ids", []))), None)
        if match is None and visit.get("time_basis") == "utc":
            candidates = [old for old in result if old.get("time_basis") == "local_wall"
                          and old.get("local_second") == visit.get("local_second")
                          and old.get("store", {}).get("name_key") == visit.get("store", {}).get("name_key")]
            # Never collapse two report orders merely because the API has a
            # matching second; only a unique reconciliation is safe.
            if len(candidates) == 1:
                match = candidates[0]
        if match is None:
            result.append(visit)
            continue
        match["source_kinds"] = sorted(set(match.get("source_kinds", []) + visit.get("source_kinds", [])))
        match["source_observation_ids"] = sorted(set(match.get("source_observation_ids", []) + visit.get("source_observation_ids", [])))
        if not (match.get("store") or {}).get("name_key") and (visit.get("store") or {}).get("name_key"):
            match["store"] = visit["store"]
        if not match.get("occurred_at") and visit.get("occurred_at"):
            match["occurred_at"] = visit["occurred_at"]
        if not match.get("local_second") and visit.get("local_second"):
            match["local_second"] = visit["local_second"]
        known = {i.get("name_key") for i in match.get("items", [])}
        match["items"] += [i for i in visit.get("items", []) if i.get("name_key") not in known]
        if visit.get("amount_order_total") is not None:
            match["amount_order_total"] = visit["amount_order_total"]
        match["dedupe"] = {"method": "confirmed_local_second_store", "confidence": "high"}
    return sorted(result, key=lambda v: (v.get("local_date", ""), v.get("occurred_at", ""), v["visit_id"]))


def _canonicalize_legacy(visit: dict) -> dict:
    """Upgrade the previous committed shape without losing its source IDs."""
    source_kinds = visit.get("source_kinds") or ([visit.get("source_kind")] if visit.get("source_kind") else ["unknown"])
    source = source_kinds[0]
    ids = visit.get("source_observation_ids") or [stable_id(source, visit.get("visit_id"))]
    store_name = visit.get("store") if isinstance(visit.get("store"), str) else None
    return {
        "visit_id": visit.get("visit_id") or stable_id(source, ids), "status": "active",
        "occurred_at": visit.get("occurred_at"), "occurred_at_precision": "second",
        "time_basis": "utc" if source == "api_export" else "local_wall",
        "local_date": visit.get("local_date") or (visit.get("occurred_at") or "")[:10],
        "local_second": visit.get("local_second") or visit.get("occurred_at"),
        "source_profile_countries": ["CA"] if source == "api_export" else (["US"] if source.startswith("us_") else ["CA"]),
        "currency": visit.get("currency"), "amount_lines_sum": visit.get("amount_lines_sum"),
        "amount_order_total": visit.get("amount_order_total"),
        "store": {"name_raw": store_name, "name_key": key(store_name), "catalog_store_number": None,
                  "in_gta_catalog": False, "standalone": False, "region": None, "match_method": "unresolved"},
        "items": [{k: item.get(k) for k in ("name", "name_key", "quantity")} for item in visit.get("items", [])],
        "source_kinds": sorted(set(source_kinds)),
        "source_observation_ids": ids, "dedupe": visit.get("dedupe", {"method": "source_identity", "confidence": "exact"}),
    }


def events_from_receipts(receipts: list[dict]) -> list[dict]:
    """Compatibility adapter used by the incremental fetcher."""
    return api_visits(receipts)[1]


def build_history(report_paths: list[tuple[Path, str, str]], receipts_path: Path | None) -> dict:
    observations, visits, stars = [], [], []
    for path, source, currency in report_paths:
        report_observations, report_stars, report_visits = parse_report(path, source, currency)
        observations += report_observations; stars += report_stars; visits += report_visits
    if receipts_path and receipts_path.exists():
        api_observations, api_orders = api_visits(json.loads(receipts_path.read_text()))
        observations += api_observations; visits += api_orders
    return {"schema_version": 1, "activity_timezone": "America/Toronto",
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "sources": sorted({o["source_kind"] for o in observations}), "observations": observations,
            "visits": _merge(visits), "stars": stars}


def merge_history(path: Path, receipts: list[dict]) -> dict:
    old = json.loads(path.read_text()) if path.exists() else build_history([], None)
    old["visits"] = [v for v in (_canonicalize_legacy(v) for v in old.get("visits", []))
                     if v.get("status", "active") == "active" and v.get("items")]
    # Older ledgers had source IDs on visits but no observation collection.
    old.setdefault("observations", [])
    for observation in old["observations"]:
        # Complete observations imported from the pre-ledger projection while
        # retaining their stable IDs and source provenance.
        observation.setdefault("record_type", "legacy_source_observation")
        observation.setdefault("source_kind", "unknown")
        observation.setdefault("status", "active")
    known = {o.get("observation_id") for o in old["observations"]}
    for visit in old["visits"]:
        for source_id in visit.get("source_observation_ids", []):
            if source_id not in known:
                old["observations"].append({"observation_id": source_id, "record_type": "legacy_source_observation",
                                             "source_kind": visit["source_kinds"][0], "status": "active"})
                known.add(source_id)
    # Accept either raw cached receipts or the canonical events adapter used
    # by older fetch scripts.
    if receipts and receipts[0].get("source_observation_ids"):
        incoming = receipts
        observations = [
            {"observation_id": source_id, "record_type": "api_receipt",
             "source_kind": "api_export", "status": "active"}
            for visit in incoming
            for source_id in visit.get("source_observation_ids", [])
        ]
    else:
        observations, incoming = api_visits(receipts)
    existing_by_id = {o.get("observation_id"): o for o in old["observations"]}
    for observation in observations:
        current = existing_by_id.get(observation["observation_id"])
        if current is None:
            old["observations"].append(observation)
            existing_by_id[observation["observation_id"]] = observation
        else:
            # A cached legacy observation can be enriched by a later receipt
            # fetch, but its identity and original record are retained.
            for field, value in observation.items():
                current.setdefault(field, value)
    old["visits"] = _merge(old.get("visits", []) + incoming)
    old["sources"] = sorted(set(old.get("sources", [])) | {o.get("source_kind") for o in old["observations"] if o.get("source_kind")})
    old["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps(old, indent=2, ensure_ascii=False) + "\n")
    return old


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--us-report", type=Path); parser.add_argument("--ca-report", type=Path)
    parser.add_argument("--receipts", type=Path); parser.add_argument("-o", "--output", type=Path, default=Path("data/starbucks/history.json"))
    args = parser.parse_args()
    reports = []
    if args.us_report: reports.append((args.us_report, "us_customer_information_report", "USD"))
    if args.ca_report: reports.append((args.ca_report, "ca_customer_information_report", "CAD"))
    ledger = build_history(reports, args.receipts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {args.output}: {len(ledger['visits'])} visits, {len(ledger['stars'])} Stars entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
