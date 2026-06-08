"""Citibike trip-data ETL pipeline.

Stage 1 (mirror_raw) copies Citibike's raw ZIP archives into GCS untouched;
Stage 2 (extract) converts them to typed Parquet; Stage 3 (load_bigquery)
registers external tables and builds the unified trips_unified view.
"""
