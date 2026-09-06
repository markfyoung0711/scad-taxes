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

## Warehouse

- `mart.dim_parcel` — one row per account
- `mart.fact_parcel_year` — account × year: building, land, appraised, assessed, cap loss, total tax
- `mart.fact_parcel_jurisdiction_year` — account × year × jurisdiction: taxable value, rate, tax
- `mart.v_parcel_value_change` — YoY and since-baseline change, value and tax
- `mart.v_parcel_trend` — one row per account: total change and CAGR
- `mart.v_jurisdiction_change` — which jurisdiction drove a year's change

## Usage

```bash
uv venv && uv pip install -e .

scad search --owner "young mark francis"      # roster only
scad fetch  --owner "young mark francis"      # + per-parcel history, staged
scad fetch  --city LINDALE                    # whole town (owner is optional)
scad build
scad report --account R107193
```

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
