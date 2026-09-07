"""Warehouse reads for the chart gallery."""
from __future__ import annotations

import duckdb
import pandas as pd
import streamlit as st

from scad.config import WAREHOUSE


@st.cache_resource
def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(WAREHOUSE), read_only=True)


@st.cache_data
def accounts() -> pd.DataFrame:
    return _con().execute(
        "SELECT account, owner_name, situs_address FROM mart.dim_parcel ORDER BY account"
    ).df()


@st.cache_data
def by_year(selected: tuple[str, ...]) -> pd.DataFrame:
    """Account x year, with the YoY and since-baseline movement already derived."""
    df = _con().execute(
        "SELECT * FROM mart.v_parcel_value_change WHERE account IN "
        f"({','.join('?' * len(selected))}) ORDER BY account, tax_year", list(selected)).df()
    # Effective rate is what the owner actually paid per $100 of appraised value,
    # which is not any single published rate.
    df["effective_rate"] = 100.0 * df["total_tax"] / df["appraised_value"].replace(0, pd.NA)
    return df


@st.cache_data
def by_jurisdiction(selected: tuple[str, ...]) -> pd.DataFrame:
    return _con().execute(
        "SELECT * FROM mart.v_jurisdiction_change WHERE account IN "
        f"({','.join('?' * len(selected))}) ORDER BY account, tax_year, jurisdiction",
        list(selected)).df()
