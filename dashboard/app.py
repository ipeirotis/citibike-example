"""Citibike × Weather — a Streamlit dashboard on the effect of NYC weather on
Citibike ridership, 2013 → present.

Data source: the BigQuery view `nyu-datasets.citibike.daily_trips_weather`
(one row per day: ridership aggregates from `m_daily_trips` joined to NYC daily
weather in `nyu-datasets.weather.m_weather_daily_nyc`). The view is tiny
(~4.7k rows), so the whole thing is pulled once and filtered client-side.

Auth is via Application Default Credentials: on Cloud Run that is the service
account the service runs as; locally it is `gcloud auth application-default
login` or $GOOGLE_APPLICATION_CREDENTIALS.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.cloud import bigquery

import attribution

PROJECT = os.environ.get("BQ_PROJECT", "nyu-datasets")
SOURCE = os.environ.get("DASHBOARD_SOURCE", "nyu-datasets.citibike.daily_trips_weather")

st.set_page_config(page_title="Citibike × Weather", page_icon="🚲", layout="wide")

# Consistent, colour-blind-friendly palette for the recurring categories.
SEASON_COLORS = {"Winter": "#4C78A8", "Spring": "#54A24B", "Summer": "#E45756", "Fall": "#F58518"}
COND_COLORS = {"Dry": "#54A24B", "Rainy": "#4C78A8", "Snowy": "#B279A2"}
# Diverging colours for the "% vs. normal" impact bars (below / above the norm).
NEG_COLOR, POS_COLOR = "#C44E52", "#55A868"
# Per-factor colours for the regression "isolated impact" chart.
IMPACT_COLORS = {
    "Temperature (vs 55–65°F)": "#E45756",
    "Rain (vs dry)": "#4C78A8",
    "Snow": "#72B7B2",
    "Wind": "#54A24B",
    "Storms (vs same rain/temp)": "#B279A2",
    "Humidity (warm days, 2016–24)": "#F58518",
}


# --------------------------------------------------------------------------- data
@st.cache_data(ttl=3600, show_spinner="Querying BigQuery…")
def load_data() -> pd.DataFrame:
    """Pull the daily trips-and-weather view and add a few derived columns."""
    client = bigquery.Client(project=PROJECT)
    df = client.query(f"SELECT * FROM `{SOURCE}` ORDER BY date").to_dataframe()

    df["date"] = pd.to_datetime(df["date"])
    # Calendar fields straight from the date so they are never NULL (the weather
    # feed lags trips by a couple of weeks, leaving its year/is_weekend NULL there).
    df["year"] = df["date"].dt.year
    df["is_weekend"] = (df["date"].dt.dayofweek >= 5).astype(int)
    # Categorical weather condition (snow takes precedence over rain). A NULL
    # is_rainy means precipitation was *not reported* — leave those days
    # unlabeled rather than letting them masquerade as measured-dry days.
    # BigQuery returns nullable Int64 columns, so build NA-safe plain-bool
    # masks first (np.where chokes on masks containing pd.NA).
    snowy = df["is_snowy"].eq(1).fillna(False).to_numpy(bool)
    rainy = df["is_rainy"].eq(1).fillna(False).to_numpy(bool)
    dry = df["is_rainy"].eq(0).fillna(False).to_numpy(bool)
    df["condition"] = np.where(snowy, "Snowy",
                      np.where(rainy, "Rainy",
                      np.where(dry, "Dry", None)))
    return df


df = load_data()


HOURLY_SOURCE = os.environ.get("DASHBOARD_HOURLY_SOURCE",
                               "nyu-datasets.citibike.hourly_trips_weather")


@st.cache_data(ttl=3600, show_spinner="Querying hourly data…")
def load_hourly() -> pd.DataFrame:
    """Pull the hourly trips-and-weather view (one row per local clock hour).

    Only the columns the Hourly tab needs, to keep the pull lean (~114k rows).
    Hours with zero trips have no row in the mart — the tab zero-fills the
    (date x 24h) grid before averaging, so overnight averages stay honest.
    """
    client = bigquery.Client(project=PROJECT)
    cols = ("date, hour, num_trips, num_member_trips, num_casual_trips,"
            " num_member_trips_nyc, num_casual_trips_nyc, num_member_trips_jc,"
            " num_casual_trips_jc, num_nyc_trips, num_jc_trips,"
            " temp_f, prcp_inches, is_raining, is_snowing")
    h = client.query(f"SELECT {cols} FROM `{HOURLY_SOURCE}`").to_dataframe()
    h["date"] = pd.to_datetime(h["date"])
    for c in h.columns.drop(["date"]):  # nullable Int64 -> plain floats for the math
        h[c] = pd.to_numeric(h[c], errors="coerce").astype("float64")
    h["hour"] = h["hour"].astype("int64")  # join/grid key, must match range(24)
    return h


@st.cache_data(ttl=3600, show_spinner="Fitting weather-impact model…")
def weather_impacts(trips_col: str):
    """Partial weather effects for a region (cached). See attribution.py.

    Fit over the region's full history — independent of the year/weekday filters —
    so the model stays well-identified; `trips_col` is the only thing that varies it.
    """
    return attribution.fit_impacts(df, trips_col)


@st.cache_data(ttl=3600, show_spinner="Fitting weather-adjustment model…")
def weather_adjusted(trips_col: str):
    """Per-day actual / expected / weather-adjusted trips for a region (cached)."""
    return attribution.weather_adjusted_daily(df, trips_col)


# --------------------------------------------------------------------------- sidebar
st.sidebar.title("🚲 Citibike × Weather")
st.sidebar.caption("NYC daily ridership vs. daily weather, 2013 → present.")

yr_min, yr_max = int(df["year"].min()), int(df["year"].max())
yr_lo, yr_hi = st.sidebar.slider("Year range", yr_min, yr_max, (yr_min, yr_max))

region = st.sidebar.radio(
    "Region",
    ["NYC + Jersey City", "NYC only", "Jersey City only"],
    help="Weather is measured in NYC; for the cleanest weather signal use 'NYC only'.",
)
TRIPS_COL = {
    "NYC + Jersey City": "num_trips",
    "NYC only": "num_nyc_trips",
    "Jersey City only": "num_jc_trips",
}[region]
# Member/casual counts for the active region, so the Riders tab honors the filter.
MEMBER_COL = {
    "NYC + Jersey City": "num_member_trips",
    "NYC only": "num_member_trips_nyc",
    "Jersey City only": "num_member_trips_jc",
}[region]
CASUAL_COL = {
    "NYC + Jersey City": "num_casual_trips",
    "NYC only": "num_casual_trips_nyc",
    "Jersey City only": "num_casual_trips_jc",
}[region]

show_weekends = st.sidebar.radio("Days", ["All days", "Weekdays only", "Weekends only"])

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Sources:** `nyu-datasets.citibike.daily_trips_weather`\n\n"
    "Daily trips (`m_daily_trips`) ⨝ NYC daily weather "
    "(`weather.m_weather_daily_nyc`); the 🕐 Hourly tab reads "
    "`hourly_trips_weather` (`m_hourly_trips` ⨝ hourly Central Park "
    "weather, `weather.m_weather_hourly_nyc`)."
)

# Apply filters → a working frame. `trips` is the active region's count.
mask = (df["year"] >= yr_lo) & (df["year"] <= yr_hi)
if show_weekends == "Weekdays only":
    mask &= df["is_weekend"] == 0
elif show_weekends == "Weekends only":
    mask &= df["is_weekend"] == 1
# Restrict each region slice to its active span — Jersey City data starts in 2015,
# so otherwise its pre-launch days would enter as fake zero-trip observations.
launch = df.loc[df[TRIPS_COL] > 0, "date"].min()
mask &= df["date"] >= launch
d = df.loc[mask].copy()
if d.empty:
    st.title("How weather moves Citibike ridership")
    st.info(f"No {region} data in {yr_lo}–{yr_hi}. Jersey City data begins in 2015 — widen the year range.")
    st.stop()
d["trips"] = d[TRIPS_COL]
d["member"] = d[MEMBER_COL]
d["casual"] = d[CASUAL_COL]
# Casual share of the active region's trips (the most weather-sensitive segment).
d["pct_casual"] = np.where(d["trips"] > 0, d["casual"] / d["trips"] * 100, np.nan)

# Detrended "ridership index" — a day's trips as a percent of the surrounding
# ~month's typical trips (centered 29-day median of the active region's daily
# series). Computed over the region's full daily history (not the weekday/weekend
# slice) so it stays stable under the filters. It nets out the long-term growth
# trend and the seasonal level, which is what lets the Wind / Humidity / Conditions
# views isolate a weather effect even though wind, humidity and storms are themselves
# tied to the seasons. Weather is independent of the day of week, so that structure
# averages out and does not bias the comparison.
_region_daily = (df.loc[df["date"] >= launch]
                   .set_index("date")[TRIPS_COL].astype(float).sort_index())
_baseline = _region_daily.rolling(29, center=True, min_periods=10).median()
_ridx = (_region_daily / _baseline) * 100.0
d["ridership_index"] = d["date"].map(_ridx)

dw = d.dropna(subset=["tavg_f"])  # rows that actually have weather

# --------------------------------------------------------------------------- header
st.title("How weather moves Citibike ridership")
st.markdown(
    f"**{region}** · **{yr_lo}–{yr_hi}** · **{show_weekends.lower()}**. "
    "Citibike trips rise and fall with temperature, rain, and snow — explore the "
    "relationship across the full history below."
)

k = st.columns(4)
k[0].metric("Total trips", f"{d['trips'].sum()/1e6:,.1f} M")
k[1].metric("Days covered", f"{len(d):,}")
k[2].metric("Avg trips / day", f"{d['trips'].mean():,.0f}")
if len(dw):
    warm = dw[dw["tavg_f"] >= 65]["trips"].mean()
    cold = dw[dw["tavg_f"] < 40]["trips"].mean()
    ratio = warm / cold if cold else np.nan
    k[3].metric("Warm vs. cold day", f"{ratio:,.1f}×" if np.isfinite(ratio) else "—",
                help="Avg trips on warm days (≥65°F) ÷ cold days (<40°F).")

(tab_overview, tab_hourly, tab_impact, tab_perf, tab_temp, tab_precip, tab_wind,
 tab_humid, tab_riders, tab_seasonal) = st.tabs(
    ["📈 Overview", "🕐 Hourly", "🎯 Impact", "📊 Performance", "🌡️ Temperature",
     "🌧️ Rain & Snow", "🌬️ Wind", "💧 Humidity", "🧍 Riders", "🗓️ Seasonality"]
)

# --------------------------------------------------------------------------- overview
with tab_overview:
    st.subheader("Daily ridership and temperature move together")
    roll = d.set_index("date").sort_index()
    roll["trips_30d"] = roll["trips"].rolling("30D", min_periods=7).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=roll.index, y=roll["trips"], name="Daily trips",
                             line=dict(color="#C7D9F0", width=1), opacity=0.6))
    fig.add_trace(go.Scatter(x=roll.index, y=roll["trips_30d"], name="30-day average",
                             line=dict(color="#1F4E96", width=2.5)))
    if "tavg_f" in roll:
        fig.add_trace(go.Scatter(x=roll.index, y=roll["tavg_f"], name="Avg temp (°F)",
                                 line=dict(color="#E45756", width=1), opacity=0.5, yaxis="y2"))
    fig.update_layout(
        height=460, hovermode="x unified",
        yaxis=dict(title="Trips / day"),
        yaxis2=dict(title="Avg temp (°F)", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=10, b=0, l=0, r=0),
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Ridership grows year over year (network expansion) while oscillating with "
        "the seasons — peaks in summer, troughs in winter — tracking the temperature "
        "curve on the right axis."
    )

# --------------------------------------------------------------------------- hourly
with tab_hourly:
    st.subheader("The day's rhythm — and what weather does to it, hour by hour")
    st.markdown(
        "One row per **local clock hour** (`hourly_trips_weather`), joined to the hourly "
        "Central Park record so rain can be matched to the very hour it fell. "
        "*(Weekdays and weekends are shown side by side; the Days filter doesn't apply here.)*"
    )
    hh = load_hourly()
    hh = hh[(hh["date"].dt.year >= yr_lo) & (hh["date"].dt.year <= yr_hi)
            & (hh["date"] >= launch)].copy()
    if hh.empty:
        st.info("No hourly data in this selection.")
    else:
        hh["trips"] = hh[TRIPS_COL]
        hh["member"] = hh[MEMBER_COL]
        hh["casual"] = hh[CASUAL_COL]
        # Zero-fill the (date x 24h) grid: an hour with no trips has no row in
        # the mart, and dropping those would overstate the overnight averages.
        grid = pd.MultiIndex.from_product(
            [pd.date_range(hh["date"].min(), hh["date"].max(), freq="D"), range(24)],
            names=["date", "hour"])
        counts = (hh.set_index(["date", "hour"])[["trips", "member", "casual"]]
                    .reindex(grid, fill_value=0.0).reset_index())
        counts["is_weekend"] = counts["date"].dt.dayofweek >= 5

        c1, c2 = st.columns(2)
        with c1:
            prof = (counts.assign(day_type=np.where(counts["is_weekend"], "Weekend", "Weekday"))
                          .groupby(["day_type", "hour"], as_index=False)["trips"].mean())
            fig = px.line(prof, x="hour", y="trips", color="day_type", markers=True,
                          color_discrete_map={"Weekday": "#1F4E96", "Weekend": "#E45756"},
                          labels={"hour": "Hour of day", "trips": "Avg trips / hour", "day_type": ""})
            fig.update_layout(height=400, legend=dict(orientation="h", y=1.02, x=0),
                              margin=dict(t=10, b=0, l=0, r=0), xaxis=dict(dtick=2))
            st.plotly_chart(fig, width="stretch")
            st.caption(
                "Weekdays carry the commute signature — twin peaks at 8 am and 5–6 pm — "
                "while weekends build to a single mid-afternoon hump."
            )
        with c2:
            mc = (counts[~counts["is_weekend"]].groupby("hour")[["member", "casual"]].mean()
                        .reset_index().melt("hour", var_name="rider", value_name="trips"))
            mc["rider"] = mc["rider"].map({"member": "Member", "casual": "Casual"})
            fig = px.line(mc, x="hour", y="trips", color="rider", markers=True,
                          color_discrete_map={"Member": "#4C78A8", "Casual": "#E45756"},
                          labels={"hour": "Hour of day (weekdays)", "trips": "Avg trips / hour", "rider": ""})
            fig.update_layout(height=400, legend=dict(orientation="h", y=1.02, x=0),
                              margin=dict(t=10, b=0, l=0, r=0), xaxis=dict(dtick=2))
            st.plotly_chart(fig, width="stretch")
            st.caption(
                "The twin peaks belong to members (commuters); casual riders build to a "
                "single afternoon crest — two different products sharing one fleet."
            )

        st.markdown("##### Rain at the hour it falls")
        rain = (counts.merge(hh[["date", "hour", "is_raining"]], on=["date", "hour"], how="left")
                      .dropna(subset=["is_raining"]))
        rain["month"] = rain["date"].dt.month
        cell = (rain.groupby(["month", "is_weekend", "hour", "is_raining"])["trips"].mean()
                    .unstack("is_raining").rename(columns={0.0: "dry", 1.0: "wet"}).dropna())
        if {"dry", "wet"} <= set(cell.columns) and len(cell):
            n_wet = (rain[rain["is_raining"] == 1.0]
                     .groupby(["month", "is_weekend", "hour"]).size()
                     .reindex(cell.index).fillna(0.0))
            cell["pct"] = (cell["wet"] / cell["dry"] - 1) * 100
            hr_eff = (cell["pct"].mul(n_wet).groupby(level="hour").sum()
                      / n_wet.groupby(level="hour").sum()).reset_index(name="pct")
            fig = px.bar(hr_eff, x="hour", y="pct", color="pct",
                         color_continuous_scale="RdYlGn", range_color=[-60, 0], text_auto=".0f",
                         labels={"hour": "Hour of day", "pct": "Trips when raining vs dry (%)"})
            fig.update_layout(height=360, coloraxis_showscale=False,
                              margin=dict(t=10, b=0, l=0, r=0), xaxis=dict(dtick=2))
            st.plotly_chart(fig, width="stretch")
            st.caption(
                "Each bar compares hours when rain was falling against dry hours of the **same "
                "hour-of-day, month and day-type** — roughly a 40–50% haircut whenever it rains, "
                "deepest in the evening and overnight leisure hours and shallowest in the morning "
                "commute, where riders are already committed to getting to work. (Marginal "
                "comparison; the 🎯 Impact tab isolates factors at the daily grain.)"
            )
        else:
            st.info("Not enough rainy-hour coverage in this selection.")

        st.markdown("##### Temperature and the shape of the day")
        heat = (counts.merge(hh[["date", "hour", "temp_f"]], on=["date", "hour"], how="left")
                      .dropna(subset=["temp_f"]))
        if len(heat):
            heat["band"] = pd.cut(heat["temp_f"], [-100, 32, 45, 55, 65, 75, 85, 200],
                                  labels=["<32°F", "32–45", "45–55", "55–65", "65–75", "75–85", "85°F+"])
            cellh = heat.groupby(["band", "hour"], observed=True)["trips"].mean()
            hour_avg = heat.groupby("hour")["trips"].mean()
            idx = (cellh / hour_avg * 100).unstack("hour")
            fig = px.imshow(idx, aspect="auto", color_continuous_scale="RdYlGn",
                            color_continuous_midpoint=100, zmin=0, zmax=200,
                            labels=dict(x="Hour of day", y="Temperature that hour", color="vs hour's norm (%)"))
            fig.update_layout(height=420, margin=dict(t=10, b=0, l=0, r=0), xaxis=dict(dtick=2))
            st.plotly_chart(fig, width="stretch")
            st.caption(
                "Each cell: ridership in that hour at that temperature, as a percent of the hour's "
                "all-weather norm. Mild-to-warm hours (55–85°F) run above norm around the clock; "
                "the hottest hours (85°F+) stay strong in the evening but flatten at midday — "
                "the one part of the day where more heat stops helping. (Temperature bands ride "
                "with the seasons, so this is a descriptive view — not the isolated effect.)"
            )

# --------------------------------------------------------------------------- impact
with tab_impact:
    st.subheader("The isolated effect of each weather factor")
    st.markdown(
        "The other tabs compare a day with its surrounding month — honest about growth and "
        "seasonality, but still **bundling correlated weather** (windy days are also cold, "
        "storm days are also wet). Here a single regression separates them: each bar is the "
        "change in daily ridership from that factor *alone*, holding the month, day-of-week, "
        "holidays and every other weather variable constant."
    )
    try:
        eff, meta = weather_impacts(TRIPS_COL)
    except Exception as exc:  # a singular design / thin slice shouldn't crash the app
        st.warning(f"Could not fit the impact model for this selection ({exc}).")
        eff = None
    if eff is not None and not eff.empty:
        eff = eff.sort_values("pct")
        eff["err_plus"] = eff["hi"] - eff["pct"]
        eff["err_minus"] = eff["pct"] - eff["lo"]
        fig = px.bar(
            eff, x="pct", y="label", orientation="h", color="group",
            color_discrete_map=IMPACT_COLORS, error_x="err_plus", error_x_minus="err_minus",
            category_orders={"label": eff["label"].tolist()},
            labels={"pct": "Isolated effect on daily ridership (%)", "label": "", "group": ""},
        )
        fig.add_vline(x=0, line_color="#444")
        fig.update_layout(height=560, legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                          margin=dict(t=10, b=0, l=0, r=10))
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "95% confidence whiskers (Newey–West SEs, which account for day-to-day "
            f"autocorrelation). Calendar controls — trend, season and weekday — already "
            f"explain {meta['r2_controls']:.0%} of ridership; weather then explains "
            f"{meta['weather_partial_r2']:.0%} of what remains. Fit over the full "
            f"{region.replace(' only', '')} history ({meta['n']:,} days); humidity is "
            "Central Park 2016–2024 only."
        )
        st.info(
            "**Why this differs from the raw tabs.** Windy days read ~−22% there, but their "
            "isolated effect is about half that — the rest is the cold that travels with wind. "
            "Thunderstorms read −10% yet come out **positive** here: once the rain they bring "
            "is accounted for, what's left are busy warm afternoons. Snow and heavy rain, "
            "conversely, come out *stronger* once isolated — a multi-day storm drags down its "
            "own monthly baseline, so the simple comparison understates it."
        )

# --------------------------------------------------------------------------- performance
with tab_perf:
    st.subheader("Weather-adjusted ridership — performance net of the weather")
    st.markdown(
        "Raw ridership mixes real demand with the luck of the weather. This view models the "
        "trips you'd **expect for each day's weather and the time of year**, then strips the "
        "weather out — so growth and period-to-period comparisons are apples-to-apples. "
        "*(Uses all days; the weekday/weekend filter doesn't apply here.)*"
    )
    try:
        adj = weather_adjusted(TRIPS_COL)
    except Exception as exc:  # a thin slice / singular design shouldn't crash the app
        st.warning(f"Could not fit the weather-adjustment model ({exc}).")
        adj = None
    if adj is not None:
        perf = adj.merge(df[["date", "year"]], on="date", how="inner")
        perf = perf[(perf["year"] >= yr_lo) & (perf["year"] <= yr_hi) & (perf["date"] >= launch)]
        if perf.empty:
            st.info("No weather-covered days in this selection.")
        else:
            act, adjt = perf["actual"].sum(), perf["adjusted"].sum()
            wpct = (act / adjt - 1) * 100
            kc = st.columns(3)
            kc[0].metric("Actual trips", f"{act/1e6:,.1f} M")
            kc[1].metric("Weather-adjusted", f"{adjt/1e6:,.1f} M",
                         help="Trips you'd expect for these dates under normal (seasonal-average) weather.")
            kc[2].metric("Weather impact", f"{wpct:+.1f}%",
                         help="How much the period's weather lifted (+) or dragged (−) ridership vs. the seasonal norm.")

            roll = perf.set_index("date").sort_index()
            roll["actual_28"] = roll["actual"].rolling("28D", min_periods=7).mean()
            roll["adjusted_28"] = roll["adjusted"].rolling("28D", min_periods=7).mean()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=roll.index, y=roll["actual_28"], name="Actual",
                                     line=dict(color="#9ECAE1", width=1.5)))
            fig.add_trace(go.Scatter(x=roll.index, y=roll["adjusted_28"], name="Weather-adjusted",
                                     line=dict(color="#1F4E96", width=2.5)))
            fig.update_layout(height=380, hovermode="x unified", yaxis_title="Trips / day (28-day avg)",
                              legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                              margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig, width="stretch")
            st.caption(
                "The dark line is ridership with the weather removed (what you'd see under normal "
                "weather). Where actual dips below it, weather was holding rides back; above, "
                "weather was a tailwind."
            )

            # near-complete years only, so annual totals are comparable
            yr = (perf.assign(n=1).groupby("year")
                      .agg(actual=("actual", "sum"), adjusted=("adjusted", "sum"), n=("n", "sum")))
            yr = yr[yr["n"] >= 300]
            yr["weather_pct"] = (yr["actual"] / yr["adjusted"] - 1) * 100
            if len(yr) >= 2:
                prev, last = yr.iloc[-2], yr.iloc[-1]
                raw_g = (last["actual"] / prev["actual"] - 1) * 100
                adj_g = (last["adjusted"] / prev["adjusted"] - 1) * 100
                tail = (f" — {adj_g - raw_g:+.1f} pts of that swing was weather, not demand."
                        if abs(adj_g - raw_g) >= 0.5 else ".")
                st.markdown(
                    f"**Underlying growth {int(yr.index[-2])} → {int(yr.index[-1])}:** ridership moved "
                    f"**{raw_g:+.1f}%** on paper, but **{adj_g:+.1f}%** once the weather is removed{tail}"
                )
            if len(yr) >= 1:
                fav = yr.reset_index()
                fav["sign"] = np.where(fav["weather_pct"] >= 0, "favorable", "unfavorable")
                fig = px.bar(fav, x="year", y="weather_pct", text_auto=".1f", color="sign",
                             color_discrete_map={"favorable": POS_COLOR, "unfavorable": NEG_COLOR},
                             labels={"weather_pct": "Weather impact on the year (%)", "year": "", "sign": ""})
                fig.update_layout(height=300, showlegend=False, margin=dict(t=10, b=0, l=0, r=0))
                st.plotly_chart(fig, width="stretch")
                st.caption(
                    "Each year's weather luck for riding: positive = warmer/drier than the seasonal "
                    "norm, negative = cooler/wetter. The cool, wet stretch of 2018–19 cost a few "
                    "percent; 2023–24 ran favorable — handy for weather-adjusting targets and reading "
                    "true year-over-year growth."
                )

# --------------------------------------------------------------------------- temperature
with tab_temp:
    st.subheader("Warmer days mean more rides — up to a point")
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.scatter(
            dw, x="tavg_f", y="trips", color="season",
            color_discrete_map=SEASON_COLORS, trendline="lowess",
            trendline_options=dict(frac=0.3),
            labels={"tavg_f": "Average temperature (°F)", "trips": "Trips / day", "season": "Season"},
            opacity=0.45, render_mode="webgl",
        )
        fig.update_layout(height=460, legend=dict(orientation="h", y=1.02, x=0),
                          margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
    with c2:
        bands = pd.cut(dw["tavg_f"], [-100, 32, 50, 65, 80, 200],
                       labels=["<32°F", "32–50°F", "50–65°F", "65–80°F", "80°F+"])
        band_avg = dw.groupby(bands, observed=True)["trips"].mean().reset_index()
        fig = px.bar(band_avg, x="tavg_f", y="trips", text_auto=".2s",
                     labels={"tavg_f": "Temperature band", "trips": "Avg trips / day"},
                     color="trips", color_continuous_scale="Tealrose")
        fig.update_layout(height=460, coloraxis_showscale=False,
                          margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
    st.caption(
        "The lowess fit climbs steeply from freezing to ~75°F, then flattens and "
        "dips on the hottest days (80°F+) — riders avoid extreme heat much as they "
        "avoid the cold."
    )

# --------------------------------------------------------------------------- precip
with tab_precip:
    st.subheader("Rain dampens ridership; snow stops it")
    c1, c2 = st.columns(2)
    with c1:
        fig = px.box(dw, x="condition", y="trips", color="condition",
                     category_orders={"condition": ["Dry", "Rainy", "Snowy"]},
                     color_discrete_map=COND_COLORS,
                     labels={"condition": "", "trips": "Trips / day"}, points=False)
        fig.update_layout(height=440, showlegend=False, margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
        st.caption("Distribution of daily trips by weather condition (snow takes precedence over rain).")
    with c2:
        snowy = dw[dw["snow_inches"] > 0]
        fig = px.scatter(
            snowy, x="snow_inches", y="trips", color="tavg_f",
            color_continuous_scale="Blues_r",
            labels={"snow_inches": "Snowfall (inches)", "trips": "Trips / day", "tavg_f": "Temp °F"},
            opacity=0.7,
        )
        fig.update_layout(height=440, margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
        st.caption("On snow days, ridership collapses as accumulation rises — the heaviest storms bring the system to a near-standstill.")

    c3, c4 = st.columns(2)
    with c3:
        rain = dw[dw["prcp_inches"] > 0]
        fig = px.scatter(
            rain, x="prcp_inches", y="trips", color="season", color_discrete_map=SEASON_COLORS,
            trendline="lowess", opacity=0.4, render_mode="webgl",
            labels={"prcp_inches": "Precipitation (inches)", "trips": "Trips / day", "season": "Season"},
        )
        fig.update_layout(height=380, legend=dict(orientation="h", y=1.02, x=0),
                          margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
        st.caption("Across rainy days, heavier precipitation pulls ridership down within every season.")
    with c4:
        ground = dw[dw["snow_depth_inches"] > 0]
        fig = px.scatter(
            ground, x="snow_depth_inches", y="trips", color="tavg_f",
            color_continuous_scale="Blues_r", opacity=0.7,
            labels={"snow_depth_inches": "Snow on the ground (inches)", "trips": "Trips / day", "tavg_f": "Temp °F"},
        )
        fig.update_layout(height=380, margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
        st.caption("Snow lying on the ground holds ridership down for days after a storm — not just on the day it falls.")

# --------------------------------------------------------------------------- wind
with tab_wind:
    st.subheader("Strong winds keep riders off the bikes")
    wind = d.dropna(subset=["wind_avg_mph", "ridership_index"])
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.scatter(
            wind, x="wind_avg_mph", y="ridership_index", color="season",
            color_discrete_map=SEASON_COLORS, trendline="lowess",
            trendline_options=dict(frac=0.4), opacity=0.45, render_mode="webgl",
            labels={"wind_avg_mph": "Average wind speed (mph)",
                    "ridership_index": "Ridership vs. normal (%)", "season": "Season"},
        )
        fig.add_hline(y=100, line_dash="dot", line_color="#888")
        fig.update_layout(height=460, legend=dict(orientation="h", y=1.02, x=0),
                          margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
    with c2:
        bands = pd.cut(wind["wind_avg_mph"], [-1, 5, 9, 13, 100],
                       labels=["Calm <5", "Breezy 5–9", "Windy 9–13", "Gale 13+"])
        band = wind.groupby(bands, observed=True)["ridership_index"].median().reset_index()
        fig = px.bar(band, x="wind_avg_mph", y="ridership_index", text_auto=".0f",
                     color="ridership_index", color_continuous_scale="RdYlGn", range_color=[60, 110],
                     labels={"wind_avg_mph": "Daily average wind", "ridership_index": "Median ridership vs. normal (%)"})
        fig.add_hline(y=100, line_dash="dot", line_color="#888")
        fig.update_layout(height=460, coloraxis_showscale=False, margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
    st.caption(
        "Wind is shown against the **ridership index** — a day's trips as a percent of "
        "the surrounding month's norm — so the effect is net of season (winter is both "
        "colder *and* windier). Calm and breezy days ride near normal; once the daily "
        "average tops ~9 mph ridership drops off, and the windiest days (13 mph+, "
        "gusting 30–40 mph) run little more than half their usual volume. Some of that "
        "gap is the cold that rides along with wind; the **🎯 Impact** tab puts wind's "
        "own isolated effect at about half this."
    )

# --------------------------------------------------------------------------- humidity
with tab_humid:
    st.subheader("On warm days, mugginess thins the crowd")
    comfort = d.dropna(subset=["dewpoint_f", "ridership_index"])
    warm = comfort[comfort["tavg_f"] >= 68].copy()
    if warm.empty:
        st.info(
            "No warm days (avg ≥ 68°F) with humidity data in this selection. "
            "Humidity and dew point are available for **2016–2024** only — widen the year range."
        )
    else:
        c1, c2 = st.columns([3, 2])
        with c1:
            fig = px.scatter(
                warm, x="dewpoint_f", y="ridership_index", color="tavg_f",
                color_continuous_scale="Turbo", opacity=0.5, render_mode="webgl",
                labels={"dewpoint_f": "Dew point (°F) — higher is muggier",
                        "ridership_index": "Ridership vs. normal (%)", "tavg_f": "Temp °F"},
            )
            fig.add_hline(y=100, line_dash="dot", line_color="#888")
            fig.update_layout(height=460, margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig, width="stretch")
            st.caption("Warm days only (avg ≥ 68°F). Dew point is the best single gauge of how muggy it feels.")
        with c2:
            warm["comfort"] = pd.cut(warm["dewpoint_f"], [-100, 60, 70, 200],
                                     labels=["Pleasant <60°F", "Sticky 60–70°F", "Oppressive 70°F+"])
            band = warm.groupby("comfort", observed=True)["ridership_index"].median().reset_index()
            fig = px.bar(band, x="comfort", y="ridership_index", text_auto=".0f",
                         color="ridership_index", color_continuous_scale="RdYlGn", range_color=[80, 110],
                         labels={"comfort": "Dew-point comfort (warm days)", "ridership_index": "Median ridership vs. normal (%)"})
            fig.add_hline(y=100, line_dash="dot", line_color="#888")
            fig.update_layout(height=460, coloraxis_showscale=False, margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig, width="stretch")
            st.caption("Dry-warm days ride above normal; oppressive humidity pulls them ~12% below.")
        st.caption(
            "🛈 Humidity, dew point, wet-bulb and pressure come from the Central Park "
            "station and are available for **2016–2024** only."
        )

# --------------------------------------------------------------------------- riders
with tab_riders:
    st.subheader("Casual riders are far more weather-sensitive than members")
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.scatter(
            dw, x="tavg_f", y="pct_casual", color="season", color_discrete_map=SEASON_COLORS,
            trendline="lowess", opacity=0.45, render_mode="webgl",
            labels={"tavg_f": "Average temperature (°F)", "pct_casual": "Casual share of trips (%)", "season": "Season"},
        )
        fig.update_layout(height=440, legend=dict(orientation="h", y=1.02, x=0),
                          margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
        st.caption("The casual (non-member) share of ridership rises sharply with temperature: good weather brings out tourists and occasional riders.")
    with c2:
        bands = pd.cut(dw["tavg_f"], [-100, 32, 50, 65, 80, 200],
                       labels=["<32°F", "32–50°F", "50–65°F", "65–80°F", "80°F+"])
        mix = dw.groupby(bands, observed=True)[["member", "casual"]].mean().reset_index()
        mix = mix.melt(id_vars="tavg_f", var_name="rider", value_name="trips")
        mix["rider"] = mix["rider"].map({"member": "Member", "casual": "Casual"})
        fig = px.bar(mix, x="tavg_f", y="trips", color="rider", barmode="group",
                     color_discrete_map={"Member": "#4C78A8", "Casual": "#E45756"},
                     labels={"tavg_f": "Temperature band", "trips": "Avg trips / day", "rider": ""})
        fig.update_layout(height=440, legend=dict(orientation="h", y=1.02, x=0),
                          margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
        st.caption("Both segments grow with warmth, but casual ridership multiplies fastest.")

# --------------------------------------------------------------------------- seasonal
with tab_seasonal:
    st.subheader("Seasonality and growth at a glance")
    pivot = (d.assign(month=d["date"].dt.month)
               .pivot_table(index="month", columns="year", values="trips", aggfunc="mean")
               .reindex(range(1, 13)))  # always 12 rows so the month labels line up
    fig = px.imshow(
        pivot, aspect="auto", color_continuous_scale="YlGnBu",
        labels=dict(x="Year", y="Month", color="Avg trips/day"),
        y=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    )
    fig.update_layout(height=460, margin=dict(t=10, b=0, l=0, r=0))
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Each column is a year, each row a month. The vertical gradient is the "
        "weather/seasonal cycle (summer bright, winter dark); the left-to-right "
        "brightening is the network's growth."
    )

    st.markdown("##### Average trips per day by month")
    monthly = (d.assign(month=d["date"].dt.month_name(),
                        m=d["date"].dt.month)
                 .groupby(["m", "month"], as_index=False)["trips"].mean()
                 .sort_values("m"))
    fig = px.line(monthly, x="month", y="trips", markers=True,
                  labels={"month": "", "trips": "Avg trips / day"})
    fig.update_layout(height=320, margin=dict(t=10, b=0, l=0, r=0))
    st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------- footer
with st.expander("About this dashboard"):
    st.markdown(
        """
This dashboard visualizes how weather affects Citibike ridership across the full
**2013 → present** history (New York City + Jersey City).

- **Trips** come from `nyu-datasets.citibike.daily_trips` / `m_daily_trips`, a daily
  aggregation of the canonical `m_trips_unified` trip table.
- **Weather** comes from `nyu-datasets.weather.m_weather_daily_nyc` — daily NYC
  temperature, precipitation, snow (and snow depth), **wind**, **humidity / dew
  point**, **pressure**, and condition flags (fog, thunder, haze). Humidity, dew
  point, wet-bulb and pressure are Central Park readings covering **2016–2024**;
  everything else spans the full history.
- The two are joined on the calendar date in
  `nyu-datasets.citibike.daily_trips_weather`, the view the daily tabs read.
- The **🕐 Hourly tab** reads `nyu-datasets.citibike.hourly_trips_weather` —
  `m_hourly_trips` (one row per local clock hour) joined to the *hourly* Central
  Park record (`nyu-datasets.weather.m_weather_hourly_nyc`, NOAA LCD v2: ~24
  METARs/day from the same station as the daily weather, 2013 → present). Both
  sides carry local wall-clock hours, so rain is matched to the very hour it fell.

The **ridership index** used in the Wind and Humidity views is a day's
trips as a percent of the surrounding ~month's typical trips (a centered 29-day
median of the selected region's daily series). It nets out the network's growth and
the seasonal cycle, so a weather effect can be read on its own even though wind,
humidity and storms are themselves correlated with the seasons.

The **🎯 Impact tab** goes a step further. The index is still a *marginal* comparison —
a windy day is also a cold day — so it fits one regression (`attribution.py`):
log-ridership on month fixed effects (trend + season + COVID), day-of-week, holidays
and all weather together, with Newey–West standard errors for the day-to-day
autocorrelation. Each coefficient is a *partial* effect — the impact of that factor
with the others held constant — which is what separates wind from the cold it rides
with, and turns thunderstorms from apparently-negative to positive.

The **📊 Performance tab** turns the same modeling into an operator KPI. It predicts the
trips you'd expect for each day's weather *and* time of year, then contrasts the actual
weather against the day-of-year climatological normal to compute a **weather-adjusted**
ridership — letting you read true year-over-year growth and weather-adjust targets net
of whether the season ran warm/dry or cool/wet.

Day keys use Citibike's local (America/New_York) calendar date, and January 2021
is de-duplicated (Citibike published it in both the legacy and current layouts).
        """
    )
    st.dataframe(d.tail(30), width="stretch", hide_index=True)
