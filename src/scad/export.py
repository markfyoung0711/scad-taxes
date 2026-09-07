"""Homeowner extract: one record per parcel with its full year-by-year history."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .warehouse import connect

PARCEL_COLUMNS = ("id", "name", "address", "town", "precinct", "precinct_name",
                  "commissioner_precinct", "property_type", "use_code", "sector",
                  "homestead_exemption", "gis_parcel_id", "latitude", "longitude")


def _num(value):
    """Money comes back as Decimal; JSON has no such type."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def homeowners(limit: int | None = None, *, town: str | None = None) -> list[dict]:
    con = connect(read_only=True)
    try:
        where, params = [], []
        if town:
            where.append("UPPER(town) = UPPER(?)")
            params.append(town)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = con.execute(
            f"SELECT {', '.join(PARCEL_COLUMNS)} FROM mart.v_homeowner {clause} "
            f"ORDER BY id {f'LIMIT {int(limit)}' if limit else ''}", params).fetchall()

        history: dict[str, list] = {}
        for account, year, market, tax in con.execute(
                "SELECT account, tax_year, market_value, total_tax "
                "FROM mart.fact_parcel_year ORDER BY account, tax_year").fetchall():
            history.setdefault(account, []).append({
                "year": year,
                "market_value": _num(market),
                "tax_amount": _num(tax),
            })
    finally:
        con.close()

    out = []
    for row in rows:
        record = {k: _num(v) for k, v in zip(PARCEL_COLUMNS, row)}
        record["tax_history"] = history.get(record["id"], [])
        out.append(record)
    return out


def write(path: Path, limit: int | None = None, *, town: str | None = None) -> int:
    records = homeowners(limit, town=town)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"homeowners": records}, indent=2))
    return len(records)
