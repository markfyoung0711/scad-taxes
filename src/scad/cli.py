"""Command line entry point: acquire -> stage -> build -> report."""
from __future__ import annotations

import argparse
import json
import sys

from . import acquire, parse, stage, warehouse
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
    return out


def cmd_search(args) -> int:
    rows = acquire.search_parcels(Client(), label=args.label, **_criteria(args))
    print(f"{len(rows)} parcels", file=sys.stderr)
    for row in rows:
        print(f"{row['Ext ID']}\t{row['gis_parcel_id']}\t{row['Owner Name']}\t{row['Site Address'].strip()}")
    return 0


def cmd_fetch(args) -> int:
    client = Client()
    rows = acquire.search_parcels(client, label=args.label, **_criteria(args))
    print(f"{len(rows)} parcels matched", file=sys.stderr)
    for row in rows:
        gis_id = row["gis_parcel_id"]
        record = parse.parse_parcel(acquire.fetch_parcel(client, gis_id), gis_parcel_id=gis_id)
        path = stage.stage_parcel(record)
        years = [v["tax_year"] for v in record["values"]]
        print(f"{record['parcel']['account']}  {min(years)}-{max(years)}  -> {path.name}", file=sys.stderr)
    return 0


def cmd_build(args) -> int:
    con = warehouse.build()
    for table in ("mart.dim_parcel", "mart.fact_parcel_year", "mart.fact_parcel_jurisdiction_year"):
        (n,) = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        print(f"{table}: {n} rows", file=sys.stderr)
    return 0


def cmd_report(args) -> int:
    con = warehouse.connect()
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
        p.add_argument("--label", help="name for the landed export file")

    p = sub.add_parser("search", help="search parcels and print the roster")
    add_search_args(p)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("fetch", help="search, then fetch and stage each parcel's history")
    add_search_args(p)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("build", help="rebuild the DuckDB warehouse from staged JSON")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("report", help="print value and tax trends")
    p.add_argument("--account", help="limit to one account, e.g. R107193")
    p.set_defaults(func=cmd_report)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
