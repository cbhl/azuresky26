# Starbucks History Schema

## Status and scope

This document defines the canonical, source-preserving model for importing
Starbucks history from either:

- the authenticated Starbucks history API; or
- a Starbucks Customer Information Report export.

It is a design contract, not an implementation specification. The canonical
model must preserve source provenance and uncertainty. Public site data is a
sanitized projection of this model, not a copy of the raw account data.

The model supports multiple reports, countries, currencies, and source
systems. It must not assume that the country in an account profile is the
country of every transaction.

## Canonical field contract and privacy boundary

The committed implementation uses `data/starbucks/history.json` with this
top-level shape:

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

The authoritative record fields are `observation_id`/`source_kind` for source
observations, `visit_id`/`source_kinds`/`source_observation_ids` for canonical
visits, and `star_id`/`source_kind`/`source_observation_id` for Stars. A visit
also uses `local_second` when needed for source reconciliation. The exploratory
`events`, `event_id`, `identity`, `sources_ingested`, and `native_id_hash`
fields in earlier designs are not fields of this contract.

Raw source IDs are explicitly allowed in committed canonical history. This
includes source-qualified report row IDs (`<source>:line:<row>`) and API
history IDs (`api_export:history:<historyId>`), as well as equivalent source
identities required to deduplicate or reconcile. They are provenance, not
display data, and must not be copied into generated `starbucks.json`, other
public JSON, or HTML. Generated public IDs, if ever added, must be independent
opaque identifiers and must not encode or hash a source ID.

This is the privacy boundary: raw reports, native IDs, detailed source
references, account/profile/card data, and reconciliation metadata may remain
in private inputs or the committed canonical ledger only as explicitly
specified above; generated JSON/HTML are sanitized projections containing
selected display fields and aggregates only.

## Observed report format

The Customer Information Reports are section-oriented text files, not one
CSV document. The relevant sections are:

```text
Purchase Transactions,
Date/Time,Store Name,Order Total Charged,Item Name

Rewards Transactions,
Date/Time Earned,Stars Earned,Point Type
```

The USA report has the purchase header at
`usa-report.txt:30-33` and the rewards header at
`:2175-2176`. The Canada report has the corresponding headers at
`canada-report.txt:32-35` and `:1751-1752`.

The parser must identify sections and parse each section with its own CSV
schema. It must stop purchase parsing at the next section. It must not scan
the entire file for rows that happen to have four comma-separated fields.

## Source observations

### Purchase rows are item/charge rows

The `Order Total Charged` column is not a verified order total. Multiple rows
with the same timestamp and store represent the items or charges associated
with an order-like event. For example, the USA report has three rows at
`2026-04-04 18:11:12` for `Stevens Creek & DeAnza` at
`usa-report.txt:33-37`.

The Canada report has five rows at
`2026-08-08 06:36:12` for `Bayview & Romfield` at
`canada-report.txt:65-73`.

Each physical row is therefore a `purchase_line`. Its amount is
`line_amount`, not `order_total`.

### Store names can be blank

Rows such as `Reload Balance`, `Automatic Reload`, `Lsus`, and `Lsca` have a
blank store field. Examples occur in the USA report at
`usa-report.txt:43-49` and in the Canada report at
`canada-report.txt:35-37` and `:105-107`.

A blank store is meaningful account-level activity, not necessarily an
unmatched Starbucks store. Canonical records must preserve a null store and
classify the activity.

### The report profile is not transaction scope

The USA report profile says San Francisco, California, US at
`usa-report.txt:6-8`, but it contains Canadian
`Bayview & Romfield` purchases at `:351-369`, `:437-443`, and `:1919-1925`.

The Canada report profile says Richmond Hill, Ontario, CA at
`canada-report.txt:6-8` and contains extensive
`Bayview & Romfield` activity throughout 2026, including `:39-73`.

The same physical Canadian store can therefore occur in both exports. The
USA report's `Bayview & Romfield` rows must not be assigned `US` merely
because the report profile is American. Store-catalog resolution can assign
`CA` when it finds a unique Canadian catalog record; otherwise the
transaction country remains null.

### Rewards are a signed ledger

The reports contain `Points`, `Product`, `Expired`, `Stars for Reload`, and
`Partnership Card Reload` point types. Values can be positive or negative.
For example, the Canada report contains `-9.0,Product` and `25.0,Stars for
Reload` at `canada-report.txt:2130-2140`.

Rewards have dates but no time and no reliable order identifier. They cannot
be joined to a purchase solely by date.

## Canonical entities

The canonical store contains four entity types:

1. `report`: source-file and account/profile metadata.
2. `purchase_line`: one physical row in the purchase section.
3. `order_group`: a cautious, derived grouping of adjacent purchase lines.
4. `reward_entry`: one physical row in the rewards section.

API records remain source-distinct from report records. An API receipt can
have stable raw `historyId`, `checkId`, or receipt identifiers; a text-report
row has a source report plus row identity. The committed canonical ledger may
retain these source identities so repeated imports can be exactly deduplicated
and API/report records can be reconciled without erasing either source
identity. Generated public projections must strip the raw identities.

## Report metadata schema

```json
{
  "record_type": "report",
  "report_id": "canada-report",
  "source_system": "customer_information_report",
  "source_filename": "canada-report.txt",
  "profile_country": "CA",
  "report_currency": "CAD",
  "account_creation_date": "2024-08-14",
  "parser_version": "1",
  "imported_at": "2026-08-28T12:00:00Z"
}
```

`profile_country` is account/profile metadata only. It is not a fallback for
`transaction_country`. `report_currency` must be supplied or independently
validated; it must not be inferred per transaction from profile location.

Profile name, address, email, phone number, stored-value-card numbers, and
similar fields are private metadata. They are not part of public derived
site data.

## Purchase-line schema

```json
{
  "record_type": "purchase_line",
  "source_system": "customer_information_report",
  "source_report_id": "canada-report",
  "source_section": "Purchase Transactions",
  "source_row_number": 67,
  "occurred_at": "2026-08-08T06:36:12",
  "occurred_at_precision": "second",
  "timezone": null,
  "timezone_source": null,
  "store_name_raw": "Bayview & Romfield",
  "store_key": null,
  "transaction_country": null,
  "country_resolution": "unresolved",
  "kind": "purchase_item",
  "activity_type": null,
  "raw_item_name": "Tr Lemonade Cool Lime",
  "line_amount": "5.16",
  "currency": "CAD",
  "order_key": "canada-report:purchase-group:12"
}
```

For account activity in the same source section:

```json
{
  "record_type": "purchase_line",
  "source_system": "customer_information_report",
  "source_report_id": "canada-report",
  "source_section": "Purchase Transactions",
  "source_row_number": 35,
  "occurred_at": "2026-08-22T18:00:56",
  "occurred_at_precision": "second",
  "timezone": null,
  "timezone_source": null,
  "store_name_raw": null,
  "store_key": null,
  "transaction_country": null,
  "country_resolution": "not_applicable",
  "kind": "account_activity",
  "activity_type": "reload",
  "raw_item_name": "Reload Balance",
  "line_amount": "72.52",
  "currency": "CAD",
  "order_key": null
}
```

Required `kind` values are:

```text
purchase_item
account_activity
unknown_account_activity
```

At minimum, `Reload Balance` and `Automatic Reload` map to `reload`.
`Lsus` and `Lsca` must be preserved and classified as
`loyalty_adjustment` only when their semantics are confirmed; otherwise use
`unknown_account_activity`. Neither is a purchased product or store visit.

`line_amount` should be represented as a decimal-compatible value. Strings
are preferred in persisted JSON to avoid accidental binary floating-point
rounding. The source header must not cause it to be called `order_total`.

## Order grouping

The report contains no order ID, receipt number, check ID, or explicit order
boundary. Grouping is consequently heuristic.

The required deterministic grouping rule is:

1. Parse physical rows in source order.
2. Group adjacent `purchase_item` rows only when their timestamps are exactly
   equal and their normalized store names are exactly equal.
3. Do not cross a non-purchase/account-activity row.
4. Do not group rows with a blank store.
5. Do not merge non-adjacent rows merely because timestamp, store, item, and
   amount happen to match.
6. Preserve source row order within a group.
7. Assign a generated `order_key`; do not present it as a Starbucks order ID.

Example:

```json
{
  "record_type": "order_group",
  "order_key": "canada-report:purchase-group:12",
  "source_system": "customer_information_report",
  "source_report_id": "canada-report",
  "occurred_at": "2026-08-08T06:36:12",
  "occurred_at_precision": "second",
  "timezone": null,
  "store_name_raw": "Bayview & Romfield",
  "store_key": null,
  "transaction_country": null,
  "currency": "CAD",
  "items": [
    {
      "source_row_number": 65,
      "raw_item_name": "Add Dried Fruit Topping",
      "line_amount": "0.70"
    },
    {
      "source_row_number": 67,
      "raw_item_name": "Tr Lemonade Cool Lime",
      "line_amount": "5.16"
    },
    {
      "source_row_number": 69,
      "raw_item_name": "Xtr Green Coffee Extract Blend",
      "line_amount": "0.59"
    },
    {
      "source_row_number": 71,
      "raw_item_name": "Whole Grain Oatmeal",
      "line_amount": "3.65"
    },
    {
      "source_row_number": 73,
      "raw_item_name": "Tall Iced Coffee",
      "line_amount": "3.65"
    }
  ],
  "line_amount_sum": "13.75",
  "reported_order_total": null,
  "order_id": null,
  "grouping_method": "adjacent_same_timestamp_and_store",
  "grouping_confidence": "heuristic"
}
```

`line_amount_sum` is a derived sum of source rows. It is not a verified
charged order total. Repeated identical items must remain separate lines;
the report does not provide quantity semantics.

## Reward-entry schema and Stars policy

```json
{
  "record_type": "reward_entry",
  "source_system": "customer_information_report",
  "source_report_id": "canada-report",
  "source_section": "Rewards Transactions",
  "source_row_number": 2132,
  "earned_on": "2026-06-08",
  "earned_on_precision": "day",
  "stars_delta": -9.0,
  "point_type": "Product",
  "profile_country_context": "CA"
}
```

The numeric field is `stars_delta`, not `stars_earned`, because values may
be negative.

Preserve the source `point_type` exactly. Known interpretations are:

```text
Points                   accrual-like entry; signed value is authoritative
Product                  product redemption/spend deduction
Expired                  expiration deduction
Stars for Reload         reload-related reward accrual
Partnership Card Reload  reload/card-related activity; not ordinary purchase stars
```

These interpretations are reporting categories, not permission to discard
the original type. A summary may calculate:

```json
{
  "net_stars_delta": 123.4,
  "earned_by_type": {
    "Points": 456.7,
    "Stars for Reload": 25.0
  },
  "spent_by_type": {
    "Product": 321.3
  },
  "expired_by_type": {
    "Expired": 42.0
  }
}
```

The underlying signed ledger remains the source of truth. Do not join reward
entries to purchases by date; rewards have no time or transaction ID and
multiple entries can share a date.

## Dates, times, and local dates

Purchase timestamps are exported as `YYYY-MM-DD HH:MM:SS` with no timezone or
offset. They must be stored as timezone-unknown local civil datetimes:

```json
{
  "occurred_at": "2026-08-22T18:00:37",
  "occurred_at_precision": "second",
  "timezone": null,
  "local_date": "2026-08-22"
}
```

Do not append `Z`. Do not silently convert the timestamp to UTC. A timezone
may be added only when supplied by a trusted source, with

Rewards have date-only precision:

```json
{
  "earned_on": "2026-06-07",
  "earned_on_precision": "day"
}
```

Do not represent a date-only reward as midnight in an invented timezone.

For reporting, `local_date` is the first ten characters of the source local
timestamp. It is not a UTC-derived date. If an API record contains an offset,
the importer must define whether the report is based on source-local date or
accounting date and apply that choice consistently.

## Ordering invariants

Source order is provenance, not canonical order. Reports are generally newest
first, but the USA report mixes US and Canadian activity and source exports
must not be treated as country-separated streams.

Every source record must retain `source_row_number`. Canonical presentation
order is:

```text
occurred_at descending,
source_report_id ascending,
source_row_number ascending
```

For rewards, use `earned_on descending`, then report ID and source row number.
For records with equal timestamps, source row order is the stable tie-breaker.

## Dedupe and identity rules

The primary source identity is:

```text
source_system + source_report_id + source_row_number
```

For API records, use:

```text
source_system + history_id
```

when `history_id` is present. API page offset and array position are never
identities because pagination windows can move.

Do not deduplicate report rows by timestamp, store, item, or amount. Those
values can legitimately repeat. Do not deduplicate repeated identical item
lines inside one order group.

If an API record and a report row appear to represent the same purchase,
retain both source records and create an explicit reconciliation record with
confidence and evidence. Never silently replace one with the other.

## Store and country resolution

Store resolution should be recorded, not just applied:

```json
{
  "store_name_raw": "Bayview & Romfield",
  "store_key": "catalog:store-number-or-location-id",
  "transaction_country": "CA",
  "country_resolution": "exact_catalog_name",
  "resolution_confidence": 1.0
}
```

Recommended resolution order:

1. exact store number, when a source provides one;
2. unique normalized catalog name;
3. curated alias;
4. fuzzy match only with explicit confidence and review output;
5. unresolved.

For the report exports, store number is absent, so Bayview & Romfield is a
name-based resolution. A unique Canadian catalog match may set

Current standalone/grocery/embedded classification is catalog-derived and
may change over time. The canonical record should retain the resolved
required. It must not imply that the Starbucks API supplied a first-class
standalone flag.

## Canonical invariants

The ingestion pipeline must enforce these invariants:

- Every canonical source record has a source system, source report/run ID,
  source section, and source row or API identity.
- Every purchase line is either `purchase_item` or explicit account activity;
  reloads and loyalty adjustments are never products.
- A blank store is represented as null, never the literal string `Unknown` in
  canonical data.
- `line_amount` is not an order total.
- `reported_order_total` is null unless a source explicitly provides one.
- Generated order groups are marked heuristic.
- Purchase timestamps never receive an invented UTC suffix.
- Reward values are signed `stars_delta` values and retain `point_type`.
- Profile country never becomes transaction country by fallback.
- Currency is explicit at report/source configuration level.
- Store matching records method and confidence.
- Public projections contain no authentication material or unnecessary
  account identifiers.
- A failed or incomplete fetch cannot replace a previously valid persistent
  history with an empty dataset without an explicit operator decision.

## Privacy boundary

Raw API responses, session cookies, account profile data, and stored-value-card
identifiers are private inputs. Source IDs in the canonical history are a
separate provenance exception: API `historyId`, `checkId`, receipt
identifiers, and report source row IDs may be committed there for exact
  deduplication and reconciliation. They must not be copied, exposed through
  detailed source references, or made reversible in generated public site data
  or HTML.

The public projection may expose aggregate counts and intentionally selected
display fields such as date, store name, item display name, and derived
 totals, subject to the site's privacy decision. Omit opaque IDs and
 source/provenance references; canonical reconciliation is not a public
 feature.

At minimum, never publish in `starbucks.json` or HTML:

- session cookies or authorization headers;
- email, phone, address, or stored-value-card data;
- raw `svcID`, `historyId`, `checkId`, receipt identifiers, report source row
  IDs, or equivalent API fields;
- full raw API responses;
- private profile metadata copied from a report.

## Public projection and graph derivation

The static site should consume a derived projection, not the canonical raw
history. A minimal public aggregate can retain the existing site contract:

```json
{
  "generated_at": "2026-08-28",
  "date_range": {
    "min": "2022-01-02",
    "max": "2026-08-22"
  },
  "history_count": 1234,
  "receipt_count": 456,
  "standalone": {
    "total": 195,
    "visited": 42,
    "remaining": 153
  },
  "top_items": [],
  "top_stores": [],
  "recent": [],
  "to_visit": [],
  "map": {
    "bbox": {},
    "stores": []
  }
}
```

The graph is derived from canonical `order_group` and store-resolution data:

- store nodes come from the current catalog;
- an order-to-store edge is created only for a `purchase_item` order group
  with a resolved `store_key`;
- edge weight is the number of distinct canonical order keys, not the number
  of item lines;
- item counts come from purchase lines, with repeated lines preserved;
- account activity and reward entries create no store-visit edges;
- standalone visited status is the existence of at least one resolved order
  edge to a currently classified standalone store;
- `to_visit` is the catalog standalone-node set minus visited standalone
  nodes;
- map marker `visits` is the order-group edge count for that store;
- unmatched records remain available for review but do not create catalog
  nodes.

For API receipts, each stable API receipt/history identity supplies one order
group. For report imports, the adjacent-row grouping rule supplies the
generated order key. This keeps multi-line reports from inflating visit
counts while preserving line-level item counts.

The public `recent` list should be selected from order groups, not raw lines,
and should identify its source/grouping confidence if that distinction is
shown. Date ranges for purchase activity should use purchase `local_date`;
reward dates should be reported separately rather than silently extending the
purchase range.

## Import output separation

Recommended persistence layers are:

```text
committed canonical history     source-preserving reports/API records,
                                including raw source IDs for identity
private or controlled archive   raw API pages, if retention is required
public report-history.json       sanitized aggregate snapshots
public starbucks.json            current site projection
```

The current map renderer only needs the existing `map` block and can remain
unchanged when report-history fields are added. A separate public history
file is preferable to repeatedly appending snapshots to the large current
`starbucks.json` payload, reducing merge conflicts and keeping raw source IDs
and other private source records out of the static build.
