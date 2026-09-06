"""DuckDB warehouse build: raw -> stg -> mart, replayed from staged JSON.

The build is idempotent. Staged files are the input, so a rebuild after a new
fetch simply picks up the new files; nothing is mutated in place.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from .config import SQL, STAGED, WAREHOUSE

LAYERS = ["01_raw.sql", "02_stg.sql", "03_mart.sql"]


def connect(path: Path = WAREHOUSE) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def build(con: duckdb.DuckDBPyConnection | None = None) -> duckdb.DuckDBPyConnection:
    con = con or connect()
    glob = str(STAGED / "parcel" / "*.json")
    if not list((STAGED / "parcel").glob("*.json")):
        raise FileNotFoundError(f"no staged parcel documents at {glob}; run `scad fetch` first")

    for name in LAYERS:
        sql = (SQL / name).read_text()
        # DuckDB named parameters are not allowed in a CREATE ... AS read_json
        # path position, so the glob is substituted before execution.
        con.execute(sql.replace("$staged_glob", f"'{glob}'"))
    return con
