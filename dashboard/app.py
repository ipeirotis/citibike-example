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

PROJECT = os.environ.get("BQ_PROJECT", "nyu-datasets")
SOURCE = os.environ.get("DASHBOARD_SOURCE", "nyu-datasets.citibike.daily_trips_weather")

st.set_page_config(page_title="Citibike × Weather", page_icon="🚲", layout="wide")

# Consistent, colour-blind-friendly palette for the recurring categories.
SEASON_COLORS = {"Winter": "#4C78A8", "Spring": "#54A24B", "Summer": "#E45756", "Fall": "#F58518"}
COND_COLORS = {"Dry": "#54A24B", "Rainy": "#4C78A8", "Snowy": "#B279A2"}


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
    # Categorical weather condition (snow takes precedence over rain).
    df["condition"] = "Dry"
    df.loc[df["is_rainy"] == 1, "condition"] = "Rainy"
    df.loc[df["is_snowy"] == 1, "condition"] = "Snowy"
    # Casual share of ridership — the most weather-sensitive segment.
    df["pct_casual"] = (df["num_casual_trips"] / df["num_trips"] * 100).round(1)
    return df


df = load_data()

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

show_weekends = st.sidebar.radio("Days", ["All days", "Weekdays only", "Weekends only"])

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Source:** `nyu-datasets.citibike.daily_trips_weather`\n\n"
    "Daily trips (`m_daily_trips`) ⨝ NYC daily weather "
    "(`weather.m_weather_daily_nyc`)."
)

# Apply filters → a working frame. `trips` is the active region's count.
mask = (df["year"] >= yr_lo) & (df["year"] <= yr_hi)
if show_weekends == "Weekdays only":
    mask &= df["is_weekend"] == 0
elif show_weekends == "Weekends only":
    mask &= df["is_weekend"] == 1
d = df.loc[mask].copy()
d["trips"] = d[TRIPS_COL]
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

tab_overview, tab_temp, tab_precip, tab_riders, tab_seasonal = st.tabs(
    ["📈 Overview", "🌡️ Temperature", "🌧️ Rain & Snow", "🧍 Riders", "🗓️ Seasonality"]
)

# --------------------------------------------------------------------------- overview
with tab_overview:
    st.subheader("Daily ridership and temperature move together")
    roll = d.set_index("date").sort_index()
    roll["trips_30d"] = roll["trips"].rolling(30, min_periods=7).mean()
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

# --------------------------------------------------------------------------- riders
with tab_riders:
    st.subheader("Casual riders are far more weather-sensitive than members")
    st.caption("Member/casual splits are dataset-wide (NYC + Jersey City); the region filter does not apply here.")
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
        mix = dw.groupby(bands, observed=True)[["num_member_trips", "num_casual_trips"]].mean().reset_index()
        mix = mix.melt(id_vars="tavg_f", var_name="rider", value_name="trips")
        mix["rider"] = mix["rider"].map({"num_member_trips": "Member", "num_casual_trips": "Casual"})
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
- **Weather** comes from `nyu-datasets.weather.m_weather_daily_nyc` (daily NYC
  temperature, precipitation, and snow).
- The two are joined on the calendar date in
  `nyu-datasets.citibike.daily_trips_weather`, the single view this app reads.

Day keys use Citibike's local (America/New_York) calendar date, and January 2021
is de-duplicated (Citibike published it in both the legacy and current layouts).
        """
    )
    st.dataframe(d.tail(30), width="stretch", hide_index=True)
