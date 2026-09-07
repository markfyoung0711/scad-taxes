"""Command line entry point: acquire -> stage -> build -> report."""
from __future__ import annotations

import argparse
import random
import sys

from . import acquire, crawl, export, geocode, parse, stage, warehouse
from .http import Client


def _criteria(args) -> dict:
    out = {}
    if args.owner:
        out["owner_name"] = args.owner
    if args.city:
        out["city"] = args.city
    if args.street_name:
        out["street_name"] = args.street_name
    if args.subdivision:
        out["subdivision"] = args.subdivision
    if args.property_use:
        out["property_use"] = args.property_use
    return out


def cmd_search(args) -> int:
    rows = acquire.search_parcels(Client(), label=args.label, **_criteria(args))
    print(f"{len(rows)} parcels", file=sys.stderr)
    for row in rows:
        print(f"{row['Ext ID']}\t{row['gis_parcel_id']}\t{row['Owner Name']}\t{row['Site Address'].strip()}")
    return 0


def _narrow(rows: list[dict], args) -> list[dict]:
    """A city-wide search returns thousands of parcels; one page per parcel at
    the polite delay makes fetching all of them a multi-hour job. --sample and
    --limit make a slice of that explicit rather than accidental."""
    if args.sample:
        rng = random.Random(args.seed)
        return rng.sample(rows, min(args.sample, len(rows)))
    if args.limit:
        return rows[:args.limit]
    return rows


def cmd_fetch(args) -> int:
    client = Client()
    if args.parcel_id:
        # The detail page is addressed by the undotted form of the Property ID
        # shown in search results (1.00000.0053.00.002000 -> 100000005300002000).
        rows = [{"gis_parcel_id": pid.replace(".", "")} for pid in args.parcel_id]
        print(f"{len(rows)} parcels named", file=sys.stderr)
    else:
        rows = acquire.search_parcels(client, label=args.label, **_criteria(args))
        print(f"{len(rows)} parcels matched", file=sys.stderr)
        rows = _narrow(rows, args)
    if len(rows) > 50 and not (args.sample or args.limit):
        print(f"refusing to fetch {len(rows)} parcel pages without --limit or "
              f"--sample; that is {len(rows)} requests", file=sys.stderr)
        return 1
    for row in rows:
        gis_id = row["gis_parcel_id"]
        record = parse.parse_parcel(acquire.fetch_parcel(client, gis_id), gis_parcel_id=gis_id)
        path = stage.stage_parcel(record)
        years = [v["tax_year"] for v in record["values"]]
        print(f"{record['parcel']['account']}  {min(years)}-{max(years)}  -> {path.name}", file=sys.stderr)
    return 0


def cmd_crawl(args) -> int:
    """Fetch every parcel matching the criteria, resumably."""
    from pathlib import Path

    log = Path(args.log) if args.log else None
    result = crawl.crawl(_criteria(args), workers=args.workers, rate=args.rate,
                         limit=args.limit, label=args.label, log=log)
    print(f"staged {result.done} of {result.total} "
          f"({result.skipped} already held, {len(result.failed)} failed)",
          file=sys.stderr)
    if result.failed:
        print("failed: " + ", ".join(result.failed[:20]), file=sys.stderr)
    return 0


def cmd_geocode(args) -> int:
    """Locate every warehoused parcel against the county's GIS."""
    import json

    from .config import STAGED
    from .stage import utcnow

    con = warehouse.connect(read_only=True)
    parcels = [{"account": a, "gis_parcel_id": g, "situs_address": s}
               for a, g, s in con.execute(
                   "SELECT account, gis_parcel_id, situs_address FROM mart.dim_parcel"
               ).fetchall()]
    con.close()

    client = Client()
    rows = geocode.assign_districts(client, geocode.locate(client, parcels))
    path = STAGED / "geocode" / "locations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"_staged_at": utcnow(), "locations": rows}))

    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    print(f"located {len(rows)} of {len(parcels)} parcels "
          f"({', '.join(f'{k}: {v}' for k, v in sorted(by_source.items()))})",
          file=sys.stderr)
    print(f"-> {path}", file=sys.stderr)
    return 0


def cmd_build(args) -> int:
    path = warehouse.build()
    for table, n in warehouse.counts(path).items():
        print(f"{table}: {n} rows", file=sys.stderr)
    return 0


def cmd_export(args) -> int:
    from pathlib import Path

    path = Path(args.out)
    n = export.write(path, args.limit, town=args.town)
    print(f"wrote {n} homeowners -> {path}", file=sys.stderr)
    return 0


def cmd_report(args) -> int:
    con = warehouse.connect(read_only=True)
    where = "WHERE account = ?" if args.account else ""
    params = [args.account] if args.account else []

    def show(title: str, sql: str, sql_params: list) -> None:
        print(f"\n== {title} ==")
        con.sql(sql, params=sql_params).show(max_rows=200)

    show("Value & tax by year",
         "SELECT account, tax_year, appraised_value, assessed_value, total_tax,"
         " appraised_pct_yoy, tax_pct_yoy, appraised_pct_since_base, tax_pct_since_base"
         f" FROM mart.v_parcel_value_change {where} ORDER BY account, tax_year", params)

    show("Trend", f"SELECT * FROM mart.v_parcel_trend {where} ORDER BY account", params)

    if args.account:
        show("By jurisdiction",
             "SELECT tax_year, jurisdiction, taxable_value, tax_rate, tax_amount, tax_change_yoy"
             " FROM mart.v_jurisdiction_change WHERE account = ?"
             " ORDER BY tax_year DESC, jurisdiction", [args.account])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scad", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_search_args(p):
        p.add_argument("--owner", help="owner name prefix, district 'LAST FIRST' order")
        p.add_argument("--city", action="append", help="location city (repeatable)")
        p.add_argument("--street-name", help="location street name, starts-with")
        p.add_argument("--subdivision", action="append", help="subdivision code (repeatable)")
        p.add_argument("--property-use", action="append",
                       help="property use code, e.g. A00 for single family (repeatable)")
        p.add_argument("--label", help="name for the landed export file")

    p = sub.add_parser("search", help="search parcels and print the roster")
    add_search_args(p)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("fetch", help="search, then fetch and stage each parcel's history")
    add_search_args(p)
    p.add_argument("--limit", type=int, help="fetch only the first N matches")
    p.add_argument("--sample", type=int, help="fetch a random N of the matches")
    p.add_argument("--seed", type=int, default=None, help="seed for --sample")
    p.add_argument("--parcel-id", action="append",
                   help="fetch these Property IDs directly, skipping the search "
                        "(dotted or undotted; repeatable)")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("crawl", help="fetch every matching parcel, resumably")
    add_search_args(p)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--rate", type=float, default=3.0,
                   help="requests per second across all workers")
    p.add_argument("--limit", type=int, help="stop after N new parcels")
    p.add_argument("--log", help="file to write progress into")
    p.set_defaults(func=cmd_crawl)

    p = sub.add_parser("geocode", help="locate warehoused parcels against county GIS")
    p.set_defaults(func=cmd_geocode)

    p = sub.add_parser("build", help="rebuild the DuckDB warehouse from staged JSON")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("export", help="write the homeowner JSON extract")
    p.add_argument("--out", default="data/export/homeowners.json")
    p.add_argument("--limit", type=int, help="cap the number of records")
    p.add_argument("--town", help="only this town")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("report", help="print value and tax trends")
    p.add_argument("--account", help="limit to one account, e.g. R107193")
    p.set_defaults(func=cmd_report)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
