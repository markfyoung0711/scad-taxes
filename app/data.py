"""Warehouse reads for the chart gallery."""
from __future__ import annotations

import duckdb
import pandas as pd
import streamlit as st

from scad.config import SEARCH_BASE, WAREHOUSE


@st.cache_resource
def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(WAREHOUSE), read_only=True)


@st.cache_data
def accounts() -> pd.DataFrame:
    # Town comes from the county's GIS, since the parcel page's situs line
    # carries the street but not the city.
    return _con().execute(
        "SELECT p.account, p.owner_name, p.situs_address, p.gis_parcel_id, "
        "p.sector, p.use_code, p.homestead_shown, p.tax_district, "
        "COALESCE(l.gis_city, '(unknown)') AS town "
        "FROM mart.dim_parcel p "
        "LEFT JOIN mart.dim_parcel_location l USING (gis_parcel_id) "
        "ORDER BY p.account").df()


@st.cache_data
def search(term: str, limit: int = 200) -> pd.DataFrame:
    """Find parcels by account number, owner name, or situs address.

    One box for all three because a person looking themselves up knows one of
    them and should not have to say which. Matching is case-insensitive and
    substring, so a street name finds a street and a surname finds a family.
    """
    term = (term or "").strip()
    if not term:
        return pd.DataFrame()
    like = f"%{term.upper()}%"
    return _con().execute(
        """SELECT p.account, p.owner_name, p.situs_address, p.sector, p.use_code,
                  p.homestead_shown, p.gis_parcel_id,
                  COALESCE(l.gis_city, '') AS town
           FROM mart.dim_parcel p
           LEFT JOIN mart.dim_parcel_location l USING (gis_parcel_id)
           WHERE UPPER(p.account) LIKE ?
              OR UPPER(p.owner_name) LIKE ?
              OR UPPER(p.situs_address) LIKE ?
           ORDER BY p.owner_name, p.account
           LIMIT ?""", [like, like, like, limit]).df()


@st.cache_data
def search_county(term: str, limit: int = 50) -> pd.DataFrame:
    """Search the full certified roll, not just the parcels with history.

    The roll covers every account in the county for the current year; the
    year-by-year history only covers the towns that have been crawled. A name
    can be absent from one and present in the other, and saying which is more
    useful than saying "not found".
    """
    term = (term or "").strip()
    if not term:
        return pd.DataFrame()
    like = f"%{term.upper()}%"
    return _con().execute(
        """SELECT account, owner_name, situs_address, use_code,
                  market_value, assessed_value, total_tax
           FROM mart.fact_county_parcel_year
           WHERE tax_year = (SELECT MAX(tax_year) FROM mart.fact_county_parcel_year)
             AND (UPPER(account) LIKE ? OR UPPER(owner_name) LIKE ?
                  OR UPPER(situs_address) LIKE ?)
           ORDER BY owner_name, account LIMIT ?""",
        [like, like, like, limit]).df()


@st.cache_data
def map_points(selected: tuple[str, ...], tax_year: int) -> pd.DataFrame:
    """One located parcel per row for a single year."""
    if not _has_locations():
        return pd.DataFrame()
    return _con().execute(
        "SELECT * FROM mart.v_parcel_map WHERE tax_year = ? AND account IN "
        f"({','.join('?' * len(selected))})", [tax_year, *selected]).df()


@st.cache_data
def _has_locations() -> bool:
    return bool(_con().execute(
        "SELECT COUNT(*) FROM duckdb_tables() WHERE schema_name = 'mart' "
        "AND table_name = 'dim_parcel_location'").fetchone()[0])


def has_locations() -> bool:
    return _has_locations()


@st.cache_data
def accounts_for(selected: tuple[str, ...]) -> pd.DataFrame:
    """Parcel attributes for the accounts a search selected."""
    return _con().execute(
        "SELECT p.account, p.owner_name, p.situs_address, p.gis_parcel_id, "
        "p.sector, p.use_code, p.homestead_shown, p.tax_district, "
        "COALESCE(l.gis_city, '(unknown)') AS town "
        "FROM mart.dim_parcel p "
        "LEFT JOIN mart.dim_parcel_location l USING (gis_parcel_id) "
        f"WHERE p.account IN ({','.join('?' * len(selected))}) "
        "ORDER BY p.account", list(selected)).df()


@st.cache_data
def all_sectors() -> list[str]:
    """Every sector in the warehouse, so a hue belongs to a sector for good
    rather than shifting when the selection changes."""
    return [r[0] for r in _con().execute(
        "SELECT DISTINCT sector FROM mart.dim_parcel "
        "WHERE sector IS NOT NULL ORDER BY sector").fetchall()]


def parcel_url(gis_parcel_id: str) -> str:
    """Link back to the district's own detail page for this parcel."""
    return f"{SEARCH_BASE}/parcel/{gis_parcel_id}"


def reload() -> None:
    """Drop the cached connection and frames so a rebuilt warehouse is seen."""
    _con.clear()
    st.cache_data.clear()


@st.cache_data
def by_year(selected: tuple[str, ...]) -> pd.DataFrame:
    """Account x year, with the YoY and since-baseline movement already derived."""
    df = _con().execute(
        "SELECT * FROM mart.v_parcel_value_change WHERE account IN "
        f"({','.join('?' * len(selected))}) ORDER BY account, tax_year", list(selected)).df()
    # Effective rate is what the owner actually paid per $100 of appraised value,
    # which is not any single published rate.
    df["effective_rate"] = 100.0 * df["total_tax"] / df["market_value"].replace(0, pd.NA)
    return df


@st.cache_data
def trend(selected: tuple[str, ...]) -> pd.DataFrame:
    """One row per account: the whole span compressed to totals and rates."""
    return _con().execute(
        "SELECT * FROM mart.v_parcel_trend WHERE account IN "
        f"({','.join('?' * len(selected))}) ORDER BY account", list(selected)).df()


@st.cache_data
def by_jurisdiction(selected: tuple[str, ...]) -> pd.DataFrame:
    return _con().execute(
        "SELECT * FROM mart.v_jurisdiction_change WHERE account IN "
        f"({','.join('?' * len(selected))}) ORDER BY account, tax_year, jurisdiction",
        list(selected)).df()
