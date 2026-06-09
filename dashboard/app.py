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
# Diverging colours for the "% vs. normal" impact bars (below / above the norm).
NEG_COLOR, POS_COLOR = "#C44E52", "#55A868"


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

tab_overview, tab_temp, tab_precip, tab_wind, tab_humid, tab_riders, tab_seasonal = st.tabs(
    ["📈 Overview", "🌡️ Temperature", "🌧️ Rain & Snow", "🌬️ Wind", "💧 Humidity",
     "🧍 Riders", "🗓️ Seasonality"]
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

    st.markdown("##### Which weather conditions hurt ridership most")
    di = d.dropna(subset=["ridership_index"])
    conds = [
        ("Snowfall",            di["is_snowy"] == 1),
        ("Heavy rain (≥½ in)",  di["prcp_inches"] >= 0.5),
        ("High wind (≥10 mph)", di["wind_avg_mph"] >= 10),
        ("Snow on ground",      di["snow_depth_inches"] > 0),
        ("Any rain",            di["is_rainy"] == 1),
        ("Thunderstorm",        di["is_thunder"] == 1),
        ("Fog",                 di["is_foggy"] == 1),
        ("Freezing (<32°F)",    di["is_freezing"] == 1),
        ("Humid (RH ≥70%)",     di["is_humid"] == 1),
        ("Haze / smoke",        di["is_hazy"] == 1),
        ("Hot (>90°F)",         di["is_hot_day"] == 1),
    ]
    rows = []
    for label, mask_c in conds:
        sub = di.loc[mask_c, "ridership_index"].dropna()
        if len(sub) >= 20:  # enough days for a stable median
            rows.append({"Condition": label, "delta": sub.median() - 100, "days": int(len(sub))})
    if rows:
        imp = pd.DataFrame(rows).sort_values("delta")
        fig = go.Figure(go.Bar(
            x=imp["delta"], y=imp["Condition"], orientation="h",
            marker_color=np.where(imp["delta"] < 0, NEG_COLOR, POS_COLOR),
            customdata=imp["days"],
            hovertemplate="%{y}: %{x:+.0f}% vs. normal<br>%{customdata} days<extra></extra>",
            text=[f"{v:+.0f}%" for v in imp["delta"]], textposition="outside",
            cliponaxis=False,
        ))
        fig.update_layout(
            height=420, margin=dict(t=10, b=0, l=0, r=10),
            xaxis_title="Median ridership vs. the surrounding month (%)", yaxis_title="",
        )
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Each bar is how a day's ridership typically compares to the surrounding "
            "~month when that condition is present, so the network's growth and the "
            "seasonal cycle are already netted out (a day at 100% rode exactly its "
            "monthly norm). Snow and heavy rain hit hardest — roughly a third fewer "
            "rides — followed by strong winds and snow lingering on the ground. Hot "
            "days barely register: New Yorkers tolerate heat far better than cold, wet, "
            "or wind."
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
        "gusting 30–40 mph) run little more than half their usual volume."
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
  `nyu-datasets.citibike.daily_trips_weather`, the single view this app reads.

The **ridership index** used in the Wind, Humidity and Conditions views is a day's
trips as a percent of the surrounding ~month's typical trips (a centered 29-day
median of the selected region's daily series). It nets out the network's growth and
the seasonal cycle, so a weather effect can be read on its own even though wind,
humidity and storms are themselves correlated with the seasons.

Day keys use Citibike's local (America/New_York) calendar date, and January 2021
is de-duplicated (Citibike published it in both the legacy and current layouts).
        """
    )
    st.dataframe(d.tail(30), width="stretch", hide_index=True)
