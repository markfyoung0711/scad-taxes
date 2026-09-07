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
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import summary
from theme import style, tokens

st.set_page_config(page_title="Smith CAD value & tax trends", layout="wide")

# "Tax paid" is the whole levy in dollars, not a rate: the district publishes
# rates per $100 of value, but what a line here traces is the bill itself.
MEASURES = [("appraised_value", "Appraised value", "solid"),
            ("total_tax", "Tax paid (total $)", "dash")]
MAX_LABELLED = 8
MAX_SERIES = 8
CHART_H = 560


def short(name: str | None, width: int = 22) -> str:
    name = (name or "").strip()
    return name if len(name) <= width else name[:width - 1] + "…"


def rebase(values: pd.Series, tax_years: pd.Series):
    """Index to 100 at the first year the measure actually has a figure.

    A parcel's first published year is not always its first *taxed* year -- a
    new build or a split appears on the roll with an appraisal before any levy
    is calculated. Indexing off the parcel's first year would divide by a
    missing number and silently drop the whole series, so each measure is
    rebased on its own first real value and the offset is reported.
    """
    usable = values.notna() & (values != 0)
    if not usable.any():
        return None, None
    base = values[usable].iloc[0]
    return 100.0 * values / base, int(tax_years[usable].iloc[0])


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
    # A categorical palette holds eight hues and they are never cycled, so
    # colouring by account stops being offered past that.
    colour_choices = (["Account", "Sector"] if len(picked) <= MAX_SERIES
                      else ["Sector"])
    colour_mode = st.radio(
        "Color by", colour_choices, horizontal=True,
        help="Account gives each parcel its own hue, with solid for appraised "
             "value and dashed for tax paid. Sector groups them once there "
             "are more parcels than a palette can hold.")
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
# Colouring by measure puts appraised value against tax paid for one account;
# the account is then carried by the dash pattern instead.
measure_color = {"appraised_value": t["series"][0], "total_tax": t["series"][1]}
account_color = {a: t["series"][i % len(t["series"])] for i, a in enumerate(picked)}

# With one parcel there is no identity to encode, so colour is free to carry
# the measure -- that is the close read, value against tax. With more than one,
# colour belongs to the parcel and the dash tells the two measures apart.
SOLO = len(picked) == 1

st.title("Appraised value & taxes over time")
st.caption(
    f"{len(picked)} account(s) · {int(years.tax_year.min())}–{int(years.tax_year.max())} · "
    "each series rebased to 100 in its own first published year"
)

# ------------------------------------------------------------------- chart
fig = go.Figure()
seen_sectors: set[str] = set()
pending_labels: list[tuple] = []

for n, acct in enumerate(picked):
    d = years[years.account == acct].sort_values("tax_year")
    if d.empty:
        continue
    row = meta.loc[acct]
    sector = row.sector or "Unclassified"
    url = data.parcel_url(row.gis_parcel_id)
    who = f"{acct} · {short(row.owner_name, 30)}"

    for col_name, nice, sector_dash in MEASURES:
        idx, _ = rebase(d[col_name], d.tax_year)
        if idx is None:
            continue

        dash = sector_dash  # solid for appraised value, dashed for tax paid
        if SOLO:
            # Colour is free to carry the measure with a single parcel, but the
            # dash still means what it means everywhere else.
            colour, legend_name = measure_color[col_name], nice
            first = True
        elif colour_mode == "Account":
            colour = account_color[acct]
            legend_name = f"{acct} · {short(row.owner_name, 24)}"
            first = sector_dash == "solid"
        else:
            colour = sector_color.get(sector, t["series"][0])
            legend_name = sector
            first = sector not in seen_sectors and sector_dash == "solid"
            if sector_dash == "solid":
                seen_sectors.add(sector)

        fig.add_trace(go.Scatter(
            x=d.tax_year, y=idx, mode="lines+markers",
            name=legend_name, legendgroup=legend_name, showlegend=first,
            line=dict(color=colour, width=2, dash=dash),
            marker=dict(size=7),
            customdata=[[who, row.situs_address or "", nice, v, iv]
                        for v, iv in zip(d[col_name], idx)],
            hovertemplate=("%{customdata[0]}<br>%{customdata[1]}<br>"
                           "%{customdata[2]}: %{customdata[3]:$,.0f} "
                           "(index %{customdata[4]:.0f})<extra></extra>")))

    value_idx, _ = rebase(d.appraised_value, d.tax_year)
    if label_lines and value_idx is not None:
        # Selective direct label on the value line only: the account number,
        # linked to the district's parcel page, with the owner beside it.
        # Held until the axis type is known -- see the note below.
        idx = 100.0 * d.appraised_value / d.appraised_value.iloc[0]
        label_colour = measure_color["appraised_value"] if SOLO else colour
        pending_labels.append((d.tax_year.iloc[-1], idx.iloc[-1], label_colour,
                               f'<a href="{url}" style="color:{label_colour}">{acct}</a> '
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
# Reserve only as much right margin as the longest label actually needs,
# rather than a fixed band that reads as dead space for a single account.
label_px = max((len(re.sub(r"<[^>]+>", "", txt)) for *_, txt in pending_labels),
               default=0) * 6 + 24
style(fig, t, height=CHART_H,
      margin=dict(l=8, r=min(label_px, 260) if pending_labels else 44,
                  t=32, b=8))
# Labels sit in the right margin; without an explicit range their width drags
# the axis out to a year that has no data.
fig.update_xaxes(range=[years.tax_year.min() - 0.25, years.tax_year.max() + 0.25],
                 tickmode="array",
                 tickvals=sorted(int(y) for y in years.tax_year.unique()))
st.plotly_chart(fig, width="stretch")

st.caption(
    ("Log scale — the spread is too wide to read linearly. " if use_log else "") +
    ("Blue solid is appraised value, orange dashed is tax paid. " if SOLO else
     "Solid is appraised value, dashed is tax paid; color is the "
     f"{colour_mode.lower()}. ") +
    "Both are indexed, so the lines show movement, not amounts — tax paid is "
    "the whole levy in dollars, not a rate per $100. Hover for the figures, "
    "or read the totals in the roster below. "
    "Account numbers at the right link to the district's parcel page. "
    "A dashed line above its solid partner means the bill outran the "
    "appraisal — rates and exemptions moving, not the market."
)

# ------------------------------------------------------------------ summary
st.divider()
focus = summary.render(years, data.trend(tuple(picked)), meta, t)

if focus:
    row = meta.loc[focus]
    st.markdown(f"#### {focus} · {row.owner_name}")
    st.caption(f"{row.situs_address or '(no situs)'} · {row.use_code} · "
               f"[parcel page]({data.parcel_url(row.gis_parcel_id)})")

    detail = years[years.account == focus].sort_values("tax_year")
    left, right = st.columns(2)
    with left:
        st.dataframe(
            detail[["tax_year", "appraised_value", "assessed_value", "total_tax",
                    "appraised_pct_yoy", "tax_pct_yoy"]],
            width="stretch", hide_index=True, column_config={
                "tax_year": st.column_config.NumberColumn("Year", format="%d"),
                "appraised_value": st.column_config.NumberColumn(
                    "Appraised", format="$%,.0f"),
                "assessed_value": st.column_config.NumberColumn(
                    "Assessed", format="$%,.0f"),
                "total_tax": st.column_config.NumberColumn("Tax", format="$%,.2f"),
                "appraised_pct_yoy": st.column_config.NumberColumn(
                    "Appraised YoY", format="%+.1f%%"),
                "tax_pct_yoy": st.column_config.NumberColumn(
                    "Tax YoY", format="%+.1f%%")})
    with right:
        # Which taxing unit actually moved the bill, for the same account.
        jur = data.by_jurisdiction((focus,))
        st.dataframe(
            jur[["tax_year", "jurisdiction", "taxable_value", "tax_rate",
                 "tax_amount", "tax_change_yoy"]].sort_values(
                     ["tax_year", "jurisdiction"], ascending=[False, True]),
            width="stretch", hide_index=True, column_config={
                "tax_year": st.column_config.NumberColumn("Year", format="%d"),
                "jurisdiction": "Jurisdiction",
                "taxable_value": st.column_config.NumberColumn(
                    "Taxable", format="$%,.0f"),
                "tax_rate": st.column_config.NumberColumn(
                    "Rate /$100", format="%.6f"),
                "tax_amount": st.column_config.NumberColumn("Tax", format="$%,.2f"),
                "tax_change_yoy": st.column_config.NumberColumn(
                    "Δ Tax", format="$%,.2f")})

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
            # A parcel with no levied year has no baseline to measure from;
            # colouring it zero would paint "never taxed" as "no change", so
            # it is left off and counted underneath instead.
            shown = points[points.tax_pct_since_base.notna()]
            untaxed = len(points) - len(shown)
            pct = shown.tax_pct_since_base
            limit = float(pct.abs().max() or 1)
            fig.add_trace(go.Scattermap(
                lat=shown.latitude, lon=shown.longitude, mode="markers",
                marker=dict(size=15, color=pct, cmin=-limit, cmax=limit,
                            colorscale=[[0.0, t["pos"]], [0.5, t["mid"]],
                                        [1.0, t["neg"]]],
                            colorbar=dict(title="Tax %<br>vs base",
                                          tickfont=dict(color=t["text_secondary"]))),
                customdata=shown[["account", "owner_name", "situs_address",
                                  "total_tax", "tax_pct_since_base",
                                  "tax_base_year"]].values,
                hovertemplate=("%{customdata[0]} · %{customdata[1]}<br>"
                               "%{customdata[2]}<br>"
                               "Tax %{customdata[3]:$,.0f} "
                               "(%{customdata[4]:+.0f}% since %{customdata[5]})"
                               "<extra></extra>")))
            if untaxed:
                st.caption(f"{untaxed} parcel(s) not plotted: no levied year to "
                           f"measure a change from.")

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
latest_year = int(years.tax_year.max())
totals = (years.groupby("account")
          .agg(tax_all_years=("total_tax", "sum"),
               years_taxed=("total_tax", "count"))
          .reset_index())
latest = (years[years.tax_year == latest_year]
          [["account", "appraised_value", "total_tax"]]
          .rename(columns={"appraised_value": "appraised_latest",
                           "total_tax": "tax_latest"}))

roster = (candidates[candidates.account.isin(picked)]
          .assign(link=lambda df: df.gis_parcel_id.map(data.parcel_url))
          .merge(latest, on="account", how="left")
          .merge(totals, on="account", how="left")
          [["account", "owner_name", "situs_address", "sector", "use_code",
            "homestead_shown", "appraised_latest", "tax_latest",
            "tax_all_years", "years_taxed", "link"]])
money = st.column_config.NumberColumn(format="$%,.0f")
st.dataframe(roster, width="stretch", hide_index=True, column_config={
    "homestead_shown": st.column_config.CheckboxColumn("Homestead"),
    "appraised_latest": st.column_config.NumberColumn(
        f"Appraised {latest_year}", format="$%,.0f"),
    "tax_latest": st.column_config.NumberColumn(
        f"Tax {latest_year}", format="$%,.2f"),
    "tax_all_years": st.column_config.NumberColumn(
        "Tax, all years", format="$%,.2f"),
    "years_taxed": st.column_config.NumberColumn("Years taxed"),
    "link": st.column_config.LinkColumn("Detail", display_text="parcel page")})
st.caption(
    "Homestead is read off the parcel page's exemptions. The district "
    "withholds some exemptions online, so an unticked box means \"not shown\", "
    "not \"none held\".")

if show_table:
    st.subheader("Values by year")
    st.dataframe(
        years[["account", "tax_year", "appraised_value", "assessed_value",
               "total_tax", "appraised_pct_yoy", "tax_pct_yoy",
               "appraised_pct_since_base", "tax_pct_since_base"]],
        width="stretch", hide_index=True)
