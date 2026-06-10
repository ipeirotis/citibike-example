# Citibike × Weather dashboard

A [Streamlit](https://streamlit.io) dashboard visualizing the effect of NYC
weather on Citibike ridership across the full **2013 → present** history, designed
to run on **Google Cloud Run**.

**Live:** <https://citibike-weather-dashboard-1062917065927.us-central1.run.app>
(Cloud Run · `us-central1` · public · runtime SA `claude-agent`).

It reads a single BigQuery view —
`nyu-datasets.citibike.daily_trips_weather` — which joins the daily trip
aggregates (`m_daily_trips`, built from the canonical `m_trips_unified`) to NYC
daily weather (`nyu-datasets.weather.m_weather_daily_nyc`). The view is ~4.7k rows,
so the app pulls it once (cached for an hour) and filters in-browser.

## What it shows

| Tab | Visualizations |
|---|---|
| **Overview** | Daily trips + 30-day average overlaid with temperature (dual axis) |
| **Impact** | Regression-isolated effect of each weather factor (partial effects with 95% CIs) + a trend/season/weather variance decomposition |
| **Performance** | Weather-adjusted ridership (operator KPI): actual vs. weather-removed trend, the period's weather impact %, and per-year weather favorability |
| **Temperature** | Trips vs. avg temperature (lowess fit, by season) + temperature-band averages |
| **Rain & Snow** | Trips by condition (box), vs. snowfall, vs. precipitation, and vs. snow lying on the ground |
| **Wind** | Ridership index vs. wind speed (by season) + wind-band averages |
| **Humidity** | Dew-point comfort on warm days — scatter + comfort-band averages (2016–2024) |
| **Riders** | Casual share vs. temperature; member vs. casual by temperature band |
| **Seasonality** | Month × year heatmap; average trips per day by month |

Sidebar filters: year range, region (NYC + JC / NYC / JC), and weekdays vs. weekends.

The Wind and Humidity views read a **ridership index** — a day's
trips as a percent of the surrounding ~month's typical trips — so the effect of a
variable that is itself seasonal (wind, humidity, storms) shows up net of the
network's growth and the seasonal cycle. Humidity, dew point, wet-bulb and pressure
are Central Park readings covering **2016–2024**; temperature, precipitation, snow
(incl. depth), wind, and the condition flags span the full history.

That index is still a *marginal* comparison — a windy day is also a cold day — so the
**Impact** tab adds true attribution: a single regression (`attribution.py`) of
log-ridership on month fixed effects, day-of-week, holidays and all weather together
(Newey–West SEs) reports each factor's *partial* effect with the others held constant.
It separates wind from the cold it rides with, and flips thunderstorms from
apparently-negative to positive once their rain is accounted for.

The **Performance** tab reuses that modeling for an operator KPI: it predicts the trips
expected for each day's weather *and* time of year, then contrasts the actual weather
against the day-of-year climatological normal to produce a **weather-adjusted** ridership
— so true year-over-year growth and weather-adjusted targets can be read net of whether
the season ran warm/dry or cool/wet (validated: 2018, NYC's wettest year on record,
prints ≈ −5%; warm 2024 ≈ +5%).

## Run locally

```bash
cd dashboard
pip install -r requirements.txt
# Authenticate to BigQuery (any identity with read on citibike + weather):
gcloud auth application-default login        # or export GOOGLE_APPLICATION_CREDENTIALS=key.json
streamlit run app.py
```

Config via env vars: `BQ_PROJECT` (default `nyu-datasets`) and `DASHBOARD_SOURCE`
(default `nyu-datasets.citibike.daily_trips_weather`).

## Deploy to Cloud Run

```bash
cd dashboard
bash deploy.sh          # override with PROJECT=… REGION=… SERVICE=… RUNTIME_SA=…
```

`deploy.sh` enables the needed APIs and runs `gcloud run deploy --source .`
(Cloud Build builds the container from the `Dockerfile`, then Cloud Run serves it).

### Required APIs

`run.googleapis.com`, `cloudbuild.googleapis.com`, `artifactregistry.googleapis.com`
(the script enables these for you).

### Required roles

| Principal | Roles | Why |
|---|---|---|
| **Deployer** (whoever runs `deploy.sh`) | `roles/run.admin`, `roles/cloudbuild.builds.editor`, `roles/artifactregistry.admin`, `roles/iam.serviceAccountUser` on the runtime SA, `roles/serviceusage.serviceUsageAdmin` (to enable APIs) | Build the image and create the Cloud Run service |
| **Runtime SA** (`--service-account`) | `roles/bigquery.jobUser` on the project + `roles/bigquery.dataViewer` on the `citibike` **and** `weather` datasets | Let the running app query the view |

> The pipeline's `claude-agent` service account now holds the deployer capabilities
> above (Cloud Run, Cloud Build, Service Usage, and `actAs` on the runtime SA) in
> addition to its BigQuery access, so it can run `deploy.sh` itself — the live
> revision is deployed by it. Any principal with the roles above can deploy too.

The service is deployed `--allow-unauthenticated` (a public read-only dashboard).
Drop that flag to require IAM-authenticated access instead.
