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

from .config import SQL, STAGED, WAREHOUSE

LAYERS = ["01_raw.sql", "02_stg.sql", "03_mart.sql"]
GEO_LAYER = "04_geo.sql"


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

    glob = str(staged / "*.json")
    geo_glob = str(STAGED / "geocode" / "*.json")
    layers = list(LAYERS)
    if list((STAGED / "geocode").glob("*.json")):
        layers.append(GEO_LAYER)

    con = duckdb.connect(str(tmp))
    try:
        for name in layers:
            sql = (SQL / name).read_text()
            # DuckDB named parameters are not allowed in the read_json path
            # position, so the globs are substituted before execution.
            con.execute(sql.replace("$staged_glob", f"'{glob}'")
                           .replace("$geocode_glob", f"'{geo_glob}'"))
    finally:
        con.close()

    os.replace(tmp, path)
    return path


def counts(path: Path = WAREHOUSE) -> dict[str, int]:
    con = connect(path, read_only=True)
    try:
        tables = ["mart.dim_parcel", "mart.fact_parcel_year",
                  "mart.fact_parcel_jurisdiction_year"]
        if con.execute("SELECT COUNT(*) FROM duckdb_tables() WHERE schema_name = 'mart' "
                       "AND table_name = 'dim_parcel_location'").fetchone()[0]:
            tables.append("mart.dim_parcel_location")
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        con.close()
