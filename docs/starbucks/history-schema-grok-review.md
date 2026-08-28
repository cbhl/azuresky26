# Review: `history-schema-general.md`

Reviewer lens: real US/CA Customer Information Reports, CA API artifacts in-repo, and `screenshots/add-starbucks-history.md` / current Starbucks pipeline requirements.

**Document under review:** `docs/starbucks/history-schema-general.md`  
**This file:** design critique only — no code changes.

Priority: **P0** blocks correct graph/metrics or privacy; **P1** likely bugs or requirement gaps; **P2** clarity/completeness; **P3** polish.

---

## Executive summary

`history-schema-general.md` is strong on **source fidelity**: sectioned CSV parsing, `line_amount` ≠ order total, blank-store account activity, profile country ≠ transaction country, adjacent timestamp+store order grouping, signed `stars_delta`, and refusing invented `Z` on report timestamps. Those match the real reports.

It is **weaker as the contract for this site’s required outcomes**. The product needs a **merged, deduplicated history** that drives a **calendar visit graph**, GTA scope rules, Stars totals without double-counting API+CIR, and a durable merge with the CA API so TTL cannot erase the past. The general doc optimizes for a private multi-entity warehouse and an optional later reconciliation step; it under-specifies the **visit projection**, **API `local_date`**, **cross-source merge for metrics**, and **Stars composition** that the page actually needs.

Several passages are **truncated mid-sentence** (implementation blockers if treated as normative).

---

## P0 — Correctness / requirements blockers

### 1. “Contribution graph” is specified as a store graph, not a day grid

**Requirement** (`add-starbucks-history.md`): GitHub-style calendar — one cell per **day**, intensity by **visits/day**, year-normalized, hover date+count; count distinct orders/receipts, **not** line items; span from first USA history ~2022 through current year.

**Doc (§ Public projection and graph derivation):** defines catalog **store nodes**, order-to-store **edges**, edge weights, map markers, `to_visit`. That is the **map/visit-geography** model already largely embodied by `starbucks.json` + SVG — not the calendar heatmap.

**Gap:** no `activity.days`, `max_count_by_year`, timezone, or formula:

```text
visits_per_local_date = COUNT DISTINCT order_key
  WHERE order is a store visit (not reload)
  AND local_date = d
```

**Risk:** implementers ship only map edges and miss the required UI metric entirely, or count line rows / UTC days by accident.

**Fix:** split “geography graph” vs “activity calendar”; specify calendar derivation as a first-class projection from `order_group` (and API receipts), with explicit `local_date` rules (§ below).

---

### 2. API timezone / `local_date` left undefined (will mis-bucket days)

**Doc (§ Dates):** report times stay timezone-unknown; “If an API record contains an offset, the importer must define whether the report is based on source-local date or accounting date…”

**Reality:** CA API timestamps are UTC (`…Z`). CIR CA wall times match `America/Toronto` conversion (e.g. CIR `2026-08-22 18:00:37` ↔ API `2026-08-22T22:00:37Z`). Using UTC `date[:10]` mis-assigns ~7/156 current CA receipts across midnight.

**Site need:** one activity timezone (`America/Toronto`) for the calendar and for CIR↔API join on the same civil second.

**Risk:** wrong cell counts; failed or double visits when merging API+CIR on “date” alone.

**Fix:** normative rule, e.g.:

- CIR purchase: `local_date` = civil date of exported `YYYY-MM-DD HH:MM:SS` (as printed).
- API: `local_date` = `date(occurred_at AST America/Toronto)`.
- Cross-source order match key uses Toronto-local `HH:MM:SS` + normalized store for CA API↔CA CIR (validated ~151/156).

Leaving “importer must define” is insufficient for this repo.

---

### 3. “Merged, deduplicated history” vs “retain both, never replace”

**Requirement:** store a **merged, deduplicated** history; API refresh merges in so TTL cannot remove old data.

**Doc (§ Dedupe):** primary identity is source row / `history_id`; “If an API record and a report row appear to represent the same purchase, **retain both** … **Never silently replace** one with the other.”

Those goals can coexist **only** with an explicit second layer:

| Layer | Identity | Dedupe |
|-------|----------|--------|
| Source facts | `report_id+row` / `history_id` | Never collapse physical rows |
| **Visit projection** (metrics/graph) | stable `visit_id` / shared `order_key` after reconcile | **Must** collapse CIR order_group ↔ API receipt to one visit |

Without the projection layer, naive `COUNT DISTINCT order_key` across sources **double-counts** the ~151 overlapping CA orders (CIR group + API receipt).

**Fix:** require a `visit` / reconciliation object (or flagged merged `order_group`) used by graph, top stores, remaining, and `recent`. Keep raw lines private if desired; public metrics must not sum both sources for the same visit.

---

### 4. Stars + API double-counting not addressed

**Doc:** preserve signed CIR ledger; summarize by `point_type`; do not join rewards to purchases by date alone. Good for CIR-only.

**Missing:** this pipeline **also** ingests API `Point` rows (`60★ redeemed`, `50★ earned` reload) and Redemption `starsEarnedDisplay`.

Empirical overlap (CA window): CIR `Points` ≈ API spend-earn display; CIR `Product` daily fragments often sum toward API discrete redeem tiers; CIR `Stars for Reload` ↔ API reload Point rows. **Summing CIR rewards + API points for the same dates double-counts.**

**Doc gap:** no policy for multi-source Stars totals (window by CIR max date, prefer one source per day, or net with explicit exclusion rules).

**Requirement:** “consider Total Stars Earned/Redeemed” on the page — without a policy, the number will be wrong.

**Fix:** add a normative Stars composition section (storage can keep all rows; **published** earned/redeemed must state source windows / exclusions).

---

### 5. Privacy: report IDs and filenames as first-class public-ish identity

**Doc examples** use a report identifier and source filename, and API `history_id` as identity.

**Requirement / practice:** do not publish private profile information; raw receipts/`historyId`/`svcID` are already treated as sensitive in-repo (gitignored dumps).

Those report prefixes are **account-correlated export IDs**. Embedding them in anything that might be committed as “canonical history” or appear in debug JSON is a privacy footgun.

**Also missing from “never publish” list:** report file account codes; raw `historyId` (doc says prefer omitting opaque IDs but still keys API identity on `history_id` without mandating hash-only in committed files).

**Fix:**

- Private canonical may keep `report_id` / path.
- Committed/public projection: opaque `source: us_customer_information_report | ca_… | api_export` only; hash or omit `history_id`.
- Do not use export filename stems as stable public keys.

---

### 6. Truncated / broken normative text

Several sentences are incomplete — cannot be implemented as written:

| Location | Issue |
|----------|--------|
| § Dates (~L340–342) | “with” — sentence ends; missing what must be recorded with timezone |
| § Store resolution (~L424–430) | “may set” / “retain the resolved required” — garbled; standalone classification paragraph incomplete |

**P0 for doc quality:** repair before treating the file as the team contract.

---

## P1 — High-impact gaps and contradictions

### 7. `history_count` / USA-only stores vs requirement wording

**Requirement:** do **not** include USA-only stores in Top Starbucks, visited/total/remaining, **or history counts**, or `/to-visit/`.  
**Also:** USA **items** still count in top ordered items; GTA-named stores from USA report **do** count.

**Doc public projection** still shows a single `history_count` with no definition (all order_groups? CA-only? GTA-resolved only?).

**Risk:** counting all US Bay Area orders as “history” violates the requirement if `history_count` means visit tally for the hero stats; under-counting if it was meant to mean “ledger depth.”

**Fix:** name metrics explicitly, e.g. `visit_count_global` (graph), `visit_count_gta` (optional), `gta_standalone_visited`, and deprecate ambiguous `history_count` or define it as “active visit orders in activity span” with GTA filter called out separately.

---

### 8. Canada “all stores and items” vs unresolved `store_key`

**Requirement:** include **all** Canada report stores/items in visited/ordered sets, matching by store name.

**Doc:** order-to-store edges only when `store_key` resolved; unmatched stay for review and do not create catalog nodes.

That is correct for **map/catalog remaining**, but **top items** and **CA visit membership** must still include unresolved CA names in item tallies and unmatched lists. Ordered items from unresolved CA rows must not be dropped.

**Clarify:** resolution gates **geography widgets only**; item aggregation walks all `purchase_item` lines (US+CA+API) regardless of `store_key`.

---

### 9. Order grouping rule is good for CIR, incomplete for API merge

**Strengths (CIR):**

- Adjacent + exact same timestamp + exact same store — matches real multi-line orders (e.g. CA Bayview `2026-08-08 06:36:12` five lines including toppings).
- Do not group blank store; do not merge non-adjacent duplicates — correct.
- `line_amount_sum` ≠ verified total — correct (API total is tax-inclusive; sums differ).

**Gaps:**

- No store **normalization** before “exactly equal” (CIR `Vaughan Mills - Entry 2 Food Court` vs API `… Food C` breaks Tier-1 join if applied to cross-source keys).
- No statement that **amount must not** be part of the visit identity (header temptation; multi-item amounts differ on ~90%+ of multi-line orders).
- No CIR↔API match procedure (local second + normalized name), confidence, or which side wins for display names / totals.
- `grouping_method: adjacent_same_timestamp_and_store` assumes source order adjacency; fine for CIR newest-first dumps, irrelevant for API.

---

### 10. Lsus / Lsca left as “confirm semantics” — operationally they are non-visits

**Doc:** map Reload/Automatic Reload → `reload`; Lsus/Lsca → `loyalty_adjustment` only if confirmed, else `unknown_account_activity`.

**Observation:** both reports use blank store + these item labels; they are never store visits. Treating them as `unknown` without a hard `counts_as_visit: false` (or equivalent) risks a future classifier counting them.

**Fix:** mandatory non-visit for blank-store rows with those four labels; keep finer `activity_type` as optional taxonomy.

---

### 11. Rewards `point_type` catalog incomplete

**Doc known list:** Points, Product, Expired, Stars for Reload, Partnership Card Reload.

**Also in real files:**

| Type | Where |
|------|--------|
| `Promotion` | US + CA (often `None` date) |
| `Partnership Star Accrual` | CA (e.g. 1000) |
| `Partnership Star Bonus` | CA (e.g. 600) |

**Product interpretation** (“product redemption/spend deduction”) is incomplete: many days are **multiple Product rows that partition a reward tier** (fragments summing to −60 / −300), not one API-style redeem event. Summaries by type are fine; UX that assumes one Product row = one free drink will lie.

**`earned_on: null` / `None`:** doc shows date-only examples but does not require representing `None` dates (34 CA + 17 US reward rows). Those must not become `1970` or invented midnight; exclude from day-scoped charts or bucket as `unknown_date`.

---

### 12. Country resolution vs GTA catalog (Bayview in US report)

**Doc strength:** do not stamp `US` on Bayview because profile is SF — correct (US report lines ~351+).

**Nuance:** for **this product**, success is `in_gta_catalog` / standalone via **name match to `stores-gta.json`**, not ISO country. `transaction_country: CA` from catalog is helpful but secondary to `store_key` + `standalone` + `region`.

**Ensure:** US-report Bayview still creates a visit edge to the GTA catalog store (requirement example). Name-only path must be first-class when store number is absent (doc says this — keep it prominent in projection rules).

---

### 13. Durable API merge / TTL — under-specified

**Requirement:** API merge into durable history so expiry cannot remove old history.

**Doc invariant:** failed fetch must not replace persistent history with empty without operator decision — good.

**Missing mechanics:**

- Append-only / upsert by identity; never delete on absence from latest page set.
- Receipt fetch is incremental by `historyId` today; order_groups from API must merge into the same visit store as CIR.
- What file is the “merged history in the repository” (private canonical only vs committed sanitized ledger)? Requirement says store merged history **in the repository** — tension with “private canonical” and “don’t commit detailed purchase history.”

**Resolve explicitly:** either (a) committed scrubbed visit ledger (no PII/IDs), or (b) private-only canonical + committed aggregates only — and state which satisfies “in the repository.”

---

## P2 — Missing fields / practicality

### 14. Entity model vs implementation cost

Four entities (`report`, `purchase_line`, `order_group`, `reward_entry`) + later reconciliation is clean analytically.

For this static site, a **single visit-oriented event list** (plus optional private raw lines) is enough to ship graph + tops + map. The general model is implementable but heavy if every public rebuild joins four record types without a materialized visit view.

**Practical path:** keep general entities in private import DB/JSONL; **materialize** `visits[]` + `stars_ledger[]` for projection (aligns with `history-schema-grok.md` event list).

---

### 15. Fields the site projection needs that are absent or weak

| Need | Doc status |
|------|------------|
| `counts_as_visit` / equivalent | Implicit via kind + blank store — make explicit on `order_group` |
| `local_date` on order_group | Mentioned in dates section; not on order_group example |
| `channel` (mobile / in-store) | API has it; omitted |
| `store_number` from API | Resolution order mentions it; purchase_line example has no field for when API supplies it |
| Item display vs `raw_item_name` | Top items need stable `name_key`; API marketing names vs CIR POS abbreviations |
| `sources[]` on a merged visit | Provenance requirement; reconciliation record mentioned but not shaped |
| Activity calendar block | Missing |
| Stars earned/redeemed public fields | Summary example only; not wired to projection |
| Corrections / void | Not present (re-import mistakes, bad fuzzy match) |

---

### 16. Money as strings — good; consistency with API floats

Preferring decimal strings for `line_amount` avoids FP drift — good. API `total` is JSON number today; projection should document decimal string or scaled integer everywhere in canonical form.

---

### 17. Source order newest-first

**Doc:** reports generally newest first; presentation sort specified. Good.

**Parser note:** “adjacent” grouping works because multi-item lines share a timestamp and sit together; still define grouping as **partition by (timestamp, store)** over the purchase section, not only physical adjacency, so a future export that interleaves cannot split one order. (Equivalent if all lines of an order share an exact timestamp and no foreign row shares it — which is the observed case.)

---

### 18. Public projection example omits `activity` / `stars` / `by_region`

Example `starbucks.json`-like payload matches an older shape (`history_count`, no activity heatmap). Current import code paths already experiment with `stars` and `activity`. The contract should show the **target** public fields for the requirement, not only the pre-graph shape.

---

### 19. Promotions / coupons

CIR **Promotions** section (name, start, expiration, redemption, status) and API **Coupon** rows are out of scope in the general doc. Fine if intentional; note that birthday/mod redemptions are **not** store visits and must not enter `order_group` visit counts if ever ingested.

---

## P3 — Nits

- Line references to report files (`:30-33`, etc.) match current exports but will rot; prefer header text anchors.
- `parser_version: "1"` as string vs int — pick one.
- `resolution_confidence: 1.0` float vs decimal string inconsistency with money policy.
- `record_type` discriminators are clear; good for JSONL.
- Hybris eGift / Google Analytics / WiFi sections correctly ignored by focusing Purchase + Rewards — state “ignore other sections” explicitly.
- WiFi section header includes `CUSTOMERID` — another private field to list under never-publish.

---

## What the general doc gets right (do not regress)

1. **Section-scoped CSV parsing**; stop at next section; do not scrape whole file for 4-tuples.  
2. **`Order Total Charged` → `line_amount`**, multi-row same timestamp+store = one order-like group.  
3. **Blank store** reload/Lsus/Lsca ≠ unmatched store visit.  
4. **Profile country ≠ transaction country**; US report can contain Canadian store names.  
5. **Heuristic `order_group`** with explicit confidence; no fake Starbucks order ID.  
6. **Signed `stars_delta` + preserve `point_type`**; no date-only join to purchases as identity.  
7. **No invented `Z`** on report timestamps.  
8. **Source identity** by row number / API `history_id`; pagination offset is not identity.  
9. **Do not collapse duplicate item lines** inside an order (no qty field in CIR).  
10. **Failed fetch must not wipe history.**  
11. **Public projection ≠ raw canonical**; cookies, svcID, profile, cards excluded.  
12. **Visit weight = distinct orders**, not line count — correct intent for map/top stores (extend same rule to calendar).

---

## Requirement coverage matrix

| Requirement | Covered by general doc? |
|-------------|-------------------------|
| Durable history beyond API TTL | Partial (invariant only) |
| Provenance US / CA / API | Partial (`customer_information_report` + API; weak US vs CA enum) |
| USA items in top items | Yes if all purchase_lines feed items |
| USA-only stores excluded from GTA tops/remaining/to-visit | Partial (resolved edges only; history_count undefined) |
| GTA visits from either report by name | Yes in spirit (name resolution) |
| All CA stores/items | Partial (items yes if lines kept; unresolved stores) |
| Stars earned/redeemed on page | Weak (CIR summary only; no API merge policy) |
| Calendar contribution graph | **No** (store graph instead) |
| Count orders not lines | Yes for edges; not specified for calendar |
| No private profile published | Mostly; report_id/filename/`history_id` soft |

---

## Recommended doc revisions (priority order)

1. **P0:** Define **activity calendar** derivation (`local_date`, DISTINCT orders, year max, timezone `America/Toronto`).  
2. **P0:** Define **visit projection / reconciliation** so CIR+API overlapping orders count once in all visit metrics.  
3. **P0:** Define **Stars multi-source totals** (anti-double-count).  
4. **P0:** Repair truncated sentences; tighten privacy (report export IDs, historyId hashing).  
5. **P1:** Explicit metric dictionary (`history_count` → precise names); GTA vs global scope.  
6. **P1:** Cross-source match key (local second + store_norm); amount excluded; Food Court normalization.  
7. **P1:** Complete `point_type` enum; `None` reward dates; Product fragmentation note.  
8. **P2:** Materialized visit view for site practicality; corrections; channel/store_number/items display names.  
9. **P2:** State committed vs private artifacts relative to “history in the repository.”

---

## Bottom line

Treat `history-schema-general.md` as a **solid private/source-canonical design** for CIR fidelity and careful semantics. Do **not** treat it alone as sufficient for shipping `add-starbucks-history.md`: it conflates map geography with the required **day-visit graph**, leaves **API local dates** and **CIR↔API visit dedupe** underspecified, and omits a **Stars double-count** policy. Fix those P0 items (and the truncated prose) before implementation freezes on this document.
