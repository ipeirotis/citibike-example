# Citibike trip-data pipeline

An ETL pipeline that mirrors Citibike's published trip archives, converts them to
typed Parquet in Google Cloud Storage, and reconciles the platform's two CSV eras
into **one canonical BigQuery table**.

```
Citibike S3  →  GCS raw/zip/ (immutable)  →  typed Parquet  →  BigQuery  →  trips_unified
   mirror            Stage 1                     Stage 2          Stage 3      (superset view)
```

The hard part is era reconciliation: Citibike changed its CSV layout in early 2021
(column names, id formats, dropped demographics). `trips_unified` is the lossless
superset of both — see [`CLAUDE.md`](CLAUDE.md) for the full schema and design, and
[`schemas/canonical.json`](schemas/canonical.json) for the machine-readable spec.

## Quick start

```bash
make install     # pandas, pyarrow, google-cloud-{storage,bigquery}, requests
make selftest    # validate the transform core (no cloud needed)
```

Cloud access is automatic in Claude Code sessions (the cloud-bootstrap SessionStart
hook activates the service account). Then:

```bash
make mirror      # Stage 1: Citibike S3 -> gs://citibike-archive/raw/zip/  (idempotent)
make extract     # Stage 2: raw ZIPs -> typed Parquet in GCS
make unify       # Stage 3: external tables + the unified trips_unified view
# make materialize   # optional: snapshot trips_unified into native `m_trips_unified`
make daily       # Stage 4: daily_trips + m_daily_trips + daily_trips_weather (dashboard marts)
```

## Weather-effects dashboard

A [Streamlit](https://streamlit.io) dashboard in [`dashboard/`](dashboard/) visualizes
the effect of NYC weather on ridership (2013 → present) from
`nyu-datasets.citibike.daily_trips_weather` — the daily trips (`m_daily_trips`) joined to
NYC daily weather. Run it locally with `streamlit run dashboard/app.py`, or deploy to Google
Cloud Run with `bash dashboard/deploy.sh` (see [`dashboard/README.md`](dashboard/README.md)
for the required roles/APIs).

Scope a run with `--region {nyc,jc,all}` and `--limit N` (e.g.
`python -m citibike_pipeline.mirror_raw --region jc --limit 1` for a smoke test), or
`--dry-run` to preview. `make help` lists all targets.

## Data location

| Resource | Value |
|---|---|
| GCS bucket | `gs://citibike-archive` (`raw/zip/`, `tripdata/parquet/`, `rides/parquet/`, `jc/…`) |
| BigQuery | `nyu-datasets.citibike` (region `US`) |
| Unified view | `nyu-datasets.citibike.trips_unified` |
| Materialized | `nyu-datasets.citibike.m_trips_unified` |
| Daily marts | `daily_trips`, `m_daily_trips`, `daily_trips_weather` |

Built on the proof-of-concept notebooks at
[ipeirotis-org/datasets/Citibike](https://github.com/ipeirotis-org/datasets/tree/main/Citibike).
