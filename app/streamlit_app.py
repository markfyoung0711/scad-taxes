"""Chart gallery: appraised value and taxes over time, one form per section.

Every form here answers the same question in a different shape so you can pick
one. The ordering is a recommendation, not a ranking of effort.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import data
from theme import style, tokens

st.set_page_config(page_title="Smith CAD value & tax trends", layout="wide")

# ---------------------------------------------------------------- controls
acct_df = data.accounts()
with st.sidebar:
    st.header("Controls")
    labels = {
        r.account: f"{r.account} · {r.situs_address or '(no situs)'}"
        for r in acct_df.itertuples()
    }
    picked = st.multiselect("Accounts", list(labels), default=list(labels),
                            format_func=lambda a: labels[a])
    mode = st.radio("Theme", ["light", "dark"], horizontal=True)
    show_tables = st.toggle("Show data tables", value=False,
                            help="Aqua and yellow fall below 3:1 on the light "
                                 "surface; the table is the relief.")

if not picked:
    st.info("Pick at least one account.")
    st.stop()

t = tokens(mode)
years = data.by_year(tuple(picked))
juris = data.by_jurisdiction(tuple(picked))
focus = picked[0]
color = {a: t["series"][i % len(t["series"])] for i, a in enumerate(picked)}

st.title("Appraised value & taxes over time")
st.caption(
    f"{len(picked)} account(s) · {int(years.tax_year.min())}–{int(years.tax_year.max())} · "
    "rates are published per $100 of value"
)


def section(n: int, title: str, best_for: str, note: str | None = None):
    st.divider()
    st.subheader(f"{n}. {title}")
    st.caption(f"**Best for:** {best_for}")
    if note:
        st.caption(note)


def table(df: pd.DataFrame):
    if show_tables:
        st.dataframe(df, width="stretch", hide_index=True)


def label_last(fig, x, y, text, colour, row=None, col=None):
    """Selective direct label: the last point only, never every point."""
    fig.add_annotation(x=x, y=y, text=text, showarrow=False, xanchor="left",
                       xshift=6, font=dict(color=colour, size=11),
                       row=row, col=col)


# ------------------------------------------------- 1. small multiples
section(1, "Small multiples", "maximum clarity — no scale confusion at all",
        "Three panels on one time axis. Recommended: appraised value, tax paid "
        "and effective rate are three different units, so they get three axes "
        "stacked rather than two crammed onto one plot.")

fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                    subplot_titles=("Appraised value", "Total tax",
                                    "Effective rate (tax per $100 appraised)"))
for acct in picked:
    d = years[years.account == acct]
    for row, (col_name, fmt) in enumerate(
            [("appraised_value", "${:,.0f}"), ("total_tax", "${:,.0f}"),
             ("effective_rate", "{:.3f}")], start=1):
        fig.add_trace(go.Scatter(
            x=d.tax_year, y=d[col_name], name=acct, legendgroup=acct,
            showlegend=(row == 1 and len(picked) > 1),
            mode="lines+markers", line=dict(color=color[acct], width=2),
            marker=dict(size=8)), row=row, col=1)
        last = d.iloc[-1]
        label_last(fig, last.tax_year, last[col_name],
                   fmt.format(last[col_name]), color[acct], row=row, col=1)
style(fig, t, height=680, legend=len(picked) > 1)
fig.update_annotations(font=dict(color=t["text_secondary"], size=12))
st.plotly_chart(fig, width="stretch")
table(years[["account", "tax_year", "appraised_value", "assessed_value",
             "total_tax", "effective_rate"]])

# ------------------------------------------------- 2. indexed to a common base
section(2, "Indexed to a common base", "seeing which grew faster, on one honest axis",
        "Both measures rebased to 100 in each account's first year. This is the "
        "correct way to put two different scales on a single axis — the gap "
        "between the lines is the divergence you actually want to read.")

fig = go.Figure()
for i, acct in enumerate(picked):
    d = years[years.account == acct].copy()
    for j, (col_name, nice) in enumerate([("appraised_value", "Appraised value"),
                                          ("total_tax", "Tax paid")]):
        idx = 100.0 * d[col_name] / d[col_name].iloc[0]
        fig.add_trace(go.Scatter(
            x=d.tax_year, y=idx, mode="lines+markers",
            name=f"{nice}" + (f" · {acct}" if len(picked) > 1 else ""),
            line=dict(color=t["series"][j], width=2,
                      dash="solid" if i == 0 else "dash"),
            marker=dict(size=8)))
        label_last(fig, d.tax_year.iloc[-1], idx.iloc[-1], f"{idx.iloc[-1]:.0f}",
                   t["series"][j])
fig.add_hline(y=100, line=dict(color=t["grid"], width=1))
fig.update_yaxes(title_text="Index (first year = 100)")
style(fig, t, height=420)
st.plotly_chart(fig, width="stretch")

# ------------------------------------------------- 3. area + line
section(3, "Area + line (indexed)", "value as the story, tax as the counterpoint",
        "Filled area carries the magnitude of the value change; the line rides "
        "on top. Indexed so both share one axis.")

d = years[years.account == focus].copy()
v_idx = 100.0 * d.appraised_value / d.appraised_value.iloc[0]
t_idx = 100.0 * d.total_tax / d.total_tax.iloc[0]
fill = "rgba(42,120,214,0.18)" if mode == "light" else "rgba(57,135,229,0.22)"
fig = go.Figure()
# Fill between the value line and the index baseline, so the shaded band reads
# as "how far above/below its starting point" rather than a slab up from zero.
fig.add_trace(go.Scatter(x=d.tax_year, y=[100] * len(d), mode="lines",
                         line=dict(color=t["grid"], width=1),
                         hoverinfo="skip", showlegend=False))
fig.add_trace(go.Scatter(x=d.tax_year, y=v_idx, name="Appraised value", fill="tonexty",
                         mode="lines", line=dict(color=t["series"][0], width=2),
                         fillcolor=fill))
fig.add_trace(go.Scatter(x=d.tax_year, y=t_idx, name="Tax paid", mode="lines+markers",
                         line=dict(color=t["series"][1], width=2), marker=dict(size=8)))
label_last(fig, d.tax_year.iloc[-1], v_idx.iloc[-1], f"{v_idx.iloc[-1]:.0f}", t["series"][0])
label_last(fig, d.tax_year.iloc[-1], t_idx.iloc[-1], f"{t_idx.iloc[-1]:.0f}", t["series"][1])
fig.update_yaxes(title_text="Index (first year = 100)")
style(fig, t, height=400)
st.plotly_chart(fig, width="stretch")
st.caption(f"Showing {focus}. Pick a different first account in the sidebar to change it.")

# ------------------------------------------------- 4. waterfall
section(4, "Waterfall — year-over-year change", "how much moved each year, and which way",
        "Absolute levels drop out; only the deltas remain. Reads volatility "
        "faster than any line chart.")

metric = st.radio("Measure", ["Appraised value", "Total tax"], horizontal=True,
                  key="waterfall_metric")
col_name = "appraised_value" if metric == "Appraised value" else "total_tax"
d = years[years.account == focus]
fig = go.Figure(go.Waterfall(
    orientation="v",
    measure=["absolute"] + ["relative"] * (len(d) - 1),
    x=[str(y) for y in d.tax_year],
    y=[d[col_name].iloc[0]] + list(d[col_name].diff().dropna()),
    increasing=dict(marker=dict(color=t["neg"])),   # a rising bill is the bad direction
    decreasing=dict(marker=dict(color=t["pos"])),
    totals=dict(marker=dict(color=t["text_secondary"])),
    connector=dict(line=dict(color=t["grid"], width=1)),
    text=[f"${v:,.0f}" for v in [d[col_name].iloc[0]] + list(d[col_name].diff().dropna())],
    textposition="outside", textfont=dict(color=t["text_secondary"], size=11)))
style(fig, t, height=420, legend=False)
fig.update_layout(hovermode="x")
st.plotly_chart(fig, width="stretch")
st.caption(f"Showing {focus} · {metric.lower()}. Red is an increase, blue a decrease; the grey opening bar is the baseline year's level, not a change.")

# ------------------------------------------------- 5. slope
section(5, "Slope chart — first year vs last", "the whole span as one comparison",
        "Two points per account. Strips out every intermediate year to answer "
        "'where did this end up?'")

fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.16,
                    subplot_titles=("Appraised value", "Total tax"))
for acct in picked:
    d = years[years.account == acct]
    for c, col_name in enumerate(["appraised_value", "total_tax"], start=1):
        first, last = d.iloc[0], d.iloc[-1]
        pct = 100.0 * (last[col_name] - first[col_name]) / first[col_name]
        fig.add_trace(go.Scatter(
            x=[int(first.tax_year), int(last.tax_year)],
            y=[first[col_name], last[col_name]],
            mode="lines+markers", name=acct, legendgroup=acct,
            showlegend=(c == 1 and len(picked) > 1),
            line=dict(color=color[acct], width=2), marker=dict(size=10)), row=1, col=c)
        # Annotations, not trace text: trace text is clipped at the plot edge,
        # annotations render into the margin where these labels need to sit.
        for x, y, txt, anchor, shift in [
                (first.tax_year, first[col_name], f"${first[col_name]:,.0f}", "right", -10),
                (last.tax_year, last[col_name], f"${last[col_name]:,.0f} ({pct:+.0f}%)", "left", 10)]:
            fig.add_annotation(x=int(x), y=y, text=txt, showarrow=False,
                               xanchor=anchor, xshift=shift,
                               font=dict(color=t["text_secondary"], size=11),
                               row=1, col=c)
first_year, last_year = int(years.tax_year.min()), int(years.tax_year.max())
style(fig, t, height=400, legend=len(picked) > 1,
      margin=dict(l=100, r=150, t=48, b=8))
# A slope chart labels its own end points, so the value axis is scaffolding.
fig.update_yaxes(showticklabels=False, showgrid=False)
fig.update_xaxes(tickmode="array", tickvals=[first_year, last_year],
                 range=[first_year - 0.08 * (last_year - first_year),
                        last_year + 0.08 * (last_year - first_year)])
fig.update_annotations(font=dict(color=t["text_secondary"], size=12))
st.plotly_chart(fig, width="stretch")

# ------------------------------------------------- 6. stacked bar
section(6, "Stacked bar — tax by jurisdiction", "who is actually charging you",
        "Stacking is legitimate here: the jurisdiction taxes are parts of one "
        "whole — they sum to the year's bill.")

d = juris[juris.account == focus]
fig = go.Figure()
for i, name in enumerate(sorted(d.jurisdiction.unique())):
    j = d[d.jurisdiction == name].sort_values("tax_year")
    fig.add_trace(go.Bar(x=j.tax_year, y=j.tax_amount, name=name,
                         marker=dict(color=t["series"][i],
                                     line=dict(color=t["surface"], width=2))))
fig.update_layout(barmode="stack", bargap=0.35)
fig.update_yaxes(title_text="Tax ($)")
style(fig, t, height=420)
fig.update_layout(hovermode="x unified")
st.plotly_chart(fig, width="stretch")
st.caption(f"Showing {focus}. The 2px surface gap between segments is deliberate.")
table(d[["tax_year", "jurisdiction", "taxable_value", "tax_rate", "tax_amount"]])

# ------------------------------------------------- 7. heatmap
section(7, "Heatmap — YoY change by jurisdiction", "spotting which year and which taxing unit moved",
        "Diverging blue↔red on a neutral midpoint: blue is a cut, red a rise, "
        "gray is no change.")

d = juris[(juris.account == focus) & juris.tax_change_yoy.notna()]
pivot = d.pivot_table(index="jurisdiction", columns="tax_year",
                      values="tax_change_yoy", aggfunc="mean")
limit = float(pivot.abs().max().max() or 1)
fig = go.Figure(go.Heatmap(
    z=pivot.values, x=[str(c) for c in pivot.columns], y=list(pivot.index),
    colorscale=[[0.0, t["pos"]], [0.5, t["mid"]], [1.0, t["neg"]]],
    zmid=0, zmin=-limit, zmax=limit,
    xgap=2, ygap=2,
    colorbar=dict(title="Δ tax ($)", tickfont=dict(color=t["text_secondary"])),
    hovertemplate="%{y} · %{x}<br>%{z:$,.2f}<extra></extra>"))
style(fig, t, height=320, legend=False)
fig.update_layout(hovermode="closest")
st.plotly_chart(fig, width="stretch")
st.caption(f"Showing {focus}. The baseline year has no prior year, so it is not plotted.")

# ------------------------------------------------- 8. dual axis
section(8, "Dual axis — shown so you can rule it out", "nothing, really",
        "You asked for this one, so here it is. The two y-scales are chosen by "
        "the renderer, and moving either one changes where the lines appear to "
        "cross — so any 'correlation' you read off it is an artefact of the "
        "scaling, not the data. Chart 2 answers the same question honestly.")

d = years[years.account == focus]
fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Scatter(x=d.tax_year, y=d.appraised_value, name="Appraised value",
                         mode="lines+markers", line=dict(color=t["series"][0], width=2),
                         marker=dict(size=8)), secondary_y=False)
fig.add_trace(go.Scatter(x=d.tax_year, y=d.effective_rate, name="Effective rate",
                         mode="lines+markers", line=dict(color=t["series"][1], width=2),
                         marker=dict(size=8)), secondary_y=True)
fig.update_yaxes(title_text="Appraised value ($)", secondary_y=False,
                 gridcolor=t["grid"], tickfont=dict(color=t["text_secondary"]))
fig.update_yaxes(title_text="Effective rate (per $100)", secondary_y=True,
                 showgrid=False, tickfont=dict(color=t["text_secondary"]))
style(fig, t, height=400)
st.plotly_chart(fig, width="stretch")
