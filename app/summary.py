"""Year-by-year tax movement as a banded matrix, with a drill-down.

Bands are configurable but default to Texas SB2's voter-approval rate: a city
or county needs an election to raise more than 3.5% in new revenue, so that is
the line between an ordinary year and one worth looking at, rather than a round
number picked for looking round.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

GREEN_DEFAULT, YELLOW_DEFAULT = 3.5, 10.0


def band(pct: float | None, green: float, yellow: float) -> str:
    if pct is None or pd.isna(pct):
        return "none"
    if pct <= green:
        return "green"
    return "yellow" if pct <= yellow else "red"


def _fills(t: dict) -> dict[str, str]:
    """Backgrounds tinted from the diverging pair, not the categorical hues --
    these encode a level, not an identity."""
    dark = t["surface"] == "#1a1a19"
    return {
        "green":  "rgba(42,120,214,.30)" if dark else "rgba(42,120,214,.16)",
        "yellow": "rgba(237,161,0,.34)"  if dark else "rgba(237,161,0,.24)",
        "red":    "rgba(227,73,72,.34)"  if dark else "rgba(227,73,72,.22)",
        "none":   "transparent",
    }


def render(years: pd.DataFrame, trend: pd.DataFrame, meta: pd.DataFrame,
           t: dict) -> str | None:
    """Draw the summary table; return the account the user drilled into."""
    st.subheader("Tax increase by year")

    c1, c2, c3, c4 = st.columns([1, 1, 1.3, 1.5])
    green = c1.number_input("Green up to (%)", value=GREEN_DEFAULT, step=0.5,
                            help="Texas SB2 sets the voter-approval rate at "
                                 "3.5% for cities and counties, 2.5% for "
                                 "school districts.")
    yellow = c2.number_input("Yellow up to (%)", value=YELLOW_DEFAULT, step=0.5)
    cells = c3.radio("Cells show", ["% change", "$ change"], horizontal=True,
                     help="Colour always follows the percentage; this only "
                          "changes the number printed in the cell.")
    rank_by = c4.selectbox(
        "Rank by", ["Compound annual %", "Total %", "Total $ increase",
                    "Biggest single-year $ jump", "Tax paid, all years"],
        help="Percentages off a near-zero base — an ag or homestead valuation "
             "ending — are real but dwarf everything else. Rank by dollars to "
             "see the largest actual increases.")

    matrix = (years.pivot_table(index="account", columns="tax_year",
                                values="tax_pct_yoy", aggfunc="first")
              .sort_index(axis=1))
    matrix.columns = [str(int(c)) for c in matrix.columns]
    year_cols = list(matrix.columns)

    # One owner often holds several parcels, so the name alone does not
    # identify a row; the district's use code is what tells them apart, and it
    # earns its own column so rows can be grouped by it.
    info = meta.reindex(matrix.index)
    summary = (trend.set_index("account")
               .reindex(matrix.index)
               .assign(owner=info.owner_name,
                       use=info.use_code.fillna("").str.split(":").str[0].str.strip()))
    # Dollar movement alongside the percentage: a bill going $77 -> $14,269
    # and one going $4,000 -> $4,800 are not the same event, and neither
    # measure describes both.
    dollars = (years.assign(delta=years.groupby("account").total_tax.diff())
               .pivot_table(index="account", columns="tax_year",
                            values="delta", aggfunc="first")
               .sort_index(axis=1))
    dollars.columns = [str(int(c)) for c in dollars.columns]
    dollars = dollars.reindex(index=matrix.index, columns=year_cols)

    table = (dollars if cells == "$ change" else matrix).copy()
    table.insert(0, "Owner", summary.owner)
    table.insert(1, "Use", summary.use)
    # Mean of yearly percentages overstates a volatile series; the compound
    # rate is what actually happened, so it is the one to sort on.
    table["Avg YoY"] = matrix.mean(axis=1, skipna=True)
    table["CAGR"] = summary.tax_cagr_pct
    table["Total %"] = summary.tax_pct_total
    table["Total $"] = (summary.last_total_tax - summary.first_total_tax)
    table["Biggest $ jump"] = dollars.max(axis=1, skipna=True)
    table["Tax, all years"] = (years.groupby("account").total_tax.sum()
                               .reindex(matrix.index))

    # Year headers pivot out as ints and the rest are labels; a mixed column
    # index cannot round-trip through Arrow, so the whole set is coerced here
    # rather than at each place one is built.
    table.columns = [str(c) for c in table.columns]

    sort_column = {"Compound annual %": "CAGR", "Total %": "Total %",
                   "Total $ increase": "Total $",
                   "Biggest single-year $ jump": "Biggest $ jump",
                   "Tax paid, all years": "Tax, all years"}[rank_by]
    table = table.sort_values(sort_column, ascending=False, na_position="last")

    fills = _fills(t)
    # Colour follows the percentage even when the cell prints dollars, so the
    # banding means one thing throughout.
    shade = matrix.reindex(index=table.index, columns=year_cols)
    cell_format = "${:+,.0f}" if cells == "$ change" else "{:+.1f}%"
    styled = (table.style
              .apply(lambda col: [
                  f"background-color: {fills[band(v, green, yellow)]}"
                  for v in shade[col.name]], subset=year_cols)
              .map(lambda v: f"background-color: {fills[band(v, green, yellow)]}",
                   subset=["Avg YoY", "CAGR"])
              .format({**{c: cell_format for c in year_cols},
                       "Avg YoY": "{:+.1f}%", "CAGR": "{:+.1f}%",
                       "Total %": "{:+.1f}%", "Total $": "${:+,.0f}",
                       "Biggest $ jump": "${:+,.0f}",
                       "Tax, all years": "${:,.0f}"}, na_rep="—"))

    picked = st.dataframe(
        styled, width="stretch", on_select="rerun",
        selection_mode="single-row", key="summary_table",
        column_config={"Use": st.column_config.TextColumn(
            "Use", width="small",
            help="The district's property use code — A is single-family, D "
                 "qualified agricultural, E rural land. One owner can hold "
                 "several parcels under different codes.")})
    st.caption(
        f"Each cell is that year's change against the one before, shaded green "
        f"to {green:g}%, yellow to {yellow:g}%, red above — the shading always "
        f"follows the percentage. A dash means there is no prior year to "
        f"compare; a parcel is often appraised before it is levied. "
        f"Select a row to drill in.")
    st.caption(
        "Percentages off a near-zero base are real, not glitches: a parcel "
        "losing an agricultural or homestead valuation can go from a $77 bill "
        "to a $14,269 one. Rank by dollars to see the largest increases in "
        "money rather than in ratio.")

    rows = picked.selection.get("rows") if picked and picked.selection else None
    return table.index[rows[0]] if rows else None
