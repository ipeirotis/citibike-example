# Citibike × Weather dashboard

A [Streamlit](https://streamlit.io) dashboard visualizing the effect of NYC
weather on Citibike ridership across the full **2013 → present** history, designed
to run on **Google Cloud Run**.

It reads a single BigQuery view —
`nyu-datasets.citibike.daily_trips_weather` — which joins the daily trip
aggregates (`m_daily_trips`, built from the canonical `m_trips_unified`) to NYC
daily weather (`nyu-datasets.weather.m_weather_daily_nyc`). The view is ~4.7k rows,
so the app pulls it once (cached for an hour) and filters in-browser.

## What it shows

| Tab | Visualizations |
|---|---|
| **Overview** | Daily trips + 30-day average overlaid with temperature (dual axis) |
| **Temperature** | Trips vs. avg temperature (lowess fit, by season) + temperature-band averages |
| **Rain & Snow** | Trips by condition (box), trips vs. snowfall, trips vs. precipitation |
| **Riders** | Casual share vs. temperature; member vs. casual by temperature band |
| **Seasonality** | Month × year heatmap; average trips per day by month |

Sidebar filters: year range, region (NYC + JC / NYC / JC), and weekdays vs. weekends.

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

> The pipeline's `claude-agent` service account has BigQuery access but **not** the
> Cloud Run / Cloud Build / Service Usage roles, so it cannot run `deploy.sh`. Run
> it as a project owner/editor (or grant the deployer roles above), or build and
> deploy the image from your own machine.

The service is deployed `--allow-unauthenticated` (a public read-only dashboard).
Drop that flag to require IAM-authenticated access instead.
