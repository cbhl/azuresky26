# Starbucks History Schema: Final Design

This is the implementation contract for the durable Starbucks history used to
build `/starbucks/`. It incorporates the two report designs and their
cross-reviews in the adjacent files.

## Layers

- Raw reports and API responses remain local, ignored inputs.
- `data/starbucks/history.json` is a committed canonical ledger. It retains
  source provenance and source-qualified raw IDs needed for exact
  deduplication and reconciliation, but no profile data or card data. This is
  the one intentional privacy exception for source identifiers: the committed
  canonical file is not itself a public projection.
- `data/starbucks/starbucks.json` is a generated public projection.

The privacy boundary is the build from the canonical ledger to generated
JSON/HTML. Public output may contain only selected display fields and
aggregates; it must strip native API IDs, report IDs and row references, raw
source observation IDs, detailed provenance, and private account data.
Canonical IDs are internal provenance fields, not public IDs. A stable
source-derived identifier, including a hash, is still a source reference.

The ledger has source observations and canonical visits. Source observations
are never deleted or silently replaced. Canonical visits are the only records
used for visit, store, item, and activity metrics.

## Top-level shape

```json
{
  "schema_version": 1,
  "activity_timezone": "America/Toronto",
  "updated_at": "2026-08-28T00:00:00Z",
  "sources": ["us_customer_information_report", "ca_customer_information_report", "api_export"],
  "observations": [],
  "visits": [],
  "stars": []
}
```

`observations` are physical report rows or API-derived records. `visits` are
order-grain records after report line grouping and cross-source
reconciliation. `stars` are signed reward entries and never visits.

The field names in this document are authoritative: observations use
`observation_id` and `source_kind`; visits use `visit_id`, `source_kinds`, and
`source_observation_ids`; Stars use `star_id`, `source_kind`, and
`source_observation_id`. Do not substitute the older `events`, `event_id`, or
nested `identity` fields from exploratory schema documents.

## Visit record

```json
{
  "visit_id": "opaque-content-id",
  "status": "active",
  "occurred_at": "2026-08-22T22:00:37Z",
  "occurred_at_precision": "second",
  "time_basis": "utc",
  "local_date": "2026-08-22",
  "source_profile_countries": ["US"],
  "currency": "CAD",
  "amount_lines_sum": "3.25",
  "amount_order_total": "3.41",
  "store": {
    "name_raw": "Bayview & Romfield",
    "name_key": "bayview and romfield",
    "catalog_store_number": "23280-204964",
    "in_gta_catalog": true,
    "standalone": true,
    "region": "York Region",
    "match_method": "exact_name"
  },
  "items": [
    {"name": "Iced Green Tea Lemonade", "name_key": "iced green tea lemonade", "quantity": null}
  ],
  "source_kinds": ["us_customer_information_report", "api_export"],
  "source_observation_ids": ["ca_customer_information_report:row:67"],
  "dedupe": {"method": "confirmed_local_second_store", "confidence": "high"}
}
```

Report timestamps are local wall-clock values and retain the printed civil
`local_date`; they do not receive a fabricated `Z`. API timestamps are parsed
as UTC and converted to `America/Toronto` for `local_date` and reconciliation.
Canonical source observation IDs may contain the report source row identity or
the API's `historyId`, `checkId`, or receipt identifier. These raw IDs are
committed only as canonical provenance for exact deduplication and
reconciliation. Canonical `visit_id` and `star_id` values are stable opaque
internal values, not public IDs; they may be derived from source IDs for ledger
stability. `starbucks.json` and HTML omit them, the raw IDs, and detailed
source references entirely.

Report purchase rows are grouped into one visit only when adjacent, both are
product rows, and timestamp plus normalized store name are identical. Amount
is never part of this grouping key. The report amount is stored as
`amount_lines_sum` because the source column is misleadingly named “Order
Total Charged” and is actually a line charge. The grouping is marked
heuristic. Blank-store rows are account activity, never visits.

Cross-source reconciliation creates one visit projection while preserving all
source observations. For Canada API/CIR data, the primary evidence is the
same Toronto-local second and normalized store name. Store-name aliases such
as `Food Court`/`Food C` are deterministic normalization. Amount and item
names are weak corroboration only because CIR line charges and API totals/name
vocabularies differ. Ambiguous matches remain separate and are flagged rather
than automatically collapsed.

## Store scope

`profile_country` describes the report account, not a transaction. A US report
row named `Bayview & Romfield` resolves to the unique Canadian GTA catalog
store by exact name and therefore counts for GTA metrics. Unrelated US stores
remain unmatched to the Canadian catalog and never affect GTA visited,
top-store, standalone, remaining, history-count, map, or `/to-visit/` data.

All purchase items from all sources, including unmatched stores, contribute to
global top ordered items. Canada report items are never dropped because their
store is unmatched. Store resolution gates geography metrics only.

## Items and non-purchases

Each source line is preserved as an item observation. `quantity` is null when
the source does not report quantity. API options/modifiers may be retained in
ignored raw input, but modifiers from CIR are not silently promoted to product
quantities. Top-item counts are source line counts on canonical visits, with
API/CIR duplicates removed at the visit projection.

Reloads (`Reload Balance`, `Automatic Reload`, `Lsus`, `Lsca`), balance
transfers, and rewards are explicit non-visit observations. They do not count
as items, stores, visits, or graph cells.

## Stars ledger

```json
{
  "star_id": "opaque-content-id",
  "occurred_on": "2026-08-22",
  "occurred_on_precision": "day",
  "stars_delta": -57.5,
  "point_type": "Product",
  "source_kind": "ca_customer_information_report",
  "status": "active"
}
```

Stars retain signed deltas and original point types. `Product` and `Expired`
negative rows are deductions; `Points`, promotions, reload bonuses, and
partnership accruals retain their categories. Rewards are not joined to a
purchase by date. The published total uses one source-of-truth series per
loyalty program and coverage interval: complete CIR rewards through the
report coverage end, then API-only tail rows. API purchase display stars are
annotations unless explicitly selected for an uncovered interval. The
projection records this policy so it cannot sum overlapping CIR and API rows.

## Activity graph

The graph is derived from active canonical visits, not observations, line
items, reloads, or Stars:

```text
daily_counts[local_date] = COUNT DISTINCT visit_id
```

It includes all purchases in the reports and API, including visits outside
the GTA, because the requested span begins with the US history in 2022. The
page’s GTA store counters remain catalog-scoped. The graph covers every year
from the first purchase date in the US report through the current build year.
Each year’s cell intensity is `daily_count / that_year_max_daily_count`, with
zero for inactive days. The generated activity block retains raw daily counts,
year maxima, year list, timezone, and date labels; the template renders a
static day grid with native hover titles.

## Invariants

- A source observation has one source kind and stable source-qualified identity;
  canonical history may retain the raw source ID needed for exact
  deduplication and reconciliation.
- A visit has at least one source observation and one or more items.
- A source API receipt can map to at most one active visit.
- A CIR line group is never treated as multiple visits.
- A reload, reward, blank-store account row, or balance transfer never counts as a visit.
- US-only stores never enter GTA counters, top stores, map, history counts, or `/to-visit/`.
- An exact unique GTA catalog name match from a US report can enter GTA counters.
- Every source item is retained in the canonical item set even if its store is unmatched.
- Activity counts distinct active visit IDs and uses local civil dates.
- A shorter API refresh never removes older ledger visits.
- No generated public artifact (`starbucks.json` or HTML) contains profile PII,
  card numbers, report export IDs, report row IDs, native API IDs, canonical
  observation/visit/Star IDs, or detailed source references.
