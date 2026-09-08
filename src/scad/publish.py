"""Publish the DuckDB marts to BigQuery.

DuckDB stays the build engine -- it is where the pipeline assembles and
validates the marts. BigQuery is the serving copy the API reads, so the two
have different jobs and the handoff is one direction only: build locally,
publish upward, never edit in place.

Tables go via Parquet rather than row inserts. DuckDB writes it natively,
BigQuery loads it natively, and the types survive the trip -- DECIMAL stays
DECIMAL instead of arriving as a float.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
from google.cloud import bigquery

from .config import WAREHOUSE

PROJECT = "butterfly-buckstoplabs"
DATASET = "scad"
LOCATION = "US"

# The marts worth serving. Views are materialised on the way out, so the API
# never pays to recompute a window function.
TABLES = [
    "dim_parcel",
    "dim_parcel_location",
    "fact_parcel_year",
    "fact_parcel_jurisdiction_year",
    "fact_county_parcel_year",
    "fact_county_jurisdiction_year",
    "fact_county_exemption",
    "v_parcel_value_change",
    "v_parcel_trend",
    "v_jurisdiction_change",
    "v_parcel_map",
    "v_homeowner",
]


def ensure_dataset(client: bigquery.Client) -> None:
    dataset = bigquery.Dataset(f"{PROJECT}.{DATASET}")
    dataset.location = LOCATION
    dataset.description = "Smith County appraisal and tax history, built by the scad pipeline"
    client.create_dataset(dataset, exists_ok=True)


def publish(only: list[str] | None = None, *, warehouse: Path = WAREHOUSE) -> dict[str, int]:
    client = bigquery.Client(project=PROJECT)
    ensure_dataset(client)

    con = duckdb.connect(str(warehouse), read_only=True)
    present = {r[0] for r in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'mart' "
        "UNION SELECT view_name FROM duckdb_views() WHERE schema_name = 'mart'").fetchall()}

    loaded: dict[str, int] = {}
    try:
        for name in (only or TABLES):
            if name not in present:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"{name}.parquet"
                con.execute(f"COPY mart.{name} TO '{path}' (FORMAT parquet)")
                # A published table is replaced wholesale: the pipeline is the
                # only writer, so there is no partial state to preserve.
                job = client.load_table_from_file(
                    path.open("rb"), f"{PROJECT}.{DATASET}.{name}",
                    job_config=bigquery.LoadJobConfig(
                        source_format=bigquery.SourceFormat.PARQUET,
                        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE))
                job.result()
            loaded[name] = client.get_table(f"{PROJECT}.{DATASET}.{name}").num_rows
    finally:
        con.close()
    return loaded
