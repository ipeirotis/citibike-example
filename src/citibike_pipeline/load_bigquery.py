"""Stage 3 — register Parquet as BigQuery external tables and build the unified view.

This is the cross-era reconciliation. The per-era SELECT templates below are the
canonical projection (kept in lockstep with ``sql/trips_unified.sql``); the view
is the UNION ALL of whichever (region, era) external tables actually exist, so it
grows to cover Jersey City automatically once JC Parquet has been loaded.

    python -m citibike_pipeline.load_bigquery external     # (re)create external tables
    python -m citibike_pipeline.load_bigquery view         # deploy trips_unified
    python -m citibike_pipeline.load_bigquery materialize  # CTAS native `m_trips_unified`
    python -m citibike_pipeline.load_bigquery all
"""
from __future__ import annotations

import argparse
import sys

from google.cloud import bigquery

from . import config, gcsio

_LEGACY_BRANCH = """
SELECT
  CAST(NULL AS STRING) AS ride_id,
  CAST(NULL AS STRING) AS rideable_type,
  start_time, stop_time,
  CAST(COALESCE(trip_duration, TIMESTAMP_DIFF(stop_time, start_time, SECOND)) AS INT64) AS trip_duration_seconds,
  CAST(start_station_id AS STRING) AS start_station_id, start_station_name,
  start_station_latitude, start_station_longitude,
  CAST(end_station_id AS STRING) AS end_station_id, end_station_name,
  end_station_latitude, end_station_longitude,
  CASE user_type WHEN 'Subscriber' THEN 'member' WHEN 'Customer' THEN 'casual' END AS member_casual,
  CAST(bike_id AS STRING) AS bike_id,
  SAFE_CAST(birth_year AS INT64) AS birth_year,
  SAFE_CAST(gender AS INT64) AS gender,
  ST_DISTANCE(ST_GEOGPOINT(start_station_longitude, start_station_latitude),
              ST_GEOGPOINT(end_station_longitude, end_station_latitude)) AS distance_meters,
  '{region}' AS region, 'legacy' AS source_era, _FILE_NAME AS source_file
FROM `{table}`"""

_CURRENT_BRANCH = """
SELECT
  ride_id, rideable_type, start_time, stop_time,
  CAST(TIMESTAMP_DIFF(stop_time, start_time, SECOND) AS INT64) AS trip_duration_seconds,
  CAST(start_station_id AS STRING) AS start_station_id, start_station_name,
  start_station_latitude, start_station_longitude,
  CAST(end_station_id AS STRING) AS end_station_id, end_station_name,
  end_station_latitude, end_station_longitude,
  member_casual,
  CAST(NULL AS STRING) AS bike_id, CAST(NULL AS INT64) AS birth_year, CAST(NULL AS INT64) AS gender,
  ST_DISTANCE(ST_GEOGPOINT(start_station_longitude, start_station_latitude),
              ST_GEOGPOINT(end_station_longitude, end_station_latitude)) AS distance_meters,
  '{region}' AS region, 'current' AS source_era, _FILE_NAME AS source_file
FROM `{table}`"""

_BRANCH = {"legacy": _LEGACY_BRANCH, "current": _CURRENT_BRANCH}


def _client() -> bigquery.Client:
    return bigquery.Client(project=config.PROJECT, location=config.LOCATION)


def _has_parquet(prefix: str) -> bool:
    return any(n.endswith(".parquet") for n in gcsio.list_names(prefix))


def ensure_external_tables(client: bigquery.Client) -> list[tuple[str, str]]:
    """Create/replace an external table for every (region, era) prefix that has Parquet.

    Returns the (region, era) pairs that now have a live table.
    """
    live: list[tuple[str, str]] = []
    for (region, era), name in config.EXTERNAL_TABLES.items():
        prefix = config.PARQUET_PREFIXES[(region, era)]
        if not _has_parquet(prefix):
            print(f"  - {name}: no Parquet under {prefix} yet, skipping")
            continue
        ext = bigquery.ExternalConfig("PARQUET")
        ext.source_uris = [config.gcs_uri(prefix) + "*.parquet"]
        table = bigquery.Table(config.table_id(name))
        table.external_data_configuration = ext
        client.delete_table(config.table_id(name), not_found_ok=True)
        client.create_table(table)
        print(f"  + {name}  ->  {ext.source_uris[0]}")
        live.append((region, era))
    return live


def build_unified_view(client: bigquery.Client) -> None:
    """Deploy trips_unified as the UNION of every external table that exists."""
    branches = []
    for (region, era), name in config.EXTERNAL_TABLES.items():
        try:
            client.get_table(config.table_id(name))
        except Exception:
            continue
        branches.append(_BRANCH[era].format(region=region, table=config.table_id(name)))
    if not branches:
        raise RuntimeError("No source external tables exist; load Parquet first.")
    sql = (f"CREATE OR REPLACE VIEW `{config.table_id(config.UNIFIED_VIEW)}` AS\n"
           + "\nUNION ALL\n".join(branches))
    client.query(sql).result()
    print(f"  deployed view {config.UNIFIED_VIEW} ({len(branches)} era/region branch(es))")


def materialize(client: bigquery.Client) -> None:
    """Snapshot the view into a native table for cheaper, faster querying."""
    sql = (f"CREATE OR REPLACE TABLE `{config.table_id(config.UNIFIED_TABLE)}` AS "
           f"SELECT * FROM `{config.table_id(config.UNIFIED_VIEW)}`")
    job = client.query(sql)
    job.result()
    out = client.get_table(config.table_id(config.UNIFIED_TABLE))
    print(f"  materialized {config.UNIFIED_TABLE}: {out.num_rows:,} rows")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Register Parquet and build the unified BigQuery view.")
    ap.add_argument("command", choices=["external", "view", "materialize", "all"])
    args = ap.parse_args(argv)

    client = _client()
    if args.command in ("external", "all"):
        ensure_external_tables(client)
    if args.command in ("view", "all"):
        build_unified_view(client)
    if args.command in ("materialize", "all"):
        materialize(client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
