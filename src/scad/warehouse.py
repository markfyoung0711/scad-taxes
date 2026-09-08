"""DuckDB warehouse build: raw -> stg -> mart, replayed from staged JSON.

The build is idempotent. Staged files are the input, so a rebuild after a new
fetch simply picks up the new files; nothing is mutated in place.

DuckDB allows a single writer, and a running dashboard holds the database
open -- so the build writes a fresh file beside the live one and swaps it in
atomically. A reader that already has the old file open keeps serving from it
until it reconnects; nothing half-built is ever visible.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

from . import bulk
from .config import SQL, STAGED, WAREHOUSE

LAYERS = ["01_raw.sql", "02_stg.sql", "03_mart.sql"]
# Files per read_json call. Large enough that the per-call overhead is
# irrelevant, small enough that the inferred schemas fit in memory.
DOCUMENT_BATCH = 2000
BULK_LAYER = "06_bulk.sql"
GEO_LAYER = "04_geo.sql"
EXPORT_LAYER = "05_export.sql"


def connect(path: Path = WAREHOUSE, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def build(path: Path = WAREHOUSE) -> Path:
    """Rebuild the warehouse from staged JSON and swap it into place."""
    staged = STAGED / "parcel"
    if not list(staged.glob("*.json")):
        raise FileNotFoundError(f"no staged parcel documents in {staged}; run `scad fetch` first")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".duckdb.building")
    for leftover in (tmp, tmp.with_name(tmp.name + ".wal")):
        leftover.unlink(missing_ok=True)

    documents = sorted(staged.glob("*.json"))
    geo_glob = str(STAGED / "geocode" / "*.ndjson")
    layers = list(LAYERS)
    if list((STAGED / "geocode").glob("*.ndjson")):
        layers.append(GEO_LAYER)
        layers.append(EXPORT_LAYER)

    bulk_years = sorted(int(d.name) for d in (STAGED / "bulk").glob("*")
                        if d.is_dir() and d.name.isdigit())

    con = duckdb.connect(str(tmp))
    try:
        # Insertion order carries no meaning here and preserving it costs
        # memory proportional to the whole build.
        con.execute("SET preserve_insertion_order = false")

        for name in layers:
            if name == "01_raw.sql":
                con.execute((SQL / name).read_text())
                load_documents(con, documents)
                continue
            sql = (SQL / name).read_text()
            # DuckDB named parameters are not allowed in the read_json path
            # position, so the glob is substituted before execution.
            con.execute(sql.replace("$geocode_glob", f"'{geo_glob}'"))

        # The certified roll is the whole county for one year; the parcel-page
        # crawl is a handful of parcels across many. They stay separate tables
        # and are compared, not merged.
        for year in bulk_years:
            bulk.load(con, year)
        if bulk_years:
            con.execute((SQL / BULK_LAYER).read_text())
    finally:
        con.close()

    os.replace(tmp, path)
    return path


def load_documents(con: duckdb.DuckDBPyConnection, files: list[Path]) -> int:
    """Read staged parcel documents into raw.parcel_document, in batches."""
    for start in range(0, len(files), DOCUMENT_BATCH):
        listed = ", ".join(f"'{f}'" for f in files[start:start + DOCUMENT_BATCH])
        select = f"SELECT * FROM read_json([{listed}], union_by_name := true)"
        if start == 0:
            con.execute(f"CREATE OR REPLACE TABLE raw.parcel_document AS {select}")
        else:
            con.execute(f"INSERT INTO raw.parcel_document BY NAME {select}")
    return len(files)


def counts(path: Path = WAREHOUSE) -> dict[str, int]:
    con = connect(path, read_only=True)
    try:
        tables = ["mart.dim_parcel", "mart.fact_parcel_year",
                  "mart.fact_parcel_jurisdiction_year"]
        for optional in ("dim_parcel_location", "fact_county_parcel_year"):
            if con.execute("SELECT COUNT(*) FROM duckdb_tables() WHERE "
                           "schema_name = 'mart' AND table_name = ?",
                           [optional]).fetchone()[0]:
                tables.append(f"mart.{optional}")
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        con.close()
