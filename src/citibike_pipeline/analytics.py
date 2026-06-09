"""Stage 4 — daily marts for the weather-effects dashboard.

Builds, on top of the canonical ``trips_unified`` view:

* ``daily_trips``           — one row per calendar day (counts, splits, durations)
* ``m_daily_trips``         — native snapshot of that view (what the dashboard reads)
* ``daily_trips_weather``   — ``m_daily_trips`` LEFT JOINed to NYC daily weather

The SQL is kept in lockstep with ``sql/daily_trips.sql`` and
``sql/daily_trips_weather.sql`` (human-readable mirrors).

    python -m citibike_pipeline.analytics daily-view        # (re)create daily_trips
    python -m citibike_pipeline.analytics daily-materialize # CTAS native m_daily_trips
    python -m citibike_pipeline.analytics daily-weather     # join weather -> daily_trips_weather
    python -m citibike_pipeline.analytics daily             # all three, in order
"""
from __future__ import annotations

import argparse
import sys

from google.cloud import bigquery

from . import config

# One row per local calendar day. See sql/daily_trips.sql for the full rationale
# (local-time day key, era de-duplication at CURRENT_ERA_START).
_DAILY_SQL = """\
CREATE OR REPLACE VIEW `{view}` AS
SELECT
  DATE(start_time)                                          AS date,
  COUNT(*)                                                  AS num_trips,
  COUNTIF(member_casual = 'member')                         AS num_member_trips,
  COUNTIF(member_casual = 'casual')                         AS num_casual_trips,
  COUNTIF(region = 'NYC' AND member_casual = 'member')      AS num_member_trips_nyc,
  COUNTIF(region = 'NYC' AND member_casual = 'casual')      AS num_casual_trips_nyc,
  COUNTIF(region = 'JC'  AND member_casual = 'member')      AS num_member_trips_jc,
  COUNTIF(region = 'JC'  AND member_casual = 'casual')      AS num_casual_trips_jc,
  COUNTIF(region = 'NYC')                                   AS num_nyc_trips,
  COUNTIF(region = 'JC')                                    AS num_jc_trips,
  COUNTIF(rideable_type = 'classic_bike')                   AS num_classic_trips,
  COUNTIF(rideable_type = 'electric_bike')                  AS num_electric_trips,
  ROUND(AVG(trip_duration_seconds) / 60, 3)                 AS avg_trip_duration_minutes,
  ROUND(APPROX_QUANTILES(trip_duration_seconds, 100)[OFFSET(50)] / 60, 3)
                                                            AS median_trip_duration_minutes,
  ROUND(AVG(distance_meters), 1)                            AS avg_distance_meters
FROM `{source}`
WHERE NOT (source_era = 'current' AND DATE(start_time) < DATE '{cutover}')
GROUP BY date"""

# Daily ridership LEFT JOINed to NYC daily weather — the dashboard's source view.
# `d.* EXCEPT(date)` carries every weather column through — calendar context
# (year/month/day_of_week/is_weekend/season), temperature, precipitation & snow,
# snow depth, wind, humidity/comfort (RH, dew point, wet-bulb), pressure, and the
# 1/0 condition flags — so new weather measurements flow into the dashboard
# automatically without editing this view. `t.date` is the join key + canonical date.
_DAILY_WEATHER_SQL = """\
CREATE OR REPLACE VIEW `{view}` AS
SELECT
  t.*,
  d.* EXCEPT(date)
FROM `{daily}` AS t
LEFT JOIN `{weather}` AS d
  ON t.date = d.date"""


def _client() -> bigquery.Client:
    return bigquery.Client(project=config.PROJECT, location=config.LOCATION)


def build_daily_view(client: bigquery.Client) -> None:
    """Deploy the daily_trips aggregation view over trips_unified."""
    sql = _DAILY_SQL.format(
        view=config.table_id(config.DAILY_VIEW),
        source=config.table_id(config.UNIFIED_VIEW),
        cutover=config.CURRENT_ERA_START,
    )
    client.query(sql, location=config.LOCATION).result()
    print(f"  deployed view {config.DAILY_VIEW}")


def materialize_daily(client: bigquery.Client) -> None:
    """Snapshot daily_trips into the native m_daily_trips table."""
    sql = (f"CREATE OR REPLACE TABLE `{config.table_id(config.DAILY_TABLE)}` AS "
           f"SELECT * FROM `{config.table_id(config.DAILY_VIEW)}`")
    client.query(sql, location=config.LOCATION).result()
    out = client.get_table(config.table_id(config.DAILY_TABLE))
    print(f"  materialized {config.DAILY_TABLE}: {out.num_rows:,} rows")


def build_daily_weather_view(client: bigquery.Client) -> None:
    """Deploy daily_trips_weather: m_daily_trips LEFT JOIN NYC daily weather."""
    sql = _DAILY_WEATHER_SQL.format(
        view=config.table_id(config.DAILY_WEATHER_VIEW),
        daily=config.table_id(config.DAILY_TABLE),
        weather=config.weather_table_id(config.WEATHER_DAILY_TABLE),
    )
    client.query(sql, location=config.LOCATION).result()
    print(f"  deployed view {config.DAILY_WEATHER_VIEW}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the daily marts for the weather dashboard.")
    ap.add_argument("command", choices=["daily-view", "daily-materialize", "daily-weather", "daily"])
    args = ap.parse_args(argv)

    client = _client()
    if args.command in ("daily-view", "daily"):
        build_daily_view(client)
    if args.command in ("daily-materialize", "daily"):
        materialize_daily(client)
    if args.command in ("daily-weather", "daily"):
        build_daily_weather_view(client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
