# Starbucks GTA store enumeration

## (a) Locator endpoint

**Primary (working):**

```
GET https://www.starbucks.ca/apiproxy/v1/locations?lat={lat}&lng={lng}
GET https://www.starbucks.ca/apiproxy/v1/locations?place={place}
GET https://www.starbucks.ca/apiproxy/v1/locations?lat={lat}&lng={lng}&features={csv}
```

Same path works on `www.starbucks.com`. Discovered from the store-locator SPA chunk
`/app-assets/store-locator-page.*.chunk.js` and `coreApp.*.js`, which build:

`locationQueryUrl = /apiproxy/v1/locations?${qs}` with keys `lat`, `lng`, `place`, `features`.

**Related:**

| Method | URL | Body / notes |
|--------|-----|----------------|
| POST | `/apiproxy/v1/locations/nearest-location` | `{"lat","lng","features?"}` → nearest coords only |
| GET | `/apiproxy/v1/locations/static-map?...` | map image, not a store list |

**Headers used:** `User-Agent: Mozilla/5.0 … Chrome/131`, `Accept: application/json`,
`x-requested-with: XMLHttpRequest`, `Referer: https://www.starbucks.ca/store-locator`.

**Dead candidates tried:** `/bff/locations` (404), `/apiproxy/v1/orchestra/locations` (404/`{}`),
`/store-locator/api/stores` (HTML SPA), `/api/locations.json` (404).

### Response shape

Top-level: **JSON array** (max **50** items per request). Each element:

| Field | Type | Meaning |
|-------|------|---------|
| `distance` | number | miles from query point |
| `isFavorite` / `isNearby` / `isPrevious` | bool | UI flags |
| `recommendationReason` | string | e.g. `"NEARBY"` |
| `store` | object | store payload |

`store` fields used:

| Field | Notes |
|-------|--------|
| `id` | locator location ID (string numeric) |
| `storeNumber` | e.g. `"4455-310581"` |
| `name` | display name |
| `ownershipTypeCode` | `"CO"` company-operated, `"LS"` licensed |
| `address.singleLine`, `.streetAddressLine1`, `.city`, `.countrySubdivisionCode`, `.postalCode`, `.countryCode` | address |
| `coordinates.latitude`, `coordinates.longitude` | WGS84 |
| `amenities[]` | `{code,name}` (Wi‑Fi, MOP, etc.) — **not** grocery vs standalone |
| `phoneNumber`, `schedule`, `open`, … | extras |

Grocery vs standalone is **not** a first-class API flag. Classification uses
`ownershipTypeCode` + name keywords (Loblaws, Metro, Longos, …).

### Enumeration method

API hard-caps at 50 nearest stores. Swept a lat/lng grid over the GTA bbox
(~43.40–44.10 N, 80.00–78.70 W) with denser spacing downtown, merged unique
`store.id` values. Spot-checked with `?place=City, ON` queries; only miss was a
typo city (`Etiboicoke` → Humber College), now included.

## (b) Counts (GTA / official regional municipalities)

**GTA definition used:** City of Toronto + Peel + York Region + Durham + Halton  
(excludes Hamilton, Bradford, Barrie, Port Hope, etc.)

| Metric | Count |
|--------|------:|
| **All Starbucks in GTA (locator)** | **312** |
| **Standalone** (`ownershipTypeCode=CO`, not inside grocery/retailer/campus/hotel/airport by name) | **195** |
| Within grocery (Loblaws/Metro/Longos/Walmart/…) | 68 |
| Embedded other (college/hotel/airport/ONroute/…) | 23 |
| Licensed other (LS, not grocery-named) | 22 |
| Within non-grocery retailer (e.g. Indigo) | 4 |
| Company-owned (CO) total | 206 |
| Licensed (LS) total | 106 |

By region (all / standalone):

| Region | All | Standalone |
|--------|----:|-----------:|
| Toronto | 141 | 92 |
| Peel | 58 | 31 |
| York Region | 53 | 31 |
| Halton | 35 | 23 |
| Durham | 25 | 18 |

### Secondary source: starbuckseverywhere.net

- `StoreOpeningDates.htm` — large HTML table (`Opened`, `Name`, `City`, `Market`), ~8758 rows.
- `StoreList` — **404**.
- Ontario markets include `Ontario\Toronto` (73), `Ontario\PeelRegion` (26),
  `Ontario\GreaterTorontoArea` (103) ≈ **206** GTA-tagged opening-date rows (historical /
  incomplete vs live locator; no coordinates). Prefer locator `id` + coords when sources disagree.

## (c) Output files

| Path | Role |
|------|------|
| `data/starbucks/stores-gta.json` | **Primary denominator list** |
| `data/starbucks/stores-gta-standalone.json` | Filter `standalone=true` only |
| `data/starbucks/locator-merged-unique.json` | Deduped raw locator payloads |
| `data/starbucks/locator-sample-*.json` | Sample raw API pages |
| `data/starbucks/SUMMARY.json` | Machine-readable counts |
| `data/starbucks/starbuckseverywhere-*.html/json` | Secondary source extract |

**`stores-gta.json`:** written, ~145 KB, 312 objects.

Record schema:

```json
{
  "name": "Rossland and Harwood Avenue",
  "address": "5 Rossland Road East, Ajax",
  "street": "5 Rossland Road East",
  "city": "Ajax",
  "province": "ON",
  "postalCode": "L1T 4V2",
  "country": "CA",
  "lat": 43.88002,
  "lng": -79.02498,
  "locationId": "1019200",
  "storeNumber": "50472-265924",
  "ownershipTypeCode": "CO",
  "banner": "standalone",
  "standalone": true,
  "region": "Durham",
  "phoneNumber": "+1 289-404-3931"
}
```

For a “visited vs all **standalone**” map, filter `standalone === true` (195 stores)
or use `stores-gta-standalone.json`.
