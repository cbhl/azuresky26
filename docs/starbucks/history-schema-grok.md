# Starbucks canonical event ledger — schema design

Design artifact only (not implemented code). Describes the durable, mergeable history that backs `/starbucks/` metrics, the contribution-style activity graph, GTA store resolution, and Stars totals when combining:

- USA Customer Information Report (CIR)
- Canada Customer Information Report (CIR)
- starbucks.ca API export (`get-transaction-history` + itemized receipts)

Validated against the real CIR text exports and the repo’s CA API artifacts (`data/starbucks/receipts.json`, `all-items.json`).

---

## 1. Goals

| Goal | Requirement |
|------|-------------|
| Survive API TTL | Ledger is durable; a shorter API window must not delete older events |
| Correct daily graph | One **visit** = one order/receipt, **not** one line item |
| Correct page metrics | Visits, items, stars, GTA map/remaining, unmatched — one source of truth |
| Multi-source merge | US CIR + CA CIR + API with provenance |
| Privacy | No profile or card data in canonical history; raw source IDs may be retained for identity, but are stripped from published artifacts |

**Layers**

1. **Private working data** (gitignored): raw CIR `.txt`, API pages, `receipts.json`, optional `_ledger_private.json` (`historyId` → `event_id`).
2. **Committed canonical ledger**: `data/starbucks/history.json` — source-preserving events, including raw source IDs needed for exact deduplication/reconciliation, but no profile or card data.
3. **Published rollup**: `data/starbucks/starbucks.json` + site templates — aggregates only.

### Contract alignment

The final implementation contract uses the following fields and containers;
these names take precedence over the exploratory event model used in some
examples below:

| Purpose | Canonical field |
|---------|-----------------|
| Top-level source list | `sources` |
| Physical source record | `observations[]` with `observation_id`, `source_kind` |
| Canonical visit | `visits[]` with `visit_id`, `source_kinds`, `source_observation_ids` |
| Stars record | `stars[]` with `star_id`, `source_kind`, `source_observation_id` |
| API/report reconciliation time | `local_second` |

The exploratory `events[]`, `event_id`, nested `identity`,
`native_id_hash`, and `sources_ingested[]` fields are not part of the final
canonical schema. `visit_id` and `star_id` are internal stable identifiers,
not public IDs.

---

## 2. Report observations (ground truth)

### 2.1 Files inspected

| Source | Example path / id | Role |
|--------|-------------------|------|
| US CIR | `usa-report.txt` | Long US history + some GTA visits |
| CA CIR | `canada-report.txt` | CA history overlapping API |
| CA API | `all-items.json`, `receipts.json` | Recent CA orders + Point/Reload rows |

Report filenames look account-linked — do not commit or cite as public identifiers.

### 2.2 CIR document shape

Both US and CA use the **same CSV section template** (not space-separated columns).

Relevant sections:

1. Customer Profile, Address, Phone, Guest Profile — **private, never ingest into ledger fields**
2. Rewards membership / email / wifi flags
3. Active Stored Value Cards (`XXXX XXXX XXXX nnnn`) — **private**
4. **`Purchase Transactions,`**
   - Header: `Date/Time,Store Name,Order Total Charged,Item Name`
   - Row example: `2026-08-22 18:00:37,Bayview & Romfield,3.25,Tr Green Iced Tea Lemonade`
5. **`Rewards Transactions,`**
   - Header: `Date/Time Earned,Stars Earned,Point Type`
   - Row example: `2026-08-22,5.5,Points` or `None,60.0,Promotion`
6. Promotions, Favorites, WiFi, Google Analytics, Hybris eGift — **out of scope for visits** (optional future)

### 2.3 Observed ranges (at validation time)

| | US CIR | CA CIR | CA API receipts |
|--|--------|--------|-----------------|
| Purchases | 2022-01-02 → 2026-04-04 | 2024-08-14 → 2026-08-22 | 2026-04-26 → 2026-08-23 |
| Rewards | 2022-01-02 → 2026-04-04 | 2024-08-14 → 2026-08-23 | Point rows in same window |
| Visit orders (after reload filter) | ~442 | ~432 | 156 |
| Purchase line rows | ~1071 | ~858 | — |

US ∩ CA on exact `(datetime, store)`: **0** order clones. US still contains **GTA store visits** (e.g. Bayview & Romfield in 2022/2024) that must count toward GTA visited/map when name-matched.

### 2.4 Purchase line semantics

- **Grain:** one CSV row = one **line item** (or modifier line), not one visit.
- **“Order Total Charged” is misnamed:** it is a **per-line amount**. Multi-item orders almost always have **different** amounts per line (US ~292/301 multi-item groups; CA ~226/230).
- **Visit grouping key:** `(Date/Time second, Store Name)` — **not** amount.
- **Timestamps:** naive **local wall clock** (CA matches API when API UTC is converted to `America/Toronto`). Example: CIR `2026-08-22 18:00:37` ↔ API `2026-08-22T22:00:37Z` (EDT).
- **Item names:** POS abbreviations (`Tr Lemonade Cool Lime`) vs API marketing names (`Cool Lime Lemonade Refresher`).
- **Modifiers:** CIR often emits separate lines (`Add Vanilla Syrup`, `Chocolate Cream Cold Foam`); API nests `options[]` under a drink. Item cardinality matches on only a subset of CIR↔API pairs — **do not require item-list equality for dedupe**.
- **Store string drift:** e.g. CIR `Vaughan Mills - Entry 2 Food Court` vs API `Vaughan Mills - Entry 2 Food C`.

### 2.5 Reload / non-visit purchase rows

Empty `Store Name` and/or item name in:

| Item name | Notes |
|-----------|--------|
| `Reload Balance` | Manual reload |
| `Automatic Reload` | US auto-reload |
| `Lsus` / `Lsca` | Balance movement — **not** a store visit |

These must never set `counts_as_visit: true`.

### 2.6 Rewards (Stars) semantics

| Point Type | Sign | Meaning |
|------------|------|---------|
| `Points` | always **+** | Spend earn (fractional); ≈ API `starsEarnedDisplay` |
| `Product` | always **−** | Stars applied to product; **often many rows per day that sum toward a reward tier** (e.g. fragments → −60), **not** one row per API `60★ redeemed` |
| `Promotion` | **+** | Bonus; `Date/Time` may be `None` |
| `Stars for Reload` | **+** (CA) | Reload bonus (API: `50★ earned` + “Starbucks Card Reload”) |
| `Partnership Card Reload` | **+** (CA) | e.g. TD 100 |
| `Partnership Star Accrual` / `Bonus` | **+** | Large one-offs |
| `Expired` | **−** (US) | Expiry |

Despite the header “Date/Time Earned”, reward values are **date-only** in practice (`2026-08-22`) → precision `day`.

**Do not 1:1-dedupe** CIR `Product` lines against API discrete `N★ redeemed` Point rows. Grains differ; use the Stars policy in §8.

### 2.7 API side (CA)

| historyType / transactionType | Visit? | Notes |
|-------------------------------|--------|--------|
| `TransactionWithPoints` + `Redemption` | **Yes** (1 per `historyId` / receipt) | Order-grained; items via receipt |
| `Transaction` + `Reload` | No | |
| `Point` | No | `N★ earned/redeemed` + optional category |
| `Coupon` | No | |
| Balance transfer | No | |

Private API fields include `svcID` (card) and tips. Raw `historyId`, `checkId`, and
`receiptNumber` may be retained in the committed canonical ledger as
source-qualified identity fields for exact deduplication/reconciliation, but
must be stripped from `starbucks.json` and HTML. Report source row IDs follow
the same rule. Hashing is not a substitute for canonical source identity and a
hash of a source ID must not be emitted as a public identifier.

CIR↔API purchase match on `(Toronto local second, normalized store)`: **~151/156** receipts; a few API-only rows (newer than CIR or naming edge cases).

---

## 3. Invariants

1. **`counts_as_visit` is true only for order-grain purchases** that are not reloads/balance rows.
2. **Graph day count** = `COUNT DISTINCT visit_key` (or `event_id` of visit orders) per `local_date` — never count purchase line residues or stars rows.
3. **`local_date` is the only calendar bucket** for the activity graph; it is always a civil date in `activity_timezone` (`America/Toronto` for this site).
4. **CIR purchase times are `time_basis: "local_wall"`**; API instants are UTC then converted for `local_date`.
5. **Primary purchase dedupe key does not include amount** (line ≠ order total; tax breaks API equality).
6. **Item lists are not required for dedupe** (POS vs marketing; mods-as-lines).
7. **Refresh never deletes** events merely absent from a newer, shorter API fetch.
8. **GTA geography metrics** only count purchases with `store.in_gta_catalog == true`; **top items** and the **activity graph** may include all visits.
9. **No PII or card data** in `history.json`; generated `starbucks.json` and
HTML contain neither those data nor raw native payment/history IDs.
10. **Stars totals must not double-count** CIR rewards and API Point/display earns for the same economic period (see §8).
11. **US-only stores** never appear in top GTA stores, visited/remaining/to-visit, or map dots; their **items** still feed top items; their **GTA-named** visits still count when catalog-matched.
12. **`status: superseded | void`** events are ignored by all public metrics.

---

## 4. Document schema

### 4.1 Top-level ledger (`data/starbucks/history.json`)

```json
{
  "schema_version": 1,
  "activity_timezone": "America/Toronto",
  "updated_at": "2026-08-28T12:00:00Z",
  "sources": ["us_customer_information_report", "ca_customer_information_report", "api_export"],
  "observations": [],
  "visits": [],
  "stars": []
}
```

`source` enum:

- `us_customer_information_report`
- `ca_customer_information_report`
- `api_export`

### 4.2 Canonical visit object

The implementation stores visits in `visits[]` and source rows in
`observations[]`; the following exploratory event example is illustrative
only. Its serialized field names are superseded by the contract-alignment
table above.

```json
{
  "event_id": "01JABC…",
  "kind": "purchase",
  "status": "active",
  "counts_as_visit": true,
  "grain": "order",

  "occurred_at": "2026-08-22T22:00:37Z",
  "occurred_at_precision": "second",
  "time_basis": "utc",
  "local_date": "2026-08-22",

  "country": "CA",
  "channel": "mobile",
  "currency": "CAD",

  "amount_lines_sum": 3.25,
  "amount_order_total": 3.41,

  "stars_delta": null,
  "stars_point_type": null,
  "stars_on_purchase": 5.5,

  "store": {
    "name_raw": "Bayview & Romfield",
    "name_key": "bayview and romfield",
    "store_number": "23280-204964",
    "in_gta_catalog": true,
    "standalone": true,
    "region": "York Region",
    "match_method": "store_number"
  },

  "items": [
    {
      "name": "Iced Green Tea Lemonade",
      "name_key": "iced green tea lemonade",
      "name_raw_cir": "Tr Green Iced Tea Lemonade",
      "quantity": 1
    }
  ],

  "identity": {
    "visit_key": "01JABC…",
    "order_key": "2026-08-22T18:00:37|bayview and romfield",
    "native_id_hash": "a1b2c3…"
  },

  "sources": ["ca_customer_information_report", "api_export"],

  "provenance": {
    "first_seen_at": "2026-08-24T10:33:00Z",
    "last_seen_at": "2026-08-28T12:00:00Z",
    "extract_rule": "api_receipt_v1",
    "merged_from_event_ids": []
  }
}
```

### 4.3 Field reference

| Field | Type | Notes |
|-------|------|--------|
| `event_id` | string | Exploratory-only name; final visits use internal `visit_id`, never a public ID. |
| `kind` | enum | `purchase` \| `stars` \| `reload` \| `coupon` \| `other` |
| `status` | enum | `active` \| `void` \| `superseded` |
| `counts_as_visit` | bool | Graph + store visit tallies gate |
| `grain` | enum | `order` (visit unit) \| `ledger` (stars/reload/coupon) \| `line_residue` (should be rare in final file) |
| `occurred_at` | string \| null | UTC ISO-8601 when known |
| `occurred_at_precision` | enum | `second` \| `minute` \| `day` \| `unknown` |
| `time_basis` | enum | `utc` (API) \| `local_wall` (CIR purchases) |
| `local_date` | string \| null | `YYYY-MM-DD` in `activity_timezone` |
| `country` | enum | `CA` \| `US` \| `UNKNOWN` |
| `channel` | enum | `in_store` \| `mobile` \| `unknown` |
| `currency` | enum | `CAD` \| `USD` \| `UNKNOWN` |
| `amount_lines_sum` | number \| null | Sum of CIR line amounts or API item pre-tax net when known |
| `amount_order_total` | number \| null | API receipt `total` when known |
| `stars_delta` | number \| null | Signed stars for `kind: "stars"` |
| `stars_point_type` | string \| null | CIR Point Type or API category (`Starbucks Card Reload`, …) |
| `stars_on_purchase` | number \| null | Parsed from API `starsEarnedDisplay` on Redemption; not always added to totals |
| `store.*` | object | Resolution result; see §7 |
| `items[]` | array | Prefer API display `name`; keep `name_raw_cir` when merged |
| `identity.visit_key` | string | DISTINCT key for graph; equals `event_id` for visit orders |
| `identity.order_key` | string | `local_wall_ts\|name_key` (CIR) or derived from API local time + store |
| `identity.native_id_hash` | string \| null | Exploratory-only; final canonical history retains source-qualified raw IDs instead |
| `sources` | string[] | Provenance set |
| `provenance` | object | first/last seen, extract rule, merge trail |

### 4.4 Kind rules

| kind | counts_as_visit | grain | When |
|------|-----------------|-------|------|
| `purchase` | **true** | `order` | CIR lines collapsed by order_key; API Redemption receipt |
| `stars` | false | `ledger` | CIR Rewards row or API Point row |
| `reload` | false | `ledger` | CIR Reload/Automatic/Lsus/Lsca or API Reload |
| `coupon` | false | `ledger` | API Coupon (CIR Promotions optional/omit) |
| `other` | false | `ledger` | Balance transfer, etc. |

---

## 5. Concrete examples

### 5.1 CA order — CIR lines + API receipt merged (one visit)

CIR lines at `2026-08-20 19:44:13`, Bayview & Romfield:

- `3.65,Tall Iced Coffee`
- `4.95,Tr Lemonade Cool Lime`

API receipt same local second, full names + tax-inclusive total.

```json
{
  "event_id": "01J_VISIT_BAYVIEW_20260820",
  "kind": "purchase",
  "status": "active",
  "counts_as_visit": true,
  "grain": "order",
  "occurred_at": "2026-08-20T23:44:13.000Z",
  "occurred_at_precision": "second",
  "time_basis": "utc",
  "local_date": "2026-08-20",
  "country": "CA",
  "channel": "in_store",
  "currency": "CAD",
  "amount_lines_sum": 8.6,
  "amount_order_total": 9.72,
  "stars_delta": null,
  "stars_on_purchase": null,
  "store": {
    "name_raw": "Bayview & Romfield",
    "name_key": "bayview and romfield",
    "store_number": "23280-204964",
    "in_gta_catalog": true,
    "standalone": true,
    "region": "York Region",
    "match_method": "store_number"
  },
  "items": [
    {
      "name": "Starbucks® Iced Coffee Blend",
      "name_key": "starbucks iced coffee blend",
      "name_raw_cir": "Tall Iced Coffee",
      "quantity": 1
    },
    {
      "name": "Cool Lime Lemonade Refresher",
      "name_key": "cool lime lemonade refresher",
      "name_raw_cir": "Tr Lemonade Cool Lime",
      "quantity": 1
    }
  ],
  "identity": {
    "visit_key": "01J_VISIT_BAYVIEW_20260820",
    "order_key": "2026-08-20T19:44:13|bayview and romfield",
    "native_id_hash": "…"
  },
  "sources": ["ca_customer_information_report", "api_export"],
  "provenance": {
    "first_seen_at": "2026-08-24T10:33:00Z",
    "last_seen_at": "2026-08-28T12:00:00Z",
    "extract_rule": "api_receipt_v1",
    "merged_from_event_ids": []
  }
}
```

### 5.2 US GTA visit (items yes, geography yes if catalog match)

```json
{
  "event_id": "01J_US_BAYVIEW_20220626",
  "kind": "purchase",
  "status": "active",
  "counts_as_visit": true,
  "grain": "order",
  "occurred_at": null,
  "occurred_at_precision": "second",
  "time_basis": "local_wall",
  "local_date": "2022-06-26",
  "country": "US",
  "channel": "unknown",
  "currency": "USD",
  "amount_lines_sum": 18.8,
  "amount_order_total": null,
  "store": {
    "name_raw": "Bayview & Romfield",
    "name_key": "bayview and romfield",
    "store_number": null,
    "in_gta_catalog": true,
    "standalone": true,
    "region": "York Region",
    "match_method": "exact_name"
  },
  "items": [
    { "name": "Gr Mango Dragonfruit Juice", "name_key": "gr mango dragonfruit juice", "name_raw_cir": "Gr Mango Dragonfruit Juice", "quantity": 1 },
    { "name": "Gr Pineapple Refresher", "name_key": "gr pineapple refresher", "name_raw_cir": "Gr Pineapple Refresher", "quantity": 1 },
    { "name": "Tl Cold Brew Iced Coffee", "name_key": "tl cold brew iced coffee", "name_raw_cir": "Tl Cold Brew Iced Coffee", "quantity": 1 },
    { "name": "Gr Strawberry Acai Juice", "name_key": "gr strawberry acai juice", "name_raw_cir": "Gr Strawberry Acai Juice", "quantity": 1 }
  ],
  "identity": {
    "visit_key": "01J_US_BAYVIEW_20220626",
    "order_key": "2022-06-26T10:50:50|bayview and romfield",
    "native_id_hash": null
  },
  "sources": ["us_customer_information_report"],
  "provenance": {
    "first_seen_at": "2026-08-28T12:00:00Z",
    "last_seen_at": "2026-08-28T12:00:00Z",
    "extract_rule": "cir_csv_v1",
    "merged_from_event_ids": []
  }
}
```

Note: `local_date` for graph uses `activity_timezone`. For pure `local_wall` CIR rows, `local_date` is the calendar date of the CIR `Date/Time` field (the wall date printed on the report). US wall times are store-local; do not reinterpret US rows as Toronto clock times for `occurred_at`, but **graph cells still key off the report’s civil date** unless a reliable zone is later attached.

### 5.3 US-only store (items count; not GTA top stores / map)

```json
{
  "event_id": "01J_US_STEVENS_20260404",
  "kind": "purchase",
  "status": "active",
  "counts_as_visit": true,
  "grain": "order",
  "time_basis": "local_wall",
  "local_date": "2026-04-04",
  "country": "US",
  "amount_lines_sum": 14.88,
  "store": {
    "name_raw": "Stevens Creek & DeAnza",
    "name_key": "stevens creek and deanza",
    "store_number": null,
    "in_gta_catalog": false,
    "standalone": null,
    "region": null,
    "match_method": "unmatched"
  },
  "items": [
    { "name": "Spinach Feta Wrap", "name_key": "spinach feta wrap", "quantity": 1 },
    { "name": "Chicken Jalapeno Pocket Dense", "name_key": "chicken jalapeno pocket dense", "quantity": 1 },
    { "name": "Trenta Icd Green Tea", "name_key": "trenta icd green tea", "quantity": 1 }
  ],
  "identity": {
    "visit_key": "01J_US_STEVENS_20260404",
    "order_key": "2026-04-04T18:11:12|stevens creek and deanza",
    "native_id_hash": null
  },
  "sources": ["us_customer_information_report"]
}
```

### 5.4 Reload (not a visit)

```json
{
  "event_id": "01J_RELOAD_CA_20260822",
  "kind": "reload",
  "status": "active",
  "counts_as_visit": false,
  "grain": "ledger",
  "time_basis": "local_wall",
  "local_date": "2026-08-22",
  "country": "CA",
  "amount_order_total": 72.52,
  "store": {
    "name_raw": "",
    "name_key": "",
    "store_number": null,
    "in_gta_catalog": false,
    "match_method": "n/a"
  },
  "items": [],
  "identity": {
    "visit_key": "01J_RELOAD_CA_20260822",
    "order_key": "2026-08-22T18:00:56|",
    "native_id_hash": null
  },
  "sources": ["ca_customer_information_report"],
  "provenance": { "extract_rule": "cir_csv_v1" }
}
```

### 5.5 Stars — CIR spend earn (`Points`)

```json
{
  "event_id": "01J_STARS_CA_PTS_20260822",
  "kind": "stars",
  "status": "active",
  "counts_as_visit": false,
  "grain": "ledger",
  "occurred_at": null,
  "occurred_at_precision": "day",
  "time_basis": "local_wall",
  "local_date": "2026-08-22",
  "country": "CA",
  "stars_delta": 5.5,
  "stars_point_type": "Points",
  "store": { "name_raw": "", "name_key": "", "in_gta_catalog": false, "match_method": "n/a" },
  "items": [],
  "identity": {
    "visit_key": "01J_STARS_CA_PTS_20260822",
    "order_key": null,
    "native_id_hash": null
  },
  "sources": ["ca_customer_information_report"]
}
```

### 5.6 Stars — CIR `Product` fragment (not 1:1 with API 60★ row)

```json
{
  "event_id": "01J_STARS_CA_PROD_20260822_A",
  "kind": "stars",
  "status": "active",
  "counts_as_visit": false,
  "grain": "ledger",
  "occurred_at_precision": "day",
  "local_date": "2026-08-22",
  "country": "CA",
  "stars_delta": -2.5,
  "stars_point_type": "Product",
  "sources": ["ca_customer_information_report"]
}
```

Same day may have another `Product` row `-57.5`; together they relate to an API `60★ redeemed` but **remain separate ledger rows** under CIR grain.

### 5.7 Stars — API discrete redeem

```json
{
  "event_id": "01J_STARS_API_REDEEM_20260822",
  "kind": "stars",
  "status": "active",
  "counts_as_visit": false,
  "grain": "ledger",
  "occurred_at": "2026-08-22T22:00:36.000Z",
  "occurred_at_precision": "second",
  "time_basis": "utc",
  "local_date": "2026-08-22",
  "country": "CA",
  "stars_delta": -60,
  "stars_point_type": "api_redeemed",
  "identity": { "native_id_hash": "…", "visit_key": "01J_STARS_API_REDEEM_20260822" },
  "sources": ["api_export"]
}
```

### 5.8 Optional private sidecar (gitignored)

```json
{
  "schema_version": 1,
  "native_ids": {
    "01J_VISIT_BAYVIEW_20260820": {
      "history_id": "…",
      "check_id": "…",
      "receipt_number": "…"
    }
  }
}
```

---

## 6. Dedupe and grouping rules

### 6.1 CIR purchase line → order (before ledger insert)

```text
RELOAD_ITEMS = { reload balance, automatic reload, lsus, lsca }

for each purchase CSV row:
  if item.lower() in RELOAD_ITEMS OR (not store and item is balance-like):
    emit kind=reload (or skip if preferred), counts_as_visit=false
  else if store empty:
    skip or kind=other
  else:
    group by order_key = f"{YYYY-MM-DDTHH:MM:SS}|{name_key(store)}"

each group → one purchase event:
  items = all lines (quantity 1 each unless identical names collapsed)
  amount_lines_sum = sum(line amounts)
  counts_as_visit = true
  grain = order
```

**Never** group by amount. **Never** emit one visit per line into the final ledger.

### 6.2 Purchase / visit identity tiers

| Tier | Key | Use |
|------|-----|-----|
| 0 | API `historyId` via private map | API refresh updates same `event_id` |
| 1 | `order_key` = local wall second + `name_key(store)` | CIR↔API primary (validated ~151/156) |
| 2 | Same `local_date` + `name_key(store)` + `amount_lines_sum` within ±15%, timestamps within ±2 minutes | Skew / truncation fallback |
| 3 | Item names / tax-inclusive total | **Optional confirmation only** — not required |

**Store normalize for keys:** lower case; `&` → `and`; strip punctuation; collapse whitespace; strip trailing `food court` / `food c`.

**Merge preference:** API receipt structure > CA CIR > US CIR. Union items (API `name` wins on fuzzy match). `sources` = sorted unique. Loser event `status: superseded` if a separate id existed.

### 6.3 Stars identity

```text
cir_stars_key ≈ source + point_type + local_date + stars_delta + mono_index
api_stars_key ≈ native historyId (private) or hash + direction + magnitude + timestamp
```

**No row-level merge** between CIR `Product` fragments and API `N★ redeemed`.

### 6.4 Refresh algorithm

1. Load committed canonical ledger + optional private id map.  
2. Parse source → candidates.  
3. Match tier 0 → 1 → 2; else insert new `event_id`.  
4. Enrich non-null richer fields; bump `last_seen_at`; union `sources`.  
5. **Do not drop** events missing from this fetch.  
6. Optional corrections pass (`void`, `force_match`, `set_store`, `exclude_visit`).  
7. Rebuild `starbucks.json` **from the ledger** (+ GTA catalog), not from raw receipts alone.

### 6.5 Re-import same CIR file

`sources_ingested[].content_fingerprint` detects identical bytes; skip or no-op merge. Newer reports with more rows merge by identity tiers.

---

## 7. Timezone and `local_date`

| Source | `time_basis` | How to get `local_date` |
|--------|--------------|-------------------------|
| API | `utc` | `date(occurred_at AST America/Toronto)` |
| CA CIR purchases | `local_wall` | Date portion of CIR `Date/Time` (already Toronto-area wall for CA stores) |
| US CIR purchases | `local_wall` | Date portion of CIR `Date/Time` (store-local wall) |
| CIR rewards | date-only | That date, or `null` if `None` |

**Activity / graph timezone:** always `America/Toronto` (`activity_timezone` on the ledger).

**Invariant:** never use raw API `date[:10]` (UTC calendar day). Empirically ~7/156 CA redemptions flip civil day vs Toronto local.

Normalize API fractional seconds to ≤6 digits before parse.

For day-only stars with `local_date` set: eligible for date-scoped stars sums; **not** visits.

---

## 8. Stars policy

### 8.1 Storage

- Every CIR Rewards row → `kind: "stars"`, signed `stars_delta`, `stars_point_type` = Point Type.  
- Every API Point earn/redeem → `kind: "stars"`.  
- API Redemption `starsEarnedDisplay` → `stars_on_purchase` on the **purchase** event (annotation).

### 8.2 Published totals (anti-double-count)

**Windowed source of truth (recommended):**

1. For each program country, let `cir_max_date` = max reward `local_date` from that country’s CIR (ignore `None`).  
2. **Earned / redeemed sums for dates ≤ `cir_max_date`:** sum CIR `stars_delta` only (all Point Types).  
3. **Dates after `cir_max_date`:** sum API `kind: "stars"` deltas (and only if a gap remains, `stars_on_purchase` for purchases with no linked Point earn).  
4. **Never** add CIR `Points` + API `starsEarnedDisplay` for the same day.  
5. **Never** add CIR `Product` + API redeemed for the same day.

US and CA are separate loyalty programs. Product choice:

- **Combined site total** = US CIR window + CA CIR window + API tails, or  
- **CA-primary** display with optional US footnote.

### 8.3 What not to do

- Treat each CIR `Product` line as one “reward redemption event” equal to API 60/100/200.  
- Count stars rows as graph visits.  
- Use reload bonus stars as visits.

---

## 9. Scope rules (page metrics)

| Metric | Scope |
|--------|--------|
| Activity graph (`activity.days`) | All `counts_as_visit` orders (US + CA + API), by `local_date` |
| Top ordered items | Items on all active purchases (all countries/sources) |
| Top Starbucks / visit counts by store | `in_gta_catalog` only |
| Standalone visited / remaining / to-visit / map | GTA catalog ⋈ visits with `in_gta_catalog` |
| Unmatched list | Purchases with a store name but not resolved to catalog |
| Stars earned/redeemed | §8 policy |
| US-only stores | Items yes; GTA geography widgets no |

### Store resolution order (persist on event)

1. `store_number` exact → `stores-gta.json`  
2. Alias map  
3. `name_key` exact (after Food Court/C normalization)  
4. Fuzzy ≥ 0.85  
5. Else `in_gta_catalog: false`, `match_method: unmatched`

---

## 10. Privacy boundary

| Data | Private raw / sidecar | Committed canonical `history.json` | Published site JSON/HTML |
|------|----------------------|-------------------------|---------------------------|
| Name, email, phone, address, DOB | raw CIR only | **no** | **no** |
| Masked PAN / svcID | raw only | **no** | **no** |
| Report file account codes | path local only | **no** | **no** |
| `historyId` / checkId / receiptNumber | raw source identity | may retain raw value for exact identity/reconciliation | **no** |
| Report source row IDs | source identity | may retain raw value for exact identity/reconciliation | **no** |
| Session cookie | never in repo | never | never |
| Store names, catalog numbers, regions | yes | yes | yes (aggregates / lists as designed) |
| Item names | yes | yes | top-N aggregates |
| Exact paid totals | optional | optional | optional / omit |
| Tip info | raw API only | **no** | **no** |

Provenance labels in public output stay at source enum level only. No public
artifact may contain raw source IDs, canonical IDs, report filenames/codes,
row-level source references, merge trails, fingerprints, or other detailed
reconciliation provenance. The committed canonical ledger is the boundary at
which the explicitly permitted raw source IDs may remain; generated JSON and
HTML are always sanitized projections.

---

## 11. How the activity graph derives from the ledger

Requirements baseline: GitHub-style grid; one cell per day; intensity by visits that day; normalized to that year’s max; hover shows date + count; count **orders/receipts**, not line items; span from earliest US history (~2022) through current year.

### 11.1 Visit set

```text
visits = canonical visits where
  status == "active"
  AND source_observation_ids is not empty
  AND local_date is not null
```

### 11.2 Day counts

```text
activity.days[d] = COUNT DISTINCT visit_id  for visits with local_date == d
activity.unit = "visits"
activity.timezone = "America/Toronto"
activity.max_count_by_year[y] = max(activity.days[d] for d in year y)
activity.total_days_active = |{ d : activity.days[d] > 0 }|
activity.total_events = sum(activity.days.values)
```

### 11.3 Cell intensity

```text
intensity(d) = activity.days[d] / activity.max_count_by_year[year(d)]
             → linear gray→green (UI detail)
```

### 11.4 What must not inflate a cell

- Multiple CIR lines of one order  
- Stars `Product` / `Points` / reload bonuses  
- Reload / Lsus / Lsca  
- Superseded duplicates after merge  
- UTC day-boundary mis-bucketing  

### 11.5 Rollup snippet (published shape)

```json
{
  "activity": {
    "unit": "visits",
    "timezone": "America/Toronto",
    "years": ["2022", "2023", "2024", "2025", "2026"],
    "max_count_by_year": { "2026": 4 },
    "days": {
      "2026-08-20": 1,
      "2026-08-22": 2
    },
    "total_days_active": 2,
    "total_events": 3
  },
  "stars": { "earned": 0, "redeemed": 0 },
  "date_range": { "min": "2022-01-02", "max": "2026-08-23" }
}
```

(`stars` filled via §8; numbers illustrative.)

---

## 12. Parser / pipeline notes (non-code checklist)

1. CIR = **CSV sections**; do not use space-separated regex or `line[11:19]` time hacks.  
2. Collapse purchase lines → orders **before** fingerprinting.  
3. Exclude reload item labels before visit emission.  
4. API merge on Toronto-local second + normalized store.  
5. Ledger is source of truth for import/stats; raw receipts remain a gitignored cache.  
6. Commit source-preserving `history.json` (including permitted raw source IDs);
   gitignore CIRs, `_ledger_private.json`, `page-*.json`, `receipts.json`, and
   `all-items.json`. Generated public outputs must strip those source IDs.  
7. Suggested lock tests:  
   - CA `2026-08-22 18:00:37` Bayview ↔ API receipt  
   - Multi-line order → 1 visit  
   - Reload/Lsus/Lsca → 0 visits  
   - UTC near-midnight → correct Toronto `local_date`  
   - US Bayview 2022 → GTA visited  
   - Stars: no CIR+API double count on a shared day (e.g. 2026-05-25)

---

## 13. Relation to current repo sketch

`scripts/starbucks_history.py` is a thin prototype. Relative to this design it must eventually:

- Parse real CIR CSV headers/rows  
- Collapse line items to orders  
- Carry `local_date`, `counts_as_visit`, `order_key`, stable `event_id`  
- Stop using amount+items content-hash as the only identity  
- Apply windowed Stars policy  
- Keep profile/card data and other private fields out of the committed ledger;
  raw source IDs are permitted there for exact identity and reconciliation  

This document is the target contract; implementation may land incrementally.

---

## 14. Summary

The canonical ledger is an **append-friendly, identity-keyed event list** where:

- **Visits** are order-grained, keyed by **local second + store**, reload-excluded;  
- **Graph cells** are distinct visits per **Toronto `local_date`**;  
- **GTA widgets** filter `in_gta_catalog`; **items/graph** can be global;  
- **Stars** are signed ledger rows with **windowed CIR-vs-API totals**;  
- **Provenance** is source enums only; **PII and native IDs** stay private.

`schema_version: 1` is the contract above.
