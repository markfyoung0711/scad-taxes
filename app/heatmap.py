"""Where the bill is highest, or rose fastest: a county heat surface.

The surface is a kernel-weighted average of the parcels around each point,
not a count of them -- a density heat map would paint the busiest
neighbourhood hottest whatever its taxes did. Each parcel pulls the color
toward its own value with a weight that falls off with distance, and the
surface fades out where there are no parcels to speak for it.

Color means one thing on this page: red is high, blue is low. The parcel dots
use the same scale as the surface, never the property type.
"""
from __future__ import annotations

import base64
import io
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import shapely
import streamlit as st
from PIL import Image
from shapely.geometry import MultiPoint

import data
from theme import tokens

MEASURES = {
    "Tax bill": ("tax_start", "tax_end"),
    "Market (appraised) value": ("market_start", "market_end"),
    "Assessed value": ("assessed_start", "assessed_end"),
    "Combined tax rate": ("rate_start", "rate_end"),
}
# Low to high, blue to red, through yellow -- the scale of the reference heat
# maps, and one where the middle reads as "middle" rather than as "nothing".
SCALE = [(0.00, (49, 54, 149)), (0.25, (69, 117, 180)), (0.45, (171, 217, 233)),
         (0.60, (254, 224, 144)), (0.80, (244, 109, 67)), (1.00, (165, 0, 38))]
METRES_PER_DEGREE = 111_320
# The smallest change that can be shown at full strength. Color is by rank,
# but when nearly every parcel ties at zero -- one year's rates, before the
# new ones are adopted -- a +0.3% change outranks 98% of the county and would
# be painted the deepest red. Below this size a change gets at most its share.
FULL_COLOR_PCT = 10.0
PIXEL_M = 100
MAX_DOTS = 150_000
# How a region is named, as (label, column). Subdivision first: it is the name
# on the deed and the one people use for where they live. Rural parcels carry
# a survey abstract there instead ("A1079 G WELCH"), which is still a place.
REGION_KEYS = {
    "Subdivision": "subdivision",
    "Appraisal neighborhood": "neighborhood",
    "Voting precinct": "voting_precinct_name",
    "ZIP code": "gis_zip",
    "Street": "street",
}
# Bands on the same rank scale as the map, named for the color they show.
BANDS = [(0.8, "Red"), (0.6, "Orange"), (0.4, "Yellow"), (0.2, "Light blue"),
         (0.0, "Blue")]


def colour(u: np.ndarray) -> np.ndarray:
    """0..1 onto the scale above, as RGB."""
    stops = np.array([s for s, _ in SCALE])
    rgb = np.array([c for _, c in SCALE], dtype=float)
    return np.stack([np.interp(u, stops, rgb[:, i]) for i in range(3)], axis=-1)


def blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian, peak 1, so one parcel alone weighs 1 at its centre."""
    r = max(1, int(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    a = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 0, a)
    return np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 1, a)


@st.cache_data(show_spinner="Painting the surface…")
def surface(lat: np.ndarray, lon: np.ndarray, u: np.ndarray, radius_m: int,
            opacity: float) -> tuple[str, list]:
    """A PNG of the smoothed surface and the corner coordinates to pin it at."""
    lat0 = float(lat.mean())
    dlat = PIXEL_M / METRES_PER_DEGREE
    dlon = dlat / math.cos(math.radians(lat0))
    pad = 3 * radius_m / PIXEL_M
    x0, y0 = lon.min() - pad * dlon, lat.min() - pad * dlat
    w = int((lon.max() - x0) / dlon + pad) + 1
    h = int((lat.max() - y0) / dlat + pad) + 1
    ix = ((lon - x0) / dlon).astype(int)
    iy = ((lat - y0) / dlat).astype(int)

    weight = np.zeros((h, w))
    total = np.zeros((h, w))
    np.add.at(weight, (iy, ix), 1.0)
    np.add.at(total, (iy, ix), u)
    sigma = radius_m / PIXEL_M
    weight, total = blur(weight, sigma), blur(total, sigma)
    mean = np.divide(total, weight, out=np.zeros_like(total), where=weight > 0)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = colour(np.clip(mean, 0, 1)).astype(np.uint8)
    # Fade out only at the edge of the nearest parcel: a lone rural parcel is
    # as much an answer for its spot as a subdivision is for its own.
    rgba[..., 3] = (np.clip(weight / 0.5, 0, 1) * 255 * opacity).astype(np.uint8)
    img = Image.fromarray(rgba[::-1], "RGBA")  # row 0 is the north edge
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    x1, y1 = x0 + w * dlon, y0 + h * dlat
    return ("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
            [[x0, y1], [x1, y1], [x1, y0], [x0, y0]])


def band(u: float) -> str:
    return next(name for floor, name in BANDS if u >= floor)


def street_of(situs: pd.Series) -> pd.Series:
    """'4320 C R 325' -> 'C R 325': the street without the house number."""
    return (situs.fillna("").str.replace(r"^\s*\d+\S*\s+", "", regex=True)
            .str.split().str.join(" ").replace("", None))


def regions(df: pd.DataFrame, key: str, on_scale) -> pd.DataFrame:
    """One row per region: where it is, how many parcels, and its color.

    A region's color is its median placed on the parcel scale, so the number
    in the row is the reason for its color: red only if the median itself
    would be red as a parcel. The median, not the mean, so one parcel that
    went up ninety-fold cannot carry a subdivision into red on its own.
    """
    d = df.dropna(subset=[key]).assign(red=lambda x: x.u >= 0.8)
    g = d.groupby(key)

    def top(col: str, n: int) -> pd.Series:
        """Each region's n commonest values, counted for all regions in one
        pass -- a per-region value_counts is ~20k Python calls at county
        scale and was most of the page's load time."""
        if col == key:  # grouped by street or ZIP: the region is its own answer
            return pd.Series(g.size().index.astype(str), index=g.size().index)
        counts = (d.groupby([key, col]).size().rename("n").reset_index()
                  .sort_values([key, "n"], ascending=[True, False]))
        return (counts.groupby(key).head(n).groupby(key)[col]
                .agg(lambda v: " · ".join(v.astype(str))))

    out = pd.DataFrame({
        "parcels": g.size(),
        "heat": 0.0,
        "share_red": g.red.mean(),
        "median": g.value.median(),
        "p90": g.value.quantile(0.9),
        "max": g.value.max(),
        "streets": top("street", 3),
        "town": top("town", 1),
        "zip": top("gis_zip", 1),
        "lat": g.latitude.median(), "lon": g.longitude.median(),
        "lat_lo": g.latitude.quantile(0.05), "lat_hi": g.latitude.quantile(0.95),
        "lon_lo": g.longitude.quantile(0.05), "lon_hi": g.longitude.quantile(0.95),
    }).reset_index(names="region")
    out["heat"] = on_scale(out["median"].to_numpy())
    out["band"] = out.heat.map(band)
    return (out.sort_values(["heat", "median"], ascending=False)
            .reset_index(drop=True))


def outline(lat: np.ndarray, lon: np.ndarray, pad_m: float = 80
            ) -> list[tuple[list[float], list[float]]]:
    """Rings drawn around a region's parcels, as (lats, lons) per ring.

    A concave hull rather than a convex one, so a subdivision that wraps a
    park or bends along a road is traced along its own shape instead of a
    bounding blob that takes in its neighbours. Worked in metres on a local
    projection, then padded so the line clears the dots at its edge. A region
    whose parcels are far apart -- a ZIP, a long road -- comes out as several
    rings, which is what it is.
    """
    lat0 = float(np.mean(lat))
    kx = METRES_PER_DEGREE * math.cos(math.radians(lat0))
    ky = METRES_PER_DEGREE
    pts = MultiPoint(np.column_stack([lon * kx, lat * ky]))
    shape = (shapely.concave_hull(pts, ratio=0.35)
             .buffer(pad_m).simplify(pad_m / 4))
    polys = getattr(shape, "geoms", [shape])
    return [([y / ky for _, y in p.exterior.coords],
             [x / kx for x, _ in p.exterior.coords]) for p in polys]


def zoom_for(r) -> float:
    """A map zoom that fits the middle 90% of a region's parcels."""
    span = max(r.lon_hi - r.lon_lo, (r.lat_hi - r.lat_lo) * 1.2, 0.002)
    return float(np.clip(math.log2(360 / span) - 1.2, 10, 16))


# ------------------------------------------------------------------ controls
st.title("Smith County tax heat map")
st.caption("Red is high, blue is low. Zoom in on a red area and click a dot "
           "to see that account and its taxes.")

years = data.tax_years()
with st.sidebar:
    st.header("Heat map")
    show = st.radio("Show", ["Change over a range", "Amount in one year"],
                    help="Change is how hard an owner was hit; amount is what "
                         "they pay now.")
    if show == "Change over a range":
        start, end = st.select_slider("Years", years, value=(years[0], years[-1]))
    else:
        end = st.select_slider("Year", years, value=years[-1])
        start = years[0] if end != years[0] else years[1]
    measure = st.radio("Measure", list(MEASURES))
    sectors = st.multiselect("Property type", data.all_sectors(),
                             placeholder="All property types")
    homestead_only = st.toggle(
        "Homesteads only", value=False,
        help="Owner-occupied homes. The district withholds some exemptions "
             "online, so this misses some homesteads rather than adding any.")
    no_new_builds = st.toggle(
        "Exclude new construction", value=True,
        help="Drops parcels with no building at the start of the range. A lot "
             "that gained a house was not hit by a tax increase; it gained a "
             "house.")
    radius = st.select_slider("Smoothing (metres)", [150, 300, 600, 1200, 2400],
                              value=600)
    opacity = st.slider("Surface opacity", 0.2, 1.0, 0.7, 0.05)
    dots = st.toggle("Show parcel dots", value=True)
    mode = st.radio("Theme", ["light", "dark"], horizontal=True)

    st.header("Region report")
    region_by = st.selectbox("Group by", list(REGION_KEYS))
    band_pick = st.multiselect("Colors", [n for _, n in BANDS],
                               default=["Red", "Orange"],
                               placeholder="All colors")
    min_parcels = st.slider("Minimum parcels per region", 1, 50, 10,
                            help="Small regions are one or two owners' "
                                 "stories, not an area's.")

change = show == "Change over a range"
if change and start == end:
    st.info("Pick two different years to measure a change.")
    st.stop()

t = tokens(mode)
df = data.change_between(start, end)
if sectors:
    df = df[df.sector.isin(sectors)]
if homestead_only:
    df = df[df.homestead_shown.fillna(False)]
if no_new_builds and change:
    b0 = pd.to_numeric(df.building_start, errors="coerce").fillna(0)
    b1 = pd.to_numeric(df.building_end, errors="coerce").fillna(0)
    df = df[~((b0 == 0) & (b1 > 0))]

lo_col, hi_col = MEASURES[measure]
v0 = pd.to_numeric(df[lo_col], errors="coerce").astype(float)
v1 = pd.to_numeric(df[hi_col], errors="coerce").astype(float)
if change:
    # A zero start has no change to measure -- an untaxed parcel that
    # acquires a bill is not an infinite rise, it is a different question.
    ok = (v0 > 0) & v1.notna()
    df = df[ok].assign(value=100.0 * (v1[ok] - v0[ok]) / v0[ok])
else:
    ok = v1.notna() & (v1 > 0)
    df = df[ok].assign(value=v1[ok])
df = df.reset_index(drop=True)

if df.empty:
    st.warning("No parcels have this measure with these filters.")
    st.stop()

# The district shows the current year's values before the taxing units adopt
# that year's rates, and repeats last year's rates meanwhile. A rate change
# into such a year is zero by construction, and its tax bill an estimate.
carried = data.rates_carried_over(end)
if carried >= 0.5 and measure in ("Tax bill", "Combined tax rate"):
    st.warning(
        f"**{end} tax rates are mostly not adopted yet.** {carried:.0%} of "
        f"taxing units show the same rate as {end - 1}, which is how the "
        f"district fills the year until rates are set in the fall. So a "
        f"{measure.lower()} ending in {end} uses last year's rates: rate "
        "changes read as zero and bills are estimates.")

# Color by rank, not by raw value. Tax changes run from -60% to +4,800%,
# because a new build or a lapsed exemption multiplies a bill; on a linear
# scale those few would be red and everyone else one shade of blue. By rank,
# red is the top of the county and the colorbar says what that means.
#
# A change keeps its sign and is ranked by size: rises fill the red half,
# cuts the blue half, no change sits in the pale middle, and both halves share
# one size scale. Ranked as one signed list, a rate that fell 2% where most
# fell 22% came out red; ranked on each side alone, a 0.2% rise where every
# other rate fell came out deep red. Red has to mean a large rise.
v = df.value
sizes = np.sort(v.abs().to_numpy())
everything = np.sort(v.to_numpy())


def on_scale(x) -> np.ndarray:
    """Where a value sits on the color scale, 0 (blue) to 1 (red).

    The same function colors a parcel and a region's median, so a region is
    red exactly when its median would be red as a single parcel.
    """
    x = np.asarray(x, dtype=float)
    if not change:
        return np.searchsorted(everything, x, side="right") / len(everything)
    size = np.searchsorted(sizes, np.abs(x), side="right") / len(sizes)
    size = np.minimum(size, np.abs(x) / FULL_COLOR_PCT)
    return 0.5 + 0.5 * np.sign(x) * size


u = on_scale(v)
if change:

    def at(q: float) -> float:
        """The change that lands at position q -- on_scale run backwards."""
        need = abs(q - 0.5) / 0.5
        return float(np.sign(q - 0.5)
                     * max(np.quantile(sizes, need), need * FULL_COLOR_PCT))
    ranks = [0.0, 0.25, 0.5, 0.75, 1.0]
    rank_vals = [at(q) for q in ranks]
    rank_labels = ["largest cut", "typical cut", "no change", "typical rise",
                   "largest rise"]
else:
    ranks = [0.0, 0.25, 0.5, 0.75, 1.0]
    rank_vals = [float(x) for x in v.quantile(ranks)]
    rank_labels = ["lowest", "25th", "median", "75th", "highest"]
lo, hi = 0.0, 1.0
df["u"] = u
df["street"] = street_of(df.situs_address)
df["town"] = df.gis_city.str.title()
df["subdivision"] = df.subdivision.str.replace(r"^\S+\s+-\s+", "", regex=True)

# The report is drawn under the map, but a region picked in it moves the map,
# so the table is computed first and its selection read from the last run.
region_col = REGION_KEYS[region_by]
# Every region with its row, whatever the color filter and minimum, so a
# parcel picked on the map can always be traced to its region's numbers; the
# report is that list filtered.
every_region = regions(df, region_col, on_scale)
report = every_region[every_region.parcels >= min_parcels]
if band_pick:
    report = report[report.band.isin(band_pick)]
report = report.reset_index(drop=True)
every_region = every_region.set_index("region")


def selected(key: str) -> dict:
    return ((st.session_state.get(key) or {}).get("selection") or {})


# Parcels clicked or lassoed on the map last run: their regions are pinned in
# the report and outlined, which is how a spot on the map is found in it.
picked = [p["customdata"][0] for p in selected("heat").get("points", [])
          if p.get("customdata")]
picked_regions = (df[df.account.isin(picked)][region_col]
                  .value_counts() if picked else pd.Series(dtype=int))
pins = [r for r in picked_regions.index if r in every_region.index]
if pins:
    # Pinned to the top even when the color filter or minimum would have
    # left them out.
    report = pd.concat([every_region.loc[pins].reset_index(names="region"),
                        report[~report.region.isin(pins)]], ignore_index=True)

# A new map selection reorders the report under any row already picked in it,
# so that row would now point at a different region: drop it instead.
if st.session_state.get("_last_picked") != picked:
    st.session_state["_last_picked"] = picked
    st.session_state.pop("region_table", None)
rows = selected("region_table").get("rows", [])
focus = report.iloc[rows[0]] if rows and rows[0] < len(report) else None

png, corners = surface(df.latitude.to_numpy(), df.longitude.to_numpy(), u,
                       radius, opacity)

money = measure != "Combined tax rate"
if change:
    unit, fmt, title = "%", "+.1f", f"{measure}<br>% change<br>{start}→{end}"
else:
    unit, fmt, title = "", ("$,.0f" if money else ".4f"), f"{measure}<br>{end}"
tick = (lambda v: f"{v:+.1f}%" if abs(v) < 10 else f"{v:+.0f}%") if change else (
    (lambda v: f"${v:,.0f}") if money else (lambda v: f"{v:.2f}"))
# Shorter than the plot and centred, so its title clears the toolbar that
# Plotly pins to the top-right corner.
colorbar = dict(title=title, tickfont=dict(color=t["text_secondary"]),
                len=0.8, y=0.45, yanchor="middle",
                tickvals=ranks,
                ticktext=[f"{tick(x)} ({lab})" for x, lab in
                          zip(rank_vals, rank_labels)])

# ----------------------------------------------------------------------- map
fig = go.Figure()
plotly_scale = [[s, f"rgb{c}"] for s, c in SCALE]
if dots:
    shown = df.head(MAX_DOTS)
    # Every dot is resent on every rerun, so each carries as little as it can:
    # 32-bit coordinates (about a metre) and color, and no street address --
    # that is one click away in the detail below. At county scale this halves
    # what a click costs to redraw.
    fig.add_trace(go.Scattermap(
        lat=shown.latitude.to_numpy(np.float32),
        lon=shown.longitude.to_numpy(np.float32),
        mode="markers",
        marker=dict(size=6, color=u[:len(shown)].astype(np.float32), cmin=lo, cmax=hi,
                    colorscale=plotly_scale, opacity=0.9, colorbar=colorbar),
        customdata=np.stack([shown.account, shown.value.round(1),
                             shown[region_col].fillna("(none)")], axis=-1),
        hovertemplate=("%{customdata[0]} · "
                       f"%{{customdata[1]:{fmt}}}{unit}<br>"
                       f"{region_by}: <b>%{{customdata[2]}}</b>"
                       "<extra></extra>")))
else:
    # The colorbar has to hang off a trace; an invisible one carries it.
    fig.add_trace(go.Scattermap(
        lat=[None], lon=[None], mode="markers", hoverinfo="skip",
        marker=dict(color=[lo], cmin=lo, cmax=hi, colorscale=plotly_scale,
                    colorbar=colorbar)))

# A row picked in the report wins; otherwise the regions under the parcels
# picked on the map. Capped, since a lasso across town can touch dozens.
outlined = ([focus.region] if focus is not None
            else list(picked_regions.index[:10]))
for name in outlined:
    # Drawn last, so it sits above the dots: a white casing under a black
    # line reads on the red surface and on the dark basemap alike, and the
    # faint tint says which side of the line is the region.
    inside = df[df[region_col] == name]
    for ring_lat, ring_lon in outline(inside.latitude.to_numpy(),
                                      inside.longitude.to_numpy()):
        fig.add_trace(go.Scattermap(
            lat=ring_lat, lon=ring_lon, mode="lines", hoverinfo="skip",
            fill="toself", fillcolor="rgba(0,0,0,0.10)",
            line=dict(width=8, color="rgba(255,255,255,0.9)")))
        fig.add_trace(go.Scattermap(
            lat=ring_lat, lon=ring_lon, mode="lines", hoverinfo="skip",
            line=dict(width=3.5, color="#000")))

fig.update_layout(
    map=dict(style="carto-darkmatter" if mode == "dark" else "carto-positron",
             center=(dict(lat=float(focus.lat), lon=float(focus.lon))
                     if focus is not None else
                     dict(lat=float(df.latitude.mean()),
                          lon=float(df.longitude.mean()))),
             zoom=zoom_for(focus) if focus is not None else 9.5,
             layers=[dict(sourcetype="image", source=png, coordinates=corners,
                          below="traces")],
             # Keep the reader's own pan and zoom across reruns -- a click on
             # a dot must not throw them back out to the whole county. Only a
             # region picked in the report moves the view.
             uirevision=focus.region if focus is not None else "free"),
    uirevision=focus.region if focus is not None else "free",
    # The top margin is the toolbar's own strip, above the map rather than
    # over it.
    height=720, margin=dict(l=0, r=0, t=34, b=0), showlegend=False,
    paper_bgcolor=t["surface"], font=dict(color=t["text_primary"]),
    clickmode="event+select")
event = st.plotly_chart(fig, width="stretch", key="heat", on_select="rerun",
                        selection_mode=("points", "box", "lasso"))

MEDIAN = "Median change" if change else f"Median {end}"
VALUE_COLUMNS = [MEDIAN, "Top 10% ≥", "Max"]
BAND_RGB = {name: f"rgb{tuple(int(c) for c in colour(np.array([floor + 0.1]))[0])}"
            for floor, name in BANDS}


def styled_table(table: pd.DataFrame):
    """Swatch the Color column, and format values for display only.

    The numbers stay numbers underneath: formatted as text, "+60%" sorted
    between "+7.9%" and "+4.0%" when a column header was clicked.
    """
    return (table.style
            .apply(lambda col: [f"background-color: {BAND_RGB[v]}; color: "
                                f"{'#fff' if v in ('Red', 'Blue') else '#111'}"
                                for v in col], subset=["Color"])
            .format(tick, subset=[c for c in VALUE_COLUMNS if c in table]))


if picked:
    here = every_region.loc[[r for r in picked_regions.index
                             if r in every_region.index]]
    st.markdown(f"**{len(picked)} parcel(s) picked, in {len(here)} "
                f"{region_by.lower()} region(s)** — outlined on the map and "
                "pinned 📍 at the top of the report below.")
    st.dataframe(styled_table(pd.DataFrame({
        "Color": here.band, "Region": here.index,
        "Picked": picked_regions.reindex(here.index).to_numpy(),
        "Parcels": here.parcels, "Streets": here.streets,
        MEDIAN: here["median"],
        "Rank": (100 * here.heat).round().astype(int)})),
        width="stretch", hide_index=True)
else:
    st.caption(f"Hover a dot to see its {region_by.lower()}; click it, or "
               "lasso an area with the toolbar, to find its region in the "
               "report.")

c1, c2, c3 = st.columns(3)
c1.metric("Parcels", f"{len(df):,}")
c2.metric(f"Median {measure.lower()}" + (" change" if change else f", {end}"),
          f"{df.value.median():+.1f}%" if change else tick(df.value.median()))
top = float(df.value.quantile(0.9))
c3.metric("Top 10%", f"≥ {tick(top)}",
          help="Red is a rise and blue a cut, shaded by size against every "
               "change in the county; the deepest red is the largest rises.")

caption = (f"{start}→{end}, parcels with a {measure.lower()} in both years. "
           if change else f"{end}, parcels with a {measure.lower()} that year. ")
st.caption(
    caption + "The tax bill moves with both the appraisal and the rate; the "
    "combined rate is the sum of the published jurisdiction rates, before "
    "exemptions." + (f" Dots are capped at {MAX_DOTS:,}." if len(df) > MAX_DOTS
                     else ""))

# -------------------------------------------------------------------- report
st.divider()
colors = ", ".join(band_pick).lower() if band_pick else "every color"
st.subheader(f"Regions by {region_by.lower()}")
st.caption(f"{len(report):,} regions shown in {colors}, hottest first. A "
           "region's color is where its median falls on the map's scale — red "
           "only if the median itself is a red number. Click a row to zoom the "
           "map to it.")

if report.empty:
    st.info("No region matches — widen the colors or lower the minimum.")
else:
    table = pd.DataFrame({
        "Color": report.band,
        "Region": [("📍 " if r in pins else "") + str(r) for r in report.region],
        "Streets": report.streets,
        "Town": report.town.fillna("") + " " + report.zip.fillna(""),
        "Parcels": report.parcels,
        MEDIAN: report["median"],
        "Top 10% ≥": report.p90,
        "Max": report["max"],
        "Rank": (100 * report.heat).round().astype(int),
        "Red parcels": (100 * report.share_red).round().astype(int),
    })
    st.dataframe(
        styled_table(table), width="stretch", hide_index=True, key="region_table",
        on_select="rerun", selection_mode="single-row",
        column_config={
            "Top 10% ≥": st.column_config.NumberColumn(
                help="The region's 90th percentile: what its hardest-hit "
                     "tenth of parcels saw."),
            "Rank": st.column_config.ProgressColumn(
                "Rank", help="Where the region's median sits on the color "
                             "scale: above 50 is a rise, below a cut, 100 the "
                             "largest rises in the county.",
                min_value=0, max_value=100, format="%d"),
            "Red parcels": st.column_config.NumberColumn(
                "Red parcels", help="Share of the region's parcels in the red "
                                    "band on the map.",
                format="%d%%")})
    st.download_button(
        "Download report (CSV)",
        table.round(2).to_csv(index=False).encode(),
        file_name=f"regions-{region_by.lower().replace(' ', '-')}-"
                  f"{measure.lower().replace(' ', '-')}-{start}-{end}.csv",
        mime="text/csv")
    if focus is not None:
        st.caption(f"Map zoomed to **{focus.region}** ({focus.parcels} parcels, "
                   f"{focus.band.lower()}). Clear the row to zoom back out.")

# -------------------------------------------------------------------- detail
points = (event.selection.get("points") if event and event.selection else []) or []
picked = [p["customdata"][0] for p in points if p.get("customdata")]
if not picked:
    st.stop()

st.divider()
for acct in picked[:5]:
    meta = data.accounts_for((acct,))
    if meta.empty:
        continue
    row = meta.iloc[0]
    st.markdown(f"#### {acct} · {row.owner_name}")
    st.caption(f"{row.situs_address or '(no situs)'} · {row.sector} · "
               f"{row.use_code} · [parcel page]({data.parcel_url(row.gis_parcel_id)})")
    hist = data.by_year((acct,)).sort_values("tax_year")
    left, right = st.columns(2)
    with left:
        st.dataframe(
            hist[["tax_year", "market_value", "assessed_value", "total_tax",
                  "market_pct_yoy", "tax_pct_yoy"]],
            width="stretch", hide_index=True, column_config={
                "tax_year": st.column_config.NumberColumn("Year", format="%d"),
                "market_value": st.column_config.NumberColumn("Market", format="$%,.0f"),
                "assessed_value": st.column_config.NumberColumn("Assessed", format="$%,.0f"),
                "total_tax": st.column_config.NumberColumn("Tax", format="$%,.2f"),
                "market_pct_yoy": st.column_config.NumberColumn("Market YoY", format="%+.1f%%"),
                "tax_pct_yoy": st.column_config.NumberColumn("Tax YoY", format="%+.1f%%")})
    with right:
        jur = data.by_jurisdiction((acct,))
        st.dataframe(
            jur[["tax_year", "jurisdiction", "taxable_value", "tax_rate",
                 "tax_amount"]].sort_values(["tax_year", "jurisdiction"],
                                            ascending=[False, True]),
            width="stretch", hide_index=True, column_config={
                "tax_year": st.column_config.NumberColumn("Year", format="%d"),
                "jurisdiction": "Jurisdiction",
                "taxable_value": st.column_config.NumberColumn("Taxable", format="$%,.0f"),
                "tax_rate": st.column_config.NumberColumn("Rate", format="%.6f"),
                "tax_amount": st.column_config.NumberColumn("Tax", format="$%,.2f")})
if len(picked) > 5:
    st.caption(f"Showing 5 of {len(picked)} selected parcels.")
