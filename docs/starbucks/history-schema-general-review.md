# Review: `history-schema-grok.md`

This review compares `docs/starbucks/history-schema-grok.md` with the actual
USA and Canada Customer Information Reports and with the repository's current
Starbucks pipeline. It treats the Grok document as a design proposal, not as
implemented behavior.

## Findings

### P0: The country field is wrong for the documented USA Bayview example

`history-schema-grok.md:368-384` creates a USA-report `Bayview & Romfield`
event with `country: "US"`, while `history-schema-grok.md:69` correctly says
the USA report contains Canadian GTA visits and that profile country is not
transaction scope.

The source report profile is San Francisco, US at
`usa-report.txt:6-8`, but the same report contains
Bayview & Romfield rows at `:351-369`, `:437-443`, and `:1919-1925`. The Canada
profile and the same store appear in `canada-report.txt:6-8`

The example must not assign `US` without evidence. A catalog match may resolve
the physical store to `CA`, but the source report alone provides neither
transaction country nor timezone. Use separate fields:

```json
{
  "profile_country": "US",
  "transaction_country": "CA",
  "country_resolution": "unique_catalog_store"
}
```

or, before catalog resolution:

```json
{
  "profile_country": "US",
  "transaction_country": null,
  "country_resolution": "unresolved"
}
```

Do not use a single `country` field for both meanings. This is a correctness
issue, not merely a naming issue, because the proposed field feeds graph and
GTA metrics.

### P0: Automatic CIR/API merging can create false visits or erase provenance

The proposed identity tiers at `history-schema-grok.md:585-596` make
`local-second + normalized-store` the primary CIR/API merge key and allow a
date/store/amount/time fallback at tier 2. The document then recommends
superseding the loser.

This is unsafe:

- the reports have no receipt/order ID;
- `Bayview & Romfield` occurs in both reports and across years;
- the same person can make two orders at the same store and second;
- CIR amounts are per-line amounts, while API `total` is a receipt total;
- CIR names are abbreviated and modifiers can be separate lines;
- the report and API can represent different currencies/programs;
- the API endpoint is a moving history window.

The document itself says at `:78` and `:107` that item grains differ and that
`Product` rows must not be 1:1 merged, but the purchase merge algorithm still
automatically merges on a weak key.

Required correction:

- keep `source_system + source_report_id + source_row_number` as immutable
  CIR identity;
- keep API `source_system + history_id` as immutable API identity;
- create a separate `reconciliation` record only after corroboration;
- never supersede source events merely because they share a timestamp/store;
- require an explicit confidence/evidence record before graph deduplication;
- do not use tier 2 as an automatic merge rule.

If the product needs one visit in the graph, derive a separate
`visit_cluster_id` with `confirmed`, `probable`, or `unresolved` status. Do not
destroy either source event.

### P0: The Stars policy does not prove source coverage and can still double count

The window rule at `history-schema-grok.md:650-663` is directionally useful,
but it is not sufficient as an ingestion contract.

Problems:

- `cir_max_date` does not prove that the CIR contains every reward entry up to
  that date.
- API Point rows and API `starsEarnedDisplay` can describe the same earn, but
  the fallback in `:656` says to add the display value when a “gap remains”
  without defining how a gap is detected.
- `Product` rows are signed ledger deductions. The Canada report explicitly
  has `2026-08-22,-2.5,Product` and `-57.5,Product` at
  `canada-report.txt:1758-1764`; those are not two
  independent reward redemptions equivalent to an API `-60` row.
- The proposal stores `stars_on_purchase` on a purchase event while also
  storing API Point events. There is no invariant that prevents a rollup from
  summing both.
- US and CA may be separate loyalty programs, but the document does not define
  how to identify program/account scope when the same source export contains
  cross-border stores.

Required correction:

1. Store every source Stars row with signed `stars_delta`, original point type,
   source identity, and a `program_scope`.
2. Store API `starsEarnedDisplay` only as an annotation unless it is the sole
   available source for a defined interval.
3. Select exactly one source-of-truth series per program and interval.
4. Publish coverage metadata, for example:

```json
{
  "stars_rollup": {
    "program": "CA",
    "source_policy": "ca_cir_through_2026-08-23_then_api_tail",
    "included_sources": ["ca_customer_information_report", "api_point_tail"],
    "excluded_overlap": true,
    "display_earn_annotations_in_total": false
  }
}
```

5. Never infer a missing interval merely from a date boundary. Require an
   explicit source coverage declaration or report a partial total.

The current repo API path also does not ingest API Point rows into the history
ledger. `scripts/starbucks_fetch.py:257-269` selects Redemption rows for
receipt fetching, and `:310` only attempts to merge receipt-derived events.
Therefore the proposed API Stars contract cannot be satisfied by the current
fetch pipeline without a separate API-history normalization step.

### P0: Graph timezone rules contradict each other for US CIR rows

The proposal says the graph always uses `America/Toronto` at
`history-schema-grok.md:129-130` and `:632-634`, but it also says at `:407`
that US CIR rows retain store-local wall dates and that graph cells use the
report's civil date.

Those are different rules. The USA report contains California local-looking
times such as `2026-04-04 18:11:12` at
`usa-report.txt:33`; interpreting that wall time
as Toronto time is incorrect.

Required model:

```json
{
  "occurred_at": "2026-04-04T18:11:12",
  "time_basis": "local_wall",
  "event_timezone": null,
  "local_date": "2026-04-04",
  "local_date_basis": "source_civil_date"
}
```

For API instants, convert to the configured activity timezone and record the
conversion. For CIR rows, use the printed civil date unless a store timezone
is independently resolved. The graph contract must say whether it supports
mixed local civil dates or only a fully timezone-normalized population. It
cannot call both policies `America/Toronto`.

### P1: The proposed `quantity: 1` invents quantity semantics

The event examples at `history-schema-grok.md:225-231`, `:330-341`, and
`:386-390` assign `quantity: 1`, while `:78` says CIR item cardinality does not
reliably match API item cardinality.

The reports provide one physical line and amount, not a quantity column. A
repeated item may be two purchased units, two modifiers, or two exported
charges. The model must preserve lines rather than silently assert quantity.

Use:

```json
{
  "source_row_number": 73,
  "raw_name": "Tall Iced Coffee",
  "line_amount": "3.65",
  "quantity": null,
  "quantity_basis": "not_reported"
}
```

If a later normalization collapses identical lines for display, retain
`line_count` and make it clear that it is a count of source lines, not a
verified product quantity.

### P1: The grouping pseudocode uses a global key and loses source identity

At `history-schema-grok.md:568-581`, grouping uses only:

```text
YYYY-MM-DDTHH:MM:SS|name_key(store)
```

This is acceptable only as an intra-report, adjacent-row grouping key. As a
canonical or cross-source identity it is unsafe. The document later uses the
same kind of key for CIR/API matching at `:590`.

The contract should require:

```text
order_key = source_report_id + source-group ordinal
```

and store the grouping evidence:

```json
{
  "grouping_method": "adjacent_same_timestamp_and_store",
  "source_row_numbers": [65, 67, 69, 71, 73],
  "grouping_confidence": "heuristic"
}
```

The exact timestamp/store rule must remain adjacent-only. It must not group
non-adjacent rows or rows separated by account activity. The report examples
at `canada-report.txt:65-73` demonstrate the valid
multi-line case; the source has no explicit order boundary.

### P1: Report parsing requirements are not implementable by the current prototype

The design correctly requires CSV sections at `history-schema-grok.md:43-58`,
but the repository prototype does not implement that contract:

- `scripts/starbucks_history.py:11-16` uses whitespace-oriented regular
  expressions rather than a CSV reader;
- `scripts/starbucks_history.py:41` collapses whitespace before parsing;
- `scripts/starbucks_history.py:52-72` parses one line as one purchase event
  and does not group adjacent rows;
- `scripts/starbucks_history.py:59-61` drops reload/balance rows instead of
  preserving classified account activity;
- `scripts/starbucks_history.py:73-89` stores absolute Stars values as
  `stars_earned`/`stars_redeemed`, losing signed `stars_delta` semantics;
- the regex parser has no robust quoted-field handling.

The design should explicitly require a parser result containing rejected-row
diagnostics, section boundaries, physical source line numbers, and the report
fingerprint. “CSV sections” alone is not enough for safe re-import.

The current modified `scripts/starbucks_import.py` also expects a different
shape from the proposed schema: it reads `event.get("store")` as a string and
`event["items"]` as strings at `:261-272`, whereas the proposal defines a
nested `store` object and item objects. It also expects `kind` values
`stars_earned` and `stars_redeemed` at `:280-282`, while the proposal uses
`kind: "stars"` and `stars_delta`. The design needs an explicit adapter or a
single final schema before implementation begins.

### P1: Current API history retention is not the proposed append-only ledger

The proposal requires refreshes not to delete events at
`history-schema-grok.md:133` and `:607-615`, but the existing fetcher writes a
fresh current API result to `all-items.json` at
`scripts/starbucks_fetch.py:159-203`.

The receipt cache is incremental by `historyId` at `:245-272`, but raw history
pages and flattened history are not durable canonical history. A shorter API
window can still make the next import's `history_count` shrink, and a failed
or empty partial response can overwrite the current flattened result.

The contract needs an atomic refresh rule:

- validate the response shape and paging before replacement;
- reject suspicious zero/partial results unless explicitly forced;
- merge API events by stable native identity in private storage;
- retain first/last seen and source coverage;
- never use page offset or array position as identity.

It should also clarify whether the proposed public `history.json` is an event
ledger or only a sanitized derived snapshot. The current repository ignores
`receipts.json`, `all-items.json`, and page files under `.gitignore:10-20`.

### P1: The graph metric is underspecified and conflicts with the current site

The proposal calls the graph metric “visits” and uses distinct
`identity.visit_key` values at `history-schema-grok.md:717-737`, which is the
right grain. However:

- `visit_key` is shown as equal to `event_id` at `:274`, but `event_id` is a
  generated public ID and the merge rules can generate a new ID after source
  reconciliation;
- source events that are both retained and unresolved could produce two graph
  visits for one real order;
- `activity.total_events` is a sum of day counts, but the current modified
  importer labels its activity unit `receipts` at
  `scripts/starbucks_import.py:283-291` and still counts API receipts directly
  at `:165-179`;
- the current site template does not render `activity` or `stars`; it only
  renders the existing aggregate fields at `templates/starbucks.html:8-73`.

The contract should define separate metrics:

```text
source_order_count       number of source order groups
confirmed_visit_count    deduplicated/reconciled visit clusters
graph_day_visit_count    distinct confirmed visit clusters per bucket
unresolved_order_count   excluded or separately displayed candidates
```

For a strict graph, only `confirmed` clusters should count. If probable
matches are included, the policy must be explicit and must not claim exact
visit counts.

The store graph should also distinguish its edge metric from the daily graph:

- daily graph: distinct visit clusters by local date;
- store `visits`: distinct visit clusters resolved to that store;
- item count: source purchase lines, with no invented quantity;
- standalone visited: existence of at least one included visit cluster;
- unmatched/uncertain: excluded from catalog edges but retained for review.

### P1: GTA scope is correct in principle but the `country` rule can leak into it

The scope table at `history-schema-grok.md:673-683` correctly separates global
items/activity from GTA store metrics. However, the sample USA Bayview event
has `country: "US"` while `in_gta_catalog: true` at `:375-384`. This makes
`country` unsuitable for filtering and invites a later implementation to
exclude a real GTA visit.

Use catalog geography as the authoritative GTA predicate:

```text
in_gta_catalog = true only after a unique catalog resolution
standalone = catalog classification, versioned with the catalog snapshot
```

Country is descriptive metadata and must not override catalog geography.
Store classification is also time-sensitive; if historical reproducibility is
required, persist the catalog snapshot/version used for resolution.

### P1: Reload and `Lsus`/`Lsca` classification is overconfident

The document maps all of `Reload Balance`, `Automatic Reload`, `Lsus`, and
`Lsca` to `kind: "reload"` at `history-schema-grok.md:81-91` and `:280-288`.
The reports establish that these are not store visits, but they do not by
themselves prove that `Lsus` and `Lsca` have identical reload semantics.

The safer contract is:

```text
Reload Balance / Automatic Reload -> activity_type=reload
Lsus / Lsca                      -> activity_type=balance_adjustment (or unknown)
```

Preserve the raw label. All are `counts_as_visit: false`, but only confirmed
semantics should be used for financial or balance rollups.

### P2: Source metadata and fingerprints need a privacy decision

The privacy table at `history-schema-grok.md:695-707` is good about cookies,
PII, and native IDs, but the proposed public ledger still exposes more than
the stated privacy goal necessarily permits:

- exact dates/times, store names, item names, and amounts can reconstruct a
  person's routine;
- stable public `event_id` values enable tracking even if native IDs are
  removed;
- `sources_ingested[].content_fingerprint` at `:151-176` is a durable account
  artifact and is unnecessary in public output;
- source labels such as US/CA report origin reveal account/program scope;
- `history.json` is described as committable at `:25-27`, while the privacy
  table permits exact totals and item names at `:704-706` without a concrete
  publication decision.

Recommended boundary:

- keep raw reports, native IDs, fingerprints, row-level amounts, and detailed
  item/order events private;
- keep the canonical source ledger private or controlled unless there is an
  explicit decision to publish row-level history;
- publish only the aggregate projection needed by the static site;
- if public event IDs are needed, use non-linkable per-build IDs or omit them;
- keep source coverage metadata private unless it is intentionally part of
  the report.

The repository already treats raw Starbucks artifacts as private in
`.gitignore:10-21`; the proposed design should not weaken that boundary by
making `history.json` a default public event ledger.

## Missing fields required for a practical contract

The Grok schema should add or clarify:

```json
{
  "source_ref": {
    "system": "customer_information_report",
    "report_id": "private-or-controlled-id",
    "section": "Purchase Transactions",
    "row_number": 67,
    "content_fingerprint": "private"
  },
  "raw_label": "Tr Lemonade Cool Lime",
  "line_amount": "5.16",
  "currency_basis": "report_config",
  "quantity": null,
  "quantity_basis": "not_reported",
  "profile_country": "CA",
  "transaction_country": null,
  "country_resolution": "unresolved",
  "event_timezone": null,
  "local_date_basis": "source_civil_date",
  "order_key": "canada-report:purchase-group:12",
  "grouping_method": "adjacent_same_timestamp_and_store",
  "grouping_confidence": "heuristic",
  "reconciliation": {
    "cluster_id": null,
    "status": "unresolved",
    "evidence": []
  }
}
```

The API variant additionally needs a private native identity reference and a
separate field for the API receipt total versus item/line amounts. The report
variant must not pretend that `amount_order_total` exists.

## Recommended corrected direction

Retain the good high-level separation in `history-schema-grok.md`:

- private acquisition data;
- durable source-preserving history;
- public aggregate projection;
- order-grain visits;
- signed Stars ledger;
- catalog-based GTA metrics.

Change the contract as follows:

1. Use source-qualified immutable identities; never automatically merge on
   timestamp/store or supersede weak-key matches.
2. Represent report rows as line items with `line_amount`; derive adjacent
   order groups with an explicit heuristic and source row references.
3. Keep profile country separate from transaction country. Resolve Bayview &
   Romfield by catalog evidence, not USA/Canada report origin.
4. Preserve signed reward rows and choose one declared Stars source per
   program/coverage interval. Do not add purchase annotations to ledger sums.
5. Separate event-local civil dates from the graph timezone. Do not interpret
   US wall-clock rows as Toronto timestamps.
6. Make graph counts operate on confirmed deduplicated visit clusters, while
   exposing source-order and unresolved counts separately.
7. Keep fingerprints, report identifiers, amounts, and row-level history out
   of the public static projection by default.
8. Define an adapter from the canonical schema to the current importer, or
   update the design to match the importer; the current shapes are not
   compatible.

## Overall assessment

The proposal has a useful architecture and correctly identifies the key
hazards of multi-line CIR rows, cross-country Bayview activity, API retention,
and Stars overlap. It is not ready as a canonical contract. The country
example, automatic dedupe tiers, Stars fallback, timezone model, quantity
field, and public-ledger privacy boundary can all produce materially wrong or
overexposed output. Resolve the P0 findings before implementation; resolve
the P1 findings before treating `history.json` as the source of truth for
site metrics.
