#!/usr/bin/env python3
"""Incrementally refresh the Starbucks ledger by driving starbucks.ca in a browser.

Usage:
    python3 scripts/starbucks_browser_fetch.py --start-browser --stop-browser
    python3 scripts/starbucks_browser_fetch.py --name sbux          # reuse a daemon
    python3 scripts/starbucks_browser_fetch.py --full               # whole history

Alternative to starbucks_fetch.py that needs no copied session cookie. It uses
browser-use (https://docs.browser-use.com) to open a Browser Use Cloud browser,
signs in with credentials from the Bitwarden CLI, opens /account/history, and
records the JSON responses the site's own page fires for the history list
("Show more activity") and for each "View receipt" button. Nothing is written
to disk except the merged ledger.

Incremental by default: only history newer than the ledger's latest visit
(minus a one-day overlap) is paged and only those receipts are opened.

Requires on PATH: browser-use (authenticated, see `browser-use auth status`)
and bw. BW_SESSION must be exported (unlocked vault). After this runs:
    python3 scripts/starbucks_import.py
    python3 scripts/render_starbucks_map.py
    zola check && zola build
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from starbucks_fetch import parse_receipt_response
from starbucks_history import merge_history

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "starbucks" / "history.json"
DEFAULT_BW_ITEM = "com.starbucks.mobilecard"

# Runs inside `browser-use` (helpers such as js/cdp/wait are pre-imported).
CAPTURE_SCRIPT = r'''
import datetime, json, os, re
SINCE = datetime.date.fromisoformat(os.environ["SBUX_SINCE"])

def signed_in():
    return "/account/signin" not in current_tab()["url"] and "auth.starbucks.com" not in current_tab()["url"]

def settle():
    for _ in range(3):
        try:
            wait_for_load(20)
            return
        except Exception:
            wait(2)

cdp("Network.enable")
new_tab("https://www.starbucks.ca/account/history")
settle(); wait(4)
if not signed_in():
    fill_input("#username", os.environ["SBUX_USER"])
    fill_input("#password", os.environ["SBUX_PASS"])
    js("document.querySelector('button[type=submit][name=action]').click()")
    wait(8); settle()
    goto_url("https://www.starbucks.ca/account/history")
    settle(); wait(4)
if not signed_in():
    raise SystemExit("sign-in failed (MFA or captcha?)")

reqs, pages, receipts = {}, [], {}

def pump():
    for e in drain_events():
        m, p = e.get("method"), e.get("params", {})
        if m == "Network.requestWillBeSent" and "apiproxy" in p["request"]["url"]:
            reqs[p["requestId"]] = (p["request"]["url"], p["request"].get("postData"))
        elif m == "Network.loadingFinished" and p["requestId"] in reqs:
            url, post = reqs[p["requestId"]]
            if "get-transaction-history" in url:
                kind = "history"
            elif "get-history-item-receipt" in url:
                kind = "receipt"
            else:
                continue
            body = json.loads(cdp("Network.getResponseBody", requestId=p["requestId"])["body"])
            if kind == "history":
                pages.append(body)
            else:
                receipts[str(json.loads(post)["variables"]["historyId"])] = body

# The initial page load already fired the first history request; reload to
# capture it with Network enabled.
drain_events()
goto_url("https://www.starbucks.ca/account/history")
settle(); wait(5); pump()

def oldest_loaded():
    days = [i["date"][:10] for b in pages
            for i in (b["data"]["transactionHistoryV2"]["historyItems"] or []) if i]
    return datetime.date.fromisoformat(min(days)) if days else None

while True:
    oldest = oldest_loaded()
    if oldest is not None and oldest < SINCE:
        break
    more = js("(function(){var b=[...document.querySelectorAll('button')].find(e=>/Show more activity/.test(e.innerText));if(!b)return false;b.scrollIntoView();b.click();return true})()")
    if not more:
        break
    wait(3); pump()

labels = json.loads(js("JSON.stringify([...document.querySelectorAll('button[aria-label^=\"View receipt\"]')].map(b=>b.getAttribute('aria-label')))"))
def label_date(label):
    m = re.search(r"for (\w+ \d+, \d{4})", label)
    return datetime.datetime.strptime(m.group(1), "%B %d, %Y").date()
for i, label in enumerate(labels):
    if label_date(label) < SINCE:
        continue
    js("(function(){var b=document.querySelectorAll('button[aria-label^=\"View receipt\"]')[%d];b.scrollIntoView({block:'center'});b.click()})()" % i)
    wait(1.8); pump()
    press_key("Escape"); wait(0.4)
wait(2); pump()

json.dump({"pages": pages, "receipts": receipts}, open(os.environ["SBUX_OUT"], "w"))
print("captured", len(pages), "history pages and", len(receipts), "receipts")
'''


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, **kwargs)


def harness_python() -> str:
    exe = shutil.which("browser-use")
    if not exe:
        raise SystemExit("browser-use not found on PATH")
    return str(Path(exe).resolve().parent / "python")


def remote_daemon(action: str, name: str) -> None:
    """Start or stop a Browser Use Cloud daemon (the CLI would first try to
    attach to local Chrome, so go through the harness module directly)."""
    code = (
        "from browser_harness.admin import start_remote_daemon, stop_remote_daemon\n"
        + (
            f"start_remote_daemon({name!r}, timeout=60)\n"
            if action == "start"
            else f"stop_remote_daemon({name!r})\n"
        )
    )
    proc = run(
        [harness_python(), "-I", "-c", code],
        env={**os.environ, "BH_OPEN_LIVE_URL": "0"},
    )
    if proc.returncode:
        raise SystemExit(f"{action} browser failed: {proc.stderr[-400:]}")


def bw_item_id(item: str) -> str:
    """Resolve an exact item name to its id (`bw get` rejects ambiguous names)."""
    if re.fullmatch(r"[0-9a-f-]{36}", item):
        return item
    proc = run(["bw", "list", "items", "--search", item])
    if proc.returncode:
        raise SystemExit("bw list failed (is BW_SESSION set?)")
    ids = [i["id"] for i in json.loads(proc.stdout) if i.get("name") == item]
    if len(ids) != 1:
        raise SystemExit(f"expected one Bitwarden item named {item!r}, found {len(ids)}")
    return ids[0]


def bw_field(item: str, field: str) -> str:
    proc = run(["bw", "get", field, item])
    if proc.returncode or not proc.stdout:
        raise SystemExit(f"bw get {field} {item!r} failed (is BW_SESSION set?)")
    return proc.stdout.strip("\n")


def ledger_since(full: bool) -> date:
    if full or not LEDGER.exists():
        return date(2000, 1, 1)
    visits = json.loads(LEDGER.read_text(encoding="utf-8")).get("visits", [])
    days = [v["local_date"] for v in visits if v.get("local_date")]
    if not days:
        return date(2000, 1, 1)
    return date.fromisoformat(max(days)) - timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="sbux", help="browser-use daemon name (BU_NAME)")
    parser.add_argument("--bw-item", default=DEFAULT_BW_ITEM, help="Bitwarden item name or id")
    parser.add_argument("--start-browser", action="store_true", help="start a cloud browser first")
    parser.add_argument("--stop-browser", action="store_true", help="stop the cloud browser afterwards")
    parser.add_argument("--full", action="store_true", help="fetch the whole history, not just new activity")
    args = parser.parse_args()

    since = ledger_since(args.full)
    print(f"fetching activity since {since}")

    started = False
    try:
        if args.start_browser:
            remote_daemon("start", args.name)
            started = True
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "capture.json"
            bw_id = bw_item_id(args.bw_item)
            env = {
                **os.environ,
                "BU_NAME": args.name,
                "SBUX_SINCE": since.isoformat(),
                "SBUX_OUT": str(out),
                "SBUX_USER": bw_field(bw_id, "username"),
                "SBUX_PASS": bw_field(bw_id, "password"),
            }
            proc = run(["browser-use"], input=CAPTURE_SCRIPT, env=env, timeout=1800)
            sys.stdout.write(proc.stdout)
            if proc.returncode or not out.exists():
                sys.stderr.write(proc.stderr[-800:])
                return 1
            capture = json.loads(out.read_text(encoding="utf-8"))
    finally:
        if started and args.stop_browser:
            remote_daemon("stop", args.name)

    items: dict[str, dict] = {}
    for body in capture["pages"]:
        for item in (body.get("data") or {}).get("transactionHistoryV2", {}).get("historyItems") or []:
            if isinstance(item, dict) and item.get("historyId"):
                items[str(item["historyId"])] = item
    dates = {hid: item.get("date") for hid, item in items.items()}
    receipts = [
        parse_receipt_response(hid, dates.get(hid), body)
        for hid, body in capture["receipts"].items()
    ]
    if not items:
        print("error: no history captured", file=sys.stderr)
        return 1
    merge_history(LEDGER, receipts, history_items=list(items.values()))
    print(f"merged {len(items)} history items and {len(receipts)} receipts into {LEDGER}")
    print("next: python3 scripts/starbucks_import.py && python3 scripts/render_starbucks_map.py && zola build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
