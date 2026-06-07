# Citibike ETL pipeline. Cloud auth is automatic (cloud-bootstrap SessionStart hook).
PY ?= python3
export PYTHONPATH := src

.PHONY: help install selftest mirror mirror-jc extract extract-jc external view materialize unify

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:       ## install Python dependencies
	$(PY) -m pip install -r requirements.txt

selftest:      ## run the dependency-light transform self-test (no cloud)
	$(PY) -m citibike_pipeline.selftest

mirror:        ## Stage 1: mirror ALL raw ZIPs from Citibike S3 -> gs://.../raw/zip/
	$(PY) -m citibike_pipeline.mirror_raw --region all

mirror-jc:     ## Stage 1: mirror only the Jersey City archives
	$(PY) -m citibike_pipeline.mirror_raw --region jc

extract:       ## Stage 2: raw ZIPs in GCS -> typed Parquet in GCS (all regions)
	$(PY) -m citibike_pipeline.extract --region all

extract-jc:    ## Stage 2: extract only Jersey City
	$(PY) -m citibike_pipeline.extract --region jc

external:      ## Stage 3: (re)create BigQuery external tables over the Parquet
	$(PY) -m citibike_pipeline.load_bigquery external

view:          ## Stage 3: deploy the unified trips_unified view
	$(PY) -m citibike_pipeline.load_bigquery view

materialize:   ## Stage 3: snapshot the view into the native `trips` table
	$(PY) -m citibike_pipeline.load_bigquery materialize

unify: external view  ## Stage 3: external tables + unified view
