# Notebooks

Narrative analyses built on the pipeline's BigQuery marts.

## `weather_effect_on_ridership.ipynb`

How NYC weather moves Citibike ridership, **2013 → present**, across two time grains:

- **Daily** — the level effects (temperature, rain, snow, wind, humidity), with a
  month-fixed-effects + Newey–West regression (the 🎯 Impact tab's daily model) that
  isolates each factor's *partial* effect from the correlated weather it travels with.
- **Hourly** — the timing effect of rain "at the hour it falls," identified with **day
  fixed effects** (within-day variation only), distributed lags + a cumulative effect,
  leads as a falsification check, a heavy-rain intensity shifter, day-clustered standard
  errors, and the member-vs-casual elasticity gradient as a validity probe.

It builds every model **from scratch** with `statsmodels` — it does *not* import the
dashboard code — so the regression design is visible and auditable on the page. The
Streamlit dashboard packages the equivalent logic in
[`../dashboard/attribution.py`](../dashboard/attribution.py) (`fit_impacts`,
`fit_hourly_rain_profile`, `fit_hourly_rain_by_daypart`, `weather_adjusted_daily`); the two
are kept in sync by hand, and the notebook's executed outputs match the live dashboard. (If
you change an estimator in `attribution.py`, update the notebook's matching cell too.)

### Running it

Reads two BigQuery views in `nyu-datasets` — `citibike.daily_trips_weather` and
`citibike.hourly_trips_weather` — via Application Default Credentials.

```bash
make install                 # repo venv (pandas, pyarrow, BigQuery client)
# notebook extras: statsmodels powers the regressions (attribution.py + the lowess
# fits) and is NOT in the root requirements.txt; db-dtypes lets BigQuery hydrate
# DATE/NUMERIC columns into pandas.
.venv/bin/pip install statsmodels db-dtypes jupyter matplotlib
.venv/bin/jupyter lab notebooks/weather_effect_on_ridership.ipynb
```

In a repo session, auth is the `claude-agent` service account; locally use
`gcloud auth application-default login` or set `GOOGLE_APPLICATION_CREDENTIALS`.
The committed copy already carries executed outputs, so it renders without a re-run.
