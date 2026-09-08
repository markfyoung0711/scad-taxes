"""Read-only HTTP API over the warehouse.

The dashboard used to open the DuckDB file itself, which meant refreshing the
data required rebuilding the container. Here the database is a served
resource: the pipeline publishes a file, the API loads it, and any client --
Streamlit, a browser, another service -- asks over HTTP.

DuckDB stays the engine because the workload is analytical and the data is
small: a county-wide median over 144k rows runs in ~17ms, which no round trip
to a hosted database would match.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Query

from .config import WAREHOUSE

# Set to gs://bucket/object to pull the warehouse at startup instead of
# reading a local file.
WAREHOUSE_URI = os.environ.get("SCAD_WAREHOUSE_URI", "")
LOCAL_COPY = Path(os.environ.get("SCAD_WAREHOUSE_LOCAL", "/tmp/scad.duckdb"))

_con: duckdb.DuckDBPyConnection | None = None


def _download(uri: str, dest: Path) -> Path:
    """Fetch the published warehouse from Cloud Storage."""
    from google.cloud import storage

    bucket_name, _, blob_name = uri.removeprefix("gs://").partition("/")
    dest.parent.mkdir(parents=True, exist_ok=True)
    storage.Client().bucket(bucket_name).blob(blob_name).download_to_filename(dest)
    return dest


def connect() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        path = _download(WAREHOUSE_URI, LOCAL_COPY) if WAREHOUSE_URI else WAREHOUSE
        _con = duckdb.connect(str(path), read_only=True)
        _con.execute("INSTALL spatial; LOAD spatial;")
    return _con


@asynccontextmanager
async def lifespan(app: FastAPI):
    connect()          # fail loudly at boot rather than on the first request
    yield


app = FastAPI(title="Smith CAD appraisal & tax API", version="0.1.0",
              lifespan=lifespan)


def rows(sql: str, params: list | None = None) -> list[dict[str, Any]]:
    cur = connect().execute(sql, params or [])
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def one(sql: str, params: list | None = None) -> dict[str, Any]:
    found = rows(sql, params)
    if not found:
        raise HTTPException(status_code=404, detail="not found")
    return found[0]


@app.get("/health")
def health() -> dict:
    n = connect().execute("SELECT COUNT(*) FROM mart.fact_county_parcel_year").fetchone()[0]
    return {"status": "ok", "county_parcels": n}


@app.get("/towns")
def towns() -> list[dict]:
    return rows("""SELECT gis_city AS town, COUNT(*) AS parcels
                   FROM mart.dim_parcel_location WHERE gis_city IS NOT NULL
                   GROUP BY 1 ORDER BY 2 DESC""")


@app.get("/use-codes")
def use_codes() -> list[dict]:
    return rows("""SELECT use_code, use_class, COUNT(*) AS parcels
                   FROM mart.fact_county_parcel_year
                   WHERE tax_year = (SELECT MAX(tax_year) FROM mart.fact_county_parcel_year)
                   GROUP BY 1, 2 ORDER BY 3 DESC""")


@app.get("/parcels")
def parcels(town: str | None = None, use_class: str | None = None,
            owner: str | None = None, limit: int = Query(100, le=1000),
            offset: int = 0) -> list[dict]:
    where, params = ["1=1"], []
    if town:
        where.append("UPPER(l.gis_city) = UPPER(?)")
        params.append(town)
    if use_class:
        where.append("c.use_class = ?")
        params.append(use_class.upper())
    if owner:
        where.append("c.owner_name ILIKE ?")
        params.append(f"%{owner}%")
    return rows(f"""
        SELECT c.account, c.owner_name, c.situs_address, c.use_code,
               c.market_value, c.assessed_value, c.total_tax, c.effective_rate,
               l.gis_city AS town, l.latitude, l.longitude
        FROM mart.fact_county_parcel_year c
        LEFT JOIN mart.dim_parcel_location l USING (gis_parcel_id)
        WHERE {' AND '.join(where)}
        ORDER BY c.account LIMIT {int(limit)} OFFSET {int(offset)}""", params)


@app.get("/parcels/{account}")
def parcel(account: str) -> dict:
    return one("""SELECT c.*, l.gis_city AS town, l.latitude, l.longitude,
                         l.voting_precinct, l.commissioner_precinct
                  FROM mart.fact_county_parcel_year c
                  LEFT JOIN mart.dim_parcel_location l USING (gis_parcel_id)
                  WHERE c.account = ?""", [account])


@app.get("/parcels/{account}/history")
def history(account: str) -> list[dict]:
    """Year-by-year movement, from the parcel-page crawl."""
    return rows("""SELECT tax_year, market_value, assessed_value, total_tax,
                          market_pct_yoy, tax_pct_yoy, market_base_year, tax_base_year
                   FROM mart.v_parcel_value_change WHERE account = ?
                   ORDER BY tax_year""", [account])


@app.get("/parcels/{account}/jurisdictions")
def jurisdictions(account: str) -> list[dict]:
    return rows("""SELECT tax_year, jurisdiction, taxable_value, tax_rate, tax_amount
                   FROM mart.fact_county_jurisdiction_year WHERE account = ?
                   ORDER BY tax_year DESC, jurisdiction""", [account])
