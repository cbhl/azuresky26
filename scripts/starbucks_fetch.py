#!/usr/bin/env python3
"""Fetch Starbucks transaction history + itemized receipts (session cookie).

Usage:
    python3 scripts/starbucks_fetch.py
    python3 scripts/starbucks_fetch.py --cookie-file PATH

Reads the live session cookie from repo-root get-transaction-history.sh
(the -b '...' curl option). Do not execute that shell file (first line is a
typo). Override the cookie source with --cookie-file.

Writes (owned by this script; safe to re-run):
    data/starbucks/page-<offset>.json   raw history pages
    data/starbucks/all-items.json       flattened non-null history items
    data/starbucks/receipts.json        itemized Redemption receipts (incremental)
    data/starbucks/receipt-errors.json  failed receipt fetches (merged)

After a successful fetch, rebuild site data with:
    python3 scripts/starbucks_import.py
    zola build
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from starbucks_history import merge_history

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "starbucks"
DEFAULT_COOKIE_FILE = ROOT / "get-transaction-history.sh"

HISTORY_URL = (
    "https://www.starbucks.ca/apiproxy/v1/orchestra/get-transaction-history"
)
RECEIPT_URL = (
    "https://www.starbucks.ca/apiproxy/v1/orchestra/get-history-item-receipt"
)

PAGE_LIMIT = 50
HISTORY_SLEEP_S = 0.4
RECEIPT_SLEEP_S = 0.25

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

SESSION_EXPIRED_MSG = (
    "SESSION EXPIRED — refresh the cookie in get-transaction-history.sh"
)


class SessionExpired(Exception):
    """Raised when the Starbucks session cookie is no longer valid."""


def extract_cookie(cookie_file: Path) -> str:
    text = cookie_file.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"-b '([^']*)'", text)
    if not match:
        raise ValueError(
            f"no -b '...' cookie option found in {cookie_file}"
        )
    return match.group(1)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_json_list(path: Path) -> list:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"expected JSON array in {path}")
    return data


def is_auth_failure(status: int | None, body: object) -> bool:
    if status in (401, 403):
        return True
    if isinstance(body, dict):
        if (
            body.get("type") == "authorize-operation"
            or (
                body.get("roleProvided") == "public"
                and body.get("roleRequired") == "user"
            )
        ):
            return True
    return False


def api_post(url: str, cookie: str, variables: dict) -> dict:
    payload = json.dumps({"variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://www.starbucks.ca",
            "referer": "https://www.starbucks.ca/account/history",
            "x-requested-with": "XMLHttpRequest",
            "user-agent": USER_AGENT,
            "cookie": cookie,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read() if exc.fp is not None else b""
        body: object
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            body = {"_raw": raw.decode("utf-8", errors="replace")}
        if is_auth_failure(status, body):
            raise SessionExpired(SESSION_EXPIRED_MSG) from exc
        raise RuntimeError(
            f"HTTP {status} from {url}: {json.dumps(body)[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error calling {url}: {exc}") from exc

    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"non-JSON response from {url} (HTTP {status})"
        ) from exc

    if is_auth_failure(status, body):
        raise SessionExpired(SESSION_EXPIRED_MSG)

    if not isinstance(body, dict):
        raise RuntimeError(f"unexpected JSON type from {url}: {type(body)}")
    return body


def fetch_history(cookie: str) -> list[dict]:
    all_items: list[dict] = []
    offset = 0
    total: int | None = None
    first = True

    while True:
        if not first:
            time.sleep(HISTORY_SLEEP_S)
        first = False

        print(f"history page offset={offset} limit={PAGE_LIMIT}")
        body = api_post(
            HISTORY_URL,
            cookie,
            {"offset": offset, "limit": PAGE_LIMIT},
        )
        page_path = DATA_DIR / f"page-{offset}.json"
        write_json(page_path, body)

        data = (body.get("data") or {}).get("transactionHistoryV2") or {}
        paging = data.get("paging") or {}
        if total is None:
            total = int(paging.get("total") or 0)
            print(f"history total reported: {total}")

        history_items = data.get("historyItems") or []
        page_count = 0
        for item in history_items:
            if item is None:
                continue
            if isinstance(item, dict):
                all_items.append(item)
                page_count += 1
        print(f"  kept {page_count} non-null items (running {len(all_items)})")

        # API `total` counts slots (including nulls). Advance by limit until covered.
        offset += PAGE_LIMIT
        if total is not None and offset >= total:
            break
        if not history_items:
            break

    write_json(DATA_DIR / "all-items.json", all_items)
    print(f"wrote {DATA_DIR / 'all-items.json'} ({len(all_items)} items)")
    return all_items


def normalize_purchased_item(item: dict) -> dict:
    options = item.get("options") or []
    discounts = item.get("discounts") or []
    return {
        "name": item.get("name"),
        "size": item.get("size"),
        "price": item.get("price"),
        "calories": item.get("calories"),
        "options": options if isinstance(options, list) else [],
        "discounts": discounts if isinstance(discounts, list) else [],
    }


def parse_receipt_response(history_id: str, date: str | None, body: dict) -> dict:
    activity = (body.get("data") or {}).get("activity") or {}
    store = activity.get("store") or {}
    receipt = activity.get("receipt") or {}
    purchased = [
        normalize_purchased_item(it)
        for it in (receipt.get("purchasedItems") or [])
        if isinstance(it, dict)
    ]
    return {
        "historyId": history_id,
        "date": date,
        "storeName": store.get("name"),
        "storeNumber": store.get("storeNumber"),
        "purchasedItems": purchased,
        "subtotal": receipt.get("subtotal"),
        "total": receipt.get("total"),
    }


def fetch_receipts(cookie: str, history_items: list[dict]) -> tuple[list[dict], int, int]:
    """Return (receipts, new_count, cached_count)."""
    receipts_path = DATA_DIR / "receipts.json"
    errors_path = DATA_DIR / "receipt-errors.json"

    existing = load_json_list(receipts_path)
    by_id: dict[str, dict] = {}
    for rec in existing:
        hid = rec.get("historyId")
        if hid and "error" not in rec:
            by_id[str(hid)] = rec

    errors = load_json_list(errors_path)
    errors_by_id: dict[str, dict] = {
        str(e["historyId"]): e for e in errors if e.get("historyId")
    }

    redemption_ids: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for item in history_items:
        if item.get("transactionType") != "Redemption":
            continue
        hid = item.get("historyId")
        if not hid:
            continue
        hid = str(hid)
        if hid in seen:
            continue
        seen.add(hid)
        redemption_ids.append((hid, item.get("date")))

    to_fetch = [(hid, date) for hid, date in redemption_ids if hid not in by_id]
    cached_count = len(redemption_ids) - len(to_fetch)
    print(
        f"receipts: {len(redemption_ids)} Redemption ids, "
        f"{cached_count} cached, {len(to_fetch)} to fetch"
    )

    new_count = 0
    first = True
    for hid, date in to_fetch:
        if not first:
            time.sleep(RECEIPT_SLEEP_S)
        first = False
        print(f"  receipt {hid}")
        try:
            body = api_post(RECEIPT_URL, cookie, {"historyId": hid})
            parsed = parse_receipt_response(hid, date, body)
            by_id[hid] = parsed
            new_count += 1
            # Clear any prior error for this id on success.
            errors_by_id.pop(hid, None)
        except SessionExpired:
            raise
        except Exception as exc:  # noqa: BLE001 — record and continue
            msg = str(exc)
            print(f"    error: {msg[:200]}")
            errors_by_id[hid] = {"historyId": hid, "error": msg}

    # Prefer date from history when receipt date is missing.
    date_by_id = {hid: d for hid, d in redemption_ids}
    for hid, rec in by_id.items():
        if not rec.get("date") and date_by_id.get(hid):
            rec["date"] = date_by_id[hid]

    receipts = sorted(
        by_id.values(),
        key=lambda r: (r.get("date") or "", r.get("historyId") or ""),
    )
    write_json(receipts_path, receipts)
    # Merge the raw receipt cache; the history module creates observations and
    # performs guarded cross-source reconciliation.
    merge_history(DATA_DIR / "history.json", receipts)
    write_json(errors_path, sorted(errors_by_id.values(), key=lambda e: e.get("historyId") or ""))
    print(f"wrote {receipts_path} ({len(receipts)} receipts, {new_count} new)")
    if errors_by_id:
        print(f"wrote {errors_path} ({len(errors_by_id)} errors)")
    return receipts, new_count, cached_count


def summarize(history_items: list[dict], receipts: list[dict], new_count: int, cached_count: int) -> None:
    dates = [ (r.get("date") or "")[:10] for r in receipts if r.get("date") ]
    redemptions = sum(
        1 for i in history_items if i.get("transactionType") == "Redemption"
    )
    stores = {
        (r.get("storeNumber") or r.get("storeName") or "").strip()
        for r in receipts
        if (r.get("storeNumber") or r.get("storeName"))
    }
    stores.discard("")

    print("---")
    print(f"history total fetched: {len(history_items)}")
    print(f"receipts: {new_count} new, {cached_count} cached, {len(receipts)} total")
    print(f"date range: {min(dates) if dates else None} .. {max(dates) if dates else None}")
    print(f"Redemption rows: {redemptions}")
    print(f"unique stores: {len(stores)}")
    print("next: python3 scripts/starbucks_import.py && zola build")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cookie-file",
        type=Path,
        default=DEFAULT_COOKIE_FILE,
        help="path to curl script containing -b 'cookie' (default: repo-root get-transaction-history.sh)",
    )
    args = parser.parse_args()

    cookie_file = args.cookie_file
    if not cookie_file.is_absolute():
        cookie_file = (Path.cwd() / cookie_file).resolve()

    if not cookie_file.exists():
        print(f"error: cookie file not found: {cookie_file}", file=sys.stderr)
        return 1

    try:
        cookie = extract_cookie(cookie_file)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        history_items = fetch_history(cookie)
        receipts, new_count, cached_count = fetch_receipts(cookie, history_items)
    except SessionExpired as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summarize(history_items, receipts, new_count, cached_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
