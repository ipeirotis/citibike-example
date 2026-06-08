# Assignment — Build a "Citibike × Weather" Dashboard

Build and deploy an interactive web dashboard that shows **how NYC weather affects
Citibike ridership** across the full history (2013 → present). The finished product
is a multi-tab [Streamlit](https://streamlit.io) app, backed by data in BigQuery,
deployed to a public URL.

## 1. What you'll practice
- Reading data from BigQuery (or a provided snapshot) into pandas
- Building an interactive, multi-view dashboard with Streamlit + Plotly
- Turning charts into a *story* — each visual answers a question
- Containerizing and deploying a web app to the cloud

## 2. The data

You visualize one daily table: **`nyu-datasets.citibike.daily_trips_weather`** — one
row per calendar day (~4,700 rows, 2013-06-01 → present), which already joins daily
Citibike trip counts to NYC daily weather.

| column | type | meaning |
|---|---|---|
| `date` | DATE | local calendar day (the join key) |
| `num_trips` | INT | total trips that day |
| `num_member_trips`, `num_casual_trips` | INT | by rider type |
| `num_nyc_trips`, `num_jc_trips` | INT | by region (NYC / Jersey City) |
| `num_classic_trips`, `num_electric_trips` | INT | by bike type (current era only) |
| `avg_trip_duration_minutes`, `median_trip_duration_minutes` | FLOAT | trip duration |
| `avg_distance_meters` | FLOAT | mean start→end station distance |
| `tmin_f`, `tmax_f`, `tavg_f` | FLOAT | temperature (°F) |
| `prcp_inches`, `snow_inches` | FLOAT | precipitation / snowfall |
| `is_rainy`, `is_snowy`, `is_hot_day`, `is_freezing` | INT (0/1) | weather flags |
| `season`, `month`, `day_of_week`, `is_weekend` | | calendar context |

### Data access — pick one
- **Easiest — provided CSV.** Your instructor shares a `daily_trips_weather.csv`
  snapshot; read it with `pandas.read_csv(...)`. No cloud credentials — ideal for
  Streamlit Community Cloud.
- **Live — BigQuery.** Query the view directly with `google-cloud-bigquery`. Requires
  read access to `nyu-datasets` (a service-account key in `st.secrets`, or your own
  `gcloud auth application-default login`).

### Data facts you must handle (graded)
- The table is **tiny** — load it **once** and cache it. Never scan the 300M-row trip
  table from inside the app.
- Weather lags trips by ~2 weeks, so the most recent days have **NULL weather**. Drop
  those rows for weather scatter plots; keep them for the trips time series.
- `num_member_trips` / `num_casual_trips` are dataset-wide (NYC + JC).

## 3. Required features

**Stack:** Python 3.11, `streamlit`, `plotly`, `pandas` (+ `google-cloud-bigquery`
and `db-dtypes` if using BigQuery; `statsmodels` for Plotly trendlines).

1. **Cached data layer** — load the table in a function decorated with
   `@st.cache_data` so reloads are instant.
2. **Header + KPIs** — a title and **≥ 4 metric cards** (e.g. total trips, days
   covered, average trips/day, warm-vs-cold ratio).
3. **Sidebar filters that drive every chart** — at minimum: a **year-range** slider,
   a **region** selector (NYC + JC / NYC / JC), and a **weekday/weekend** toggle.
4. **At least 5 visualizations**, organized into tabs or sections, **each with a
   one-sentence insight caption**:
   1. **Overview time series** — daily trips with a rolling average over the full
      history, and temperature on a secondary axis.
   2. **Temperature vs ridership** — scatter of daily trips vs average temperature
      (colored by season, with a trendline) and/or a bar of average trips by
      temperature band. Should reveal the *rise-then-dip-in-extreme-heat* shape.
   3. **Rain & snow** — trips by condition (dry / rainy / snowy) as a box or bar,
      plus trips vs snowfall.
   4. **Rider mix** — show that **casual riders are more weather-sensitive than
      members** (e.g. casual share vs temperature, or member vs casual by temp band).
   5. **Seasonality** — a month × year heatmap and/or an average-by-month profile.

## 4. Deployment (deliver a public URL)
- **Option A — Streamlit Community Cloud (recommended).** Push the repo to GitHub,
  deploy at <https://share.streamlit.io>, put any BigQuery credentials in *Secrets*.
  Free, ~5 minutes.
- **Option B — Google Cloud Run.** Add a `Dockerfile` and run
  `gcloud run deploy --source .`. Bind `0.0.0.0:$PORT`, run `--server.headless=true`,
  and disable XSRF/CORS + websocket compression so the websocket survives the proxy.

## 5. Deliverables
A GitHub repo containing:
- `app.py` — well-structured and commented
- `requirements.txt`
- `README.md` — how to run locally, how you deployed, the **live URL**, and a short
  write-up of **3 insights** you found about weather and ridership
- `Dockerfile` (only if you chose Cloud Run)

## 6. Grading rubric (100 pts)
| Area | Pts |
|---|---|
| Data loading + caching + correct NULL handling | 15 |
| Five required visualizations (well-chosen chart types, readable) | 40 |
| Working filters that drive all charts | 15 |
| Insight captions + the 3-insight write-up (storytelling) | 10 |
| Deployed and reachable at a public URL | 15 |
| Code quality + README | 5 |

## 7. Stretch goals (bonus)
- **Quantify an effect** — regress `num_trips` on temperature + precipitation, or run
  a t-test of rainy vs dry days.
- **Find the thresholds** — at what temperature / snowfall does ridership collapse?
- **Build the data yourself** — aggregate the raw `m_trips_unified` table into your
  own `daily_trips`. Watch for the **January-2021 double-load** (Citibike published
  that month in two formats), and use the *local* `DATE(start_time)` as the day key
  (don't apply a timezone conversion — the timestamps are already local wall-clock).
- A station-level **map**, an **NYC vs JC** comparison, or a simple next-day forecast.

## 8. Starter hint — the data layer only

```python
import streamlit as st
import pandas as pd

@st.cache_data(ttl=3600)
def load_data() -> pd.DataFrame:
    # Option 1 — provided CSV (no credentials needed):
    return pd.read_csv("daily_trips_weather.csv", parse_dates=["date"])

    # Option 2 — live from BigQuery:
    # from google.cloud import bigquery
    # df = bigquery.Client(project="nyu-datasets").query(
    #     "SELECT * FROM `nyu-datasets.citibike.daily_trips_weather` ORDER BY date"
    # ).to_dataframe()
    # df["date"] = pd.to_datetime(df["date"])
    # return df

df = load_data()
st.title("How weather moves Citibike ridership")
# ... your KPIs, sidebar filters, and charts go here ...
```

Everything else — the KPIs, filters, and five charts — is yours to build.

---

> **Instructor note (remove before sharing):** a reference implementation built to
> this spec lives in `dashboard/` of this repo and is deployed at
> <https://citibike-weather-dashboard-1062917065927.us-central1.run.app>. The daily
> view is produced by `src/citibike_pipeline/analytics.py` (`make daily`).
