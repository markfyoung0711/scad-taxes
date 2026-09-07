"""Load a certified appraisal roll export into the warehouse.

The district publishes one year at a time, so this is the whole county for the
current roll: 144k real-property accounts against the ~100 the parcel-page
crawl reaches. What it does not give is history -- prior years are not
published and need a public information request (see docs/).

Two quirks of the file drive the shape of this module:

* The real-property header mislabels D3's tax-value column as `D4_TAX_VAL`,
  so there are two columns by that name. District groups are therefore
  unpivoted by position -- four columns each, 27 of them, from a fixed offset
  -- and never by name.
* The files are latin-1, and money appears both bare (`598098`) and
  comma-grouped inside quotes (`"22,750"`).
"""
from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import duckdb

from .config import RAW, STAGED

DISTRICT_WIDTH = 4      # code, rate, taxable value, tax
DISTRICT_COUNT = 27


def unpack(year: int, kind: str = "all") -> Path:
    """Extract the landed roll archive into data/staged/bulk/<year>/."""
    archives = sorted((RAW / "bulk_roll" / str(year)).glob("*.zip"))
    if not archives:
        raise FileNotFoundError(f"no roll archive landed for {year}; run `scad roll {year}`")
    out = STAGED / "bulk" / str(year)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archives[-1]) as z:
        z.extractall(out)
    return out


def _find(directory: Path, needle: str) -> Path:
    hits = [p for p in directory.glob("*.csv") if needle.lower() in p.name.lower()]
    if not hits:
        raise FileNotFoundError(f"no {needle} file under {directory}")
    return hits[0]


def _district_sql(header: list[str], table: str, year: int) -> str:
    """One SELECT per district slot, unioned -- positional, because of the
    duplicated `D4_TAX_VAL` header."""
    start = header.index("D1")
    parts = []
    for n in range(DISTRICT_COUNT):
        code, rate, value, tax = (
            f'"{header[start + n * DISTRICT_WIDTH + i]}"' if i != 2 else
            # The duplicate is renamed by DuckDB on read; address both by the
            # position DuckDB gives them.
            f'"{header[start + n * DISTRICT_WIDTH + 2]}"'
            for i in range(DISTRICT_WIDTH))
        parts.append(
            f"SELECT \"ACCOUNT NUM\" AS account, {year} AS tax_year, "
            f"{code} AS jurisdiction, {rate} AS tax_rate, "
            f"{value} AS taxable_value, {tax} AS tax_amount FROM {table}")
    return "\nUNION ALL\n".join(parts)


def load(con: duckdb.DuckDBPyConnection, year: int) -> dict[str, int]:
    """Read the extracted CSVs into raw.* and stg.bulk_* for `year`."""
    directory = STAGED / "bulk" / str(year)
    real = _find(directory, "RealPropCertifiedAppraisalRoll_Extract1")
    exempt = _find(directory, "RealPropCertifiedAppraisalRoll_Extract2")

    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute("CREATE SCHEMA IF NOT EXISTS stg")

    read = "header=true, all_varchar=true, encoding='latin-1'"
    con.execute(f"CREATE OR REPLACE TABLE raw.bulk_real AS "
                f"SELECT * FROM read_csv('{real}', {read})")
    con.execute(f"CREATE OR REPLACE TABLE raw.bulk_real_exemption AS "
                f"SELECT * FROM read_csv('{exempt}', {read})")

    # Money arrives bare or comma-grouped inside quotes; strip before casting.
    con.execute("""
        CREATE OR REPLACE MACRO money(x) AS
            TRY_CAST(NULLIF(REPLACE(REPLACE(TRIM(COALESCE(x, '')), ',', ''),
                                    '$', ''), '') AS DECIMAL(16,2))
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE stg.bulk_parcel_year AS
        SELECT
            "ACCOUNT NUM"              AS account,
            "GEO ACCOUNT NUM"          AS gis_parcel_id,
            {year}                     AS tax_year,
            NAME                       AS owner_name,
            SITUS_ADDRESSS             AS situs_address,
            "USE CODE"                 AS use_code,
            NEIGHBORHOOD               AS neighborhood,
            money("LAND MKT VALUE")    AS land_value,
            money("TOTAL BUILDING VALUE") AS building_value,
            money("MKT VAL")           AS market_value,
            money("APPRAISED VAL")     AS appraised_value,
            money("ASSESSED VALUE")    AS assessed_value,
            money("HMS CAP EXEMPT VAL") AS homestead_cap_loss,
            money(ACREAGE)             AS acreage,
            YEAR_BUILT                 AS year_built
        FROM raw.bulk_real
    """)

    header = next(csv.reader(open(real, encoding="latin-1")))
    con.execute(f"""
        CREATE OR REPLACE TABLE stg.bulk_parcel_jurisdiction_year AS
        SELECT account, tax_year, TRIM(jurisdiction) AS jurisdiction,
               money(tax_rate) AS tax_rate,
               money(taxable_value) AS taxable_value,
               money(tax_amount) AS tax_amount
        FROM ({_district_sql(header, 'raw.bulk_real', year)})
        WHERE jurisdiction IS NOT NULL AND TRIM(jurisdiction) <> ''
    """)

    con.execute("""
        CREATE OR REPLACE TABLE stg.bulk_exemption AS
        SELECT ACCOUNT AS account, "GEO ACCOUNT" AS gis_parcel_id,
               "EXEMPT CD" AS exempt_code, "EXEMPT CD DESC" AS exempt_desc,
               "TAX DIST CD" AS tax_district,
               money("TAX DIST EXEMPT VAL") AS exempt_value
        FROM raw.bulk_real_exemption
    """)

    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("stg.bulk_parcel_year", "stg.bulk_parcel_jurisdiction_year",
                      "stg.bulk_exemption")}
