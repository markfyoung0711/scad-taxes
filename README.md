# Smith County (TX) property tax history warehouse

Ingests public Smith County Appraisal District records and measures how
appraised value and taxes have moved, per account, over every year the
district publishes.

## Data sources

| Source | What it gives | Years |
|---|---|---|
| Advanced search + JSON export (`smithcad-search.gsacorp.io/export/adv/r?format=json`) | Parcel roster: account, GIS parcel id, owner, situs, use code, tax district | current |
| Parcel detail page (`/parcel/<gis_parcel_id>`) | Building/land/appraised/assessed value **and** taxable value, rate and tax per jurisdiction, per year | 2020–2026 |
| Certified appraisal roll ZIP (`smithcad.org/data/<year>/`) | Full-county bulk CSV — 144k real property accounts, 9.8k BPP, 41k mineral | current only |
| County GIS (`Parcels` / `Address_Points` FeatureServers) | Parcel polygons and address points, keyed by the same account numbers | current |

The parcel page is the only public source carrying multiple years, so it is
what the trend rests on. The bulk roll is the current-year cross-check and the
route to county-wide coverage.

**Years before the 7 on the parcel page require an open-records request** to
the district — smithcad.org publishes only the current roll.

## Pipeline

```
acquire  -> data/raw/          verbatim bytes + data/raw/_manifest.jsonl (url, sha256, fetched_at)
parse    -> data/staged/parcel/<account>.json
warehouse-> data/warehouse/scad.duckdb    raw -> stg -> mart
```

The build is idempotent and replayed from staged files; nothing is mutated in
place, and every warehouse row traces back through the manifest to the bytes
it came from.

## Exemptions

The parcel page lists exemptions as `HS: Homestead (11.13(b))  (100%)`, which
staging splits into `exemption_codes` and a `homestead_shown` flag. The
district withholds some exemptions online — "For privacy reasons not all
exemptions are shown" — so a false flag means *not shown*, not *none held*.
The certified roll's exemption file is authoritative, for the current year.

## Geocoding

Locations come from Smith County's own GIS, joined on the account number
rather than matched on address text: the `Parcels` layer's `ACCOUNT` is the
same identifier as the roll's, and `PIN` is the R-number. Parcels with no
polygon of their own — improvement-only accounts and recent splits — fall back
to the county address-point layer.

Geocoding also stamps each parcel with the districts its centroid falls
inside — voting precinct and commissioner precinct — resolved by
point-in-polygon, since those layers carry no account key.

```bash
scad geocode && scad build
```

## Warehouse

- `mart.dim_parcel` — one row per account, with `sector` derived from the
  leading letter of the use code (the Texas state property category)
- `mart.fact_parcel_year` — account × year: building, land, appraised, assessed, cap loss, total tax
- `mart.fact_parcel_jurisdiction_year` — account × year × jurisdiction: taxable value, rate, tax
- `mart.v_parcel_value_change` — YoY and since-baseline change, value and tax
- `mart.v_parcel_trend` — one row per account: total change and CAGR
- `mart.v_jurisdiction_change` — which jurisdiction drove a year's change
- `mart.dim_parcel_location` — latitude/longitude per parcel, with the source
  (`parcel_centroid` or `address_point`)
- `mart.v_parcel_map` — account × year with a location on it: the map grain
- `mart.v_homeowner` — one row per parcel, flattened for the export

## Usage

```bash
uv venv && uv pip install -e .

scad search --owner "young mark francis"      # roster only
scad fetch  --owner "young mark francis"      # + per-parcel history, staged
scad fetch  --city LINDALE --property-use A00 --sample 25   # a slice of a town
scad fetch  --parcel-id 1.00000.0053.00.002000              # named parcels
scad geocode                                  # locate them against county GIS
scad build
scad report --account R107193
scad export --out data/export/homeowners.json   # JSON extract
```

### Homeowner extract

`scad export` writes one record per parcel with its whole year-by-year
history:

```json
{
  "homeowners": [
    {
      "id": "R107193",
      "name": "YOUNG MARK FRANCIS & ELIZABETH G",
      "address": "4320 C R 325",
      "town": "Lindale",
      "precinct": "3021",
      "property_type": "house",
      "homestead_exemption": true,
      "tax_history": [
        {"year": 2020, "appraised_value": 310876, "tax_amount": 2886.89}
      ]
    }
  ]
}
```

`property_type` follows the district's own use class: A/B/M are dwellings
(`house`), D and E are land (`acreage`), anything else says `other` rather
than guessing.

A city search returns thousands of parcels and each one is a separate page
fetch, so `fetch` refuses more than 50 without `--limit` or `--sample`.

Owner name is matched as a prefix on the district's `LAST FIRST` form, so
`young mark` matches and `mark young` does not.

Requests are serialised with a 1s delay (`SCAD_DELAY`) and a contact
User-Agent (`SCAD_USER_AGENT`).

## Reading the numbers

Appraised value and assessed value diverge when a homestead cap is in force —
account R107193 was appraised at $310,876 in 2020 but assessed at $174,727,
so tax growth off that baseline reflects the cap unwinding as well as
market movement. Taxable value also differs per jurisdiction, since exemptions
apply differently to the county, ISD, college and ESD.

Rates are published per $100 of value.

## Dashboard

```bash
uv run streamlit run app/streamlit_app.py
```

Value and tax are different units, so both are rebased to 100 in each account's
own first published year — one honest axis, where the gap between a dashed line
and its solid partner is how far the tax bill diverged from the appraisal.
(A dual-axis chart would answer the same question by putting two y-scales on
one plot, which makes the crossing point an artefact of the scaling.)

Filters cascade: sector → use code → account. **Solid is always appraised
value, dashed is always tax paid**; color carries identity:

- **One parcel** — no identity to encode, so color takes the measure instead:
  blue is appraised value, orange is tax paid.
- **Account** — each parcel gets its own hue. Offered up to eight parcels; a
  categorical palette holds eight and they are never cycled.
- **Sector** — beyond eight, identity moves up to the sector.

Account numbers at the right edge link to the district's own parcel page, with
the owner beside them.

Each measure is indexed to 100 at the first year *it* has a figure, not the
parcel's first year — a new build or a split lands on the roll with an
appraisal before any levy is calculated, and indexing off the parcel's base
year would divide by a missing number and drop the whole series.

A split or a new build can index into the hundreds while everything else sits
near 100, so the y axis switches to log once the spread passes 5×; the sidebar
overrides it either way.

The map below plots the same selection, colored by sector or by tax change
since the baseline year, and needs `scad geocode && scad build` first.

Colors come from a validated categorical palette (adjacent-pair CVD ΔE ≥ 8 in
both light and dark). Aqua and yellow sit below 3:1 on the light surface, so
every view also offers the table.
