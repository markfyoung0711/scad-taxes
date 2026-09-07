"""Appraised value and taxes over time, indexed to a common base, plus a map.

Value and tax are different units, so they are rebased to 100 in each account's
first published year. That puts them on one honest axis: the gap between a
dashed line and its solid partner is how far the tax bill has diverged from the
appraisal.

Color carries the sector (the Texas state property-use category), not the
account -- there are more accounts than a categorical palette can hold, and
sector is what a regional read is actually about.
"""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
from theme import style, tokens

st.set_page_config(page_title="Smith CAD value & tax trends", layout="wide")

MEASURES = [("appraised_value", "Appraised value", "solid"),
            ("total_tax", "Tax paid", "dash")]
MAX_LABELLED = 8
CHART_H = 560


def short(name: str | None, width: int = 22) -> str:
    name = (name or "").strip()
    return name if len(name) <= width else name[:width - 1] + "…"


# ------------------------------------------------------------------ controls
acct_df = data.accounts()

with st.sidebar:
    st.header("Filters")
    sectors = sorted(acct_df.sector.dropna().unique())
    picked_sectors = st.multiselect("Sector", sectors, default=sectors)

    in_sector = acct_df[acct_df.sector.isin(picked_sectors)]
    uses = sorted(in_sector.use_code.dropna().unique())
    picked_uses = st.multiselect("Use code", uses, default=uses,
                                 help="Narrows within the chosen sectors.")

    candidates = in_sector[in_sector.use_code.isin(picked_uses)]
    labels = {r.account: f"{r.account} · {short(r.owner_name, 26)}"
              for r in candidates.itertuples()}
    picked = st.multiselect("Accounts", list(labels), default=list(labels),
                            format_func=lambda a: labels[a])

    st.header("Display")
    mode = st.radio("Theme", ["light", "dark"], horizontal=True)
    label_lines = st.toggle("Label lines on the chart",
                            value=len(picked) <= MAX_LABELLED)
    y_scale = st.radio(
        "Y scale", ["Auto", "Linear", "Log"], horizontal=True,
        help="A parcel that was split or newly improved can index into the "
             "hundreds, flattening everything else on a linear axis. Auto "
             "switches to log once the spread passes 5x.")
    show_table = st.toggle("Show data table", value=False)
    if st.button("Reload warehouse", help="Pick up a rebuild without restarting"):
        data.reload()
        st.rerun()

if not picked:
    st.info("No accounts match these filters.")
    st.stop()

t = tokens(mode)
years = data.by_year(tuple(picked))
meta = acct_df.set_index("account")

# One hue per sector, assigned in a fixed order over every sector in the
# warehouse -- so filtering the list never repaints the sectors that remain.
sector_color = {s: t["series"][i % len(t["series"])]
                for i, s in enumerate(sorted(acct_df.sector.dropna().unique()))}

st.title("Appraised value & taxes over time")
st.caption(
    f"{len(picked)} account(s) · {int(years.tax_year.min())}–{int(years.tax_year.max())} · "
    "each series rebased to 100 in its own first published year"
)

# ------------------------------------------------------------------- chart
fig = go.Figure()
seen_sectors: set[str] = set()
pending_labels: list[tuple] = []

for acct in picked:
    d = years[years.account == acct].sort_values("tax_year")
    if d.empty:
        continue
    row = meta.loc[acct]
    sector = row.sector or "Unclassified"
    colour = sector_color.get(sector, t["series"][0])
    url = data.parcel_url(row.gis_parcel_id)
    who = f"{acct} · {short(row.owner_name, 30)}"

    for col_name, nice, dash in MEASURES:
        base = d[col_name].iloc[0]
        if not base:
            continue
        idx = 100.0 * d[col_name] / base
        first = sector not in seen_sectors and dash == "solid"
        seen_sectors.add(sector) if dash == "solid" else None
        fig.add_trace(go.Scatter(
            x=d.tax_year, y=idx, mode="lines+markers",
            name=sector, legendgroup=sector, showlegend=first,
            line=dict(color=colour, width=2, dash=dash),
            marker=dict(size=7),
            customdata=[[who, row.situs_address or "", nice, v, iv]
                        for v, iv in zip(d[col_name], idx)],
            hovertemplate=("%{customdata[0]}<br>%{customdata[1]}<br>"
                           "%{customdata[2]}: %{customdata[3]:$,.0f} "
                           "(index %{customdata[4]:.0f})<extra></extra>")))

    if label_lines and d.appraised_value.iloc[0]:
        # Selective direct label on the value line only: the account number,
        # linked to the district's parcel page, with the owner beside it.
        # Held until the axis type is known -- see the note below.
        idx = 100.0 * d.appraised_value / d.appraised_value.iloc[0]
        pending_labels.append((d.tax_year.iloc[-1], idx.iloc[-1], colour,
                               f'<a href="{url}" style="color:{colour}">{acct}</a> '
                               f'<span style="opacity:.75">'
                               f'{short(row.owner_name, 20)}</span>'))

# A split or a new build can index into the hundreds while everything else
# sits near 100; on a linear axis that one line flattens the rest. Default to
# log once the spread passes 5x, and let the sidebar override either way.
spread = max((tr.y.max() / max(tr.y.min(), 1e-9)) for tr in fig.data if len(tr.y))
use_log = spread > 5 if y_scale == "Auto" else y_scale == "Log"
fig.update_yaxes(title_text="Index (first year = 100)",
                 type="log" if use_log else "linear")

# Plotly places shapes and annotations in axis coordinates, and a log axis
# counts those in powers of ten -- so anything positioned by value has to be
# converted once the axis type is settled, not before.
def at_y(value: float) -> float:
    return math.log10(max(value, 1e-9)) if use_log else value


# add_hline takes the raw data value and converts for the axis itself.
fig.add_hline(y=100, line=dict(color=t["grid"], width=1))

# End-point labels cluster wherever lines converge, so nudge them apart in
# pixel space: place them in y order and keep a minimum gap, shifting only as
# far as the collision requires.
PLOT_H, GAP = CHART_H - 40, 18
if pending_labels:
    ordered = sorted(pending_labels, key=lambda r: r[1], reverse=True)
    ys = [at_y(y) for _, y, _, _ in ordered]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1.0
    placed: float | None = None
    for (x, y, colour, text), pos in zip(ordered, ys):
        px = (hi - pos) / span * PLOT_H          # 0 at the top of the cluster
        if placed is not None and px - placed < GAP:
            px = placed + GAP
        placed = px
        fig.add_annotation(x=x, y=pos, text=text, showarrow=False,
                           xanchor="left", xshift=10,
                           yshift=int(round((hi - pos) / span * PLOT_H - px)),
                           align="left", font=dict(color=colour, size=11))
style(fig, t, height=CHART_H,
      margin=dict(l=8, r=250 if label_lines else 44, t=32, b=8))
# Labels sit in the right margin; without an explicit range their width drags
# the axis out to a year that has no data.
fig.update_xaxes(range=[years.tax_year.min() - 0.25, years.tax_year.max() + 0.25],
                 tickmode="array",
                 tickvals=sorted(int(y) for y in years.tax_year.unique()))
st.plotly_chart(fig, width="stretch")

st.caption(
    ("Log scale — the spread is too wide to read linearly. " if use_log else "") +
    "Solid is appraised value, dashed is tax paid; color is the sector. "
    "Account numbers at the right link to the district's parcel page. "
    "A dashed line above its solid partner means the bill outran the "
    "appraisal — rates and exemptions moving, not the market."
)

# --------------------------------------------------------------------- map
st.divider()
st.subheader("Regional view")

if not data.has_locations():
    st.info("No geocoding staged yet. Run `scad geocode && scad build`.")
else:
    year_options = sorted(int(y) for y in years.tax_year.unique())
    map_year = st.select_slider("Tax year", year_options, value=year_options[-1])
    points = data.map_points(tuple(picked), map_year)

    if points.empty:
        st.info(f"No located parcels for {map_year}.")
    else:
        colour_by = st.radio("Color by", ["Sector", "Tax change since base"],
                             horizontal=True)
        fig = go.Figure()
        if colour_by == "Sector":
            for sector, grp in points.groupby("sector"):
                fig.add_trace(go.Scattermap(
                    lat=grp.latitude, lon=grp.longitude, mode="markers",
                    name=sector,
                    marker=dict(size=14, color=sector_color.get(sector, t["series"][0])),
                    customdata=grp[["account", "owner_name", "situs_address",
                                    "appraised_value", "total_tax"]].values,
                    hovertemplate=("%{customdata[0]} · %{customdata[1]}<br>"
                                   "%{customdata[2]}<br>"
                                   "Appraised %{customdata[3]:$,.0f}<br>"
                                   "Tax %{customdata[4]:$,.0f}<extra></extra>")))
        else:
            # Diverging on a neutral midpoint: blue is a cut, red a rise.
            pct = points.tax_pct_since_base.fillna(0)
            limit = float(pct.abs().max() or 1)
            fig.add_trace(go.Scattermap(
                lat=points.latitude, lon=points.longitude, mode="markers",
                marker=dict(size=15, color=pct, cmin=-limit, cmax=limit,
                            colorscale=[[0.0, t["pos"]], [0.5, t["mid"]],
                                        [1.0, t["neg"]]],
                            colorbar=dict(title="Tax %<br>vs base",
                                          tickfont=dict(color=t["text_secondary"]))),
                customdata=points[["account", "owner_name", "situs_address",
                                   "total_tax", "tax_pct_since_base"]].values,
                hovertemplate=("%{customdata[0]} · %{customdata[1]}<br>"
                               "%{customdata[2]}<br>"
                               "Tax %{customdata[3]:$,.0f} "
                               "(%{customdata[4]:+.0f}% vs base)<extra></extra>")))

        fig.update_layout(
            map=dict(style="carto-darkmatter" if mode == "dark" else "carto-positron",
                     center=dict(lat=points.latitude.mean(),
                                 lon=points.longitude.mean()),
                     zoom=8.5),
            height=560, margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor=t["surface"], font=dict(color=t["text_primary"]),
            legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0,
                        font=dict(color=t["text_secondary"])))
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Located against Smith County's own parcel polygons where one "
            "exists, and the county address-point layer otherwise — "
            "improvement-only accounts and recent splits have no polygon of "
            "their own.")

# ------------------------------------------------------------------ roster
st.divider()
st.subheader("Parcels")
roster = (candidates[candidates.account.isin(picked)]
          .assign(link=lambda df: df.gis_parcel_id.map(data.parcel_url))
          [["account", "owner_name", "situs_address", "sector", "use_code", "link"]])
st.dataframe(roster, width="stretch", hide_index=True,
             column_config={"link": st.column_config.LinkColumn(
                 "Detail", display_text="parcel page")})

if show_table:
    st.subheader("Values by year")
    st.dataframe(
        years[["account", "tax_year", "appraised_value", "assessed_value",
               "total_tax", "appraised_pct_yoy", "tax_pct_yoy",
               "appraised_pct_since_base", "tax_pct_since_base"]],
        width="stretch", hide_index=True)
