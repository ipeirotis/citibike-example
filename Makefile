# Citibike ETL pipeline.
#   Cloud auth: gcloud CLI is activated by the cloud-bootstrap SessionStart hook;
#   the Python clients get ADC via scripts/with-credentials.sh (the WITH wrapper).
#   Run `make install` once to create .venv, then the stage targets below.
PY   := .venv/bin/python
WITH := bash scripts/with-credentials.sh
export PYTHONPATH := src

.PHONY: help install selftest mirror mirror-jc extract extract-jc extract-nyc-new external view materialize unify daily-view daily-materialize daily-weather daily

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:       ## create .venv and install dependencies
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.txt

selftest:      ## run the dependency-light transform self-test (no cloud)
	$(PY) -m citibike_pipeline.selftest

mirror:        ## Stage 1: mirror ALL raw ZIPs from Citibike S3 -> gs://.../raw/zip/
	$(WITH) $(PY) -m citibike_pipeline.mirror_raw --region all

mirror-jc:     ## Stage 1: mirror only the Jersey City archives
	$(WITH) $(PY) -m citibike_pipeline.mirror_raw --region jc

extract:       ## Stage 2: raw ZIPs in GCS -> typed Parquet in GCS (all regions)
	$(WITH) $(PY) -m citibike_pipeline.extract --region all

extract-jc:    ## Stage 2: extract only Jersey City
	$(WITH) $(PY) -m citibike_pipeline.extract --region jc

extract-nyc-new: ## Stage 2: extract NYC monthly archives newer than what's loaded
	$(WITH) $(PY) -m citibike_pipeline.extract --nyc-new

external:      ## Stage 3: (re)create BigQuery external tables over the Parquet
	$(WITH) $(PY) -m citibike_pipeline.load_bigquery external

view:          ## Stage 3: deploy the unified trips_unified view
	$(WITH) $(PY) -m citibike_pipeline.load_bigquery view

materialize:   ## Stage 3: snapshot the view into the native `m_trips_unified` table
	$(WITH) $(PY) -m citibike_pipeline.load_bigquery materialize

unify: external view  ## Stage 3: external tables + unified view

daily-view:    ## Stage 4: deploy the daily_trips aggregation view
	$(WITH) $(PY) -m citibike_pipeline.analytics daily-view

daily-materialize: ## Stage 4: snapshot daily_trips into native m_daily_trips
	$(WITH) $(PY) -m citibike_pipeline.analytics daily-materialize

daily-weather: ## Stage 4: deploy daily_trips_weather (join NYC daily weather)
	$(WITH) $(PY) -m citibike_pipeline.analytics daily-weather

daily: ## Stage 4: daily_trips view + m_daily_trips snapshot + weather-join view
	$(WITH) $(PY) -m citibike_pipeline.analytics daily
