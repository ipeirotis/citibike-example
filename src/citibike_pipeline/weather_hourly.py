"""Stage W — hourly NYC weather: NOAA LCD v2 -> GCS -> BigQuery.

The daily weather mart (``weather.weather_daily_nyc``) is built from GHCN-Daily,
whose Central Park values are summaries of hourly ASOS observations. NOAA
publishes those parent observations as **Local Climatological Data v2** — one
CSV per station-year — so this stage ingests the *same station, same
instrument* at observation granularity. That unlocks exposure-weighted
regressors for the trips models (riding-hours temperature, rain timing,
afternoon wet-bulb) and extends humidity/dew-point coverage back before 2016,
where the daily mart's GHCN ``ADPT``/``RHAV`` elements begin.

Same stage shape as the trips pipeline:

    mirror       NCEI station-year CSVs -> gs://<bucket>/raw/lcd/   (immutable)
    extract      raw CSVs -> typed Parquet under weather/lcd/parquet/  (SI units)
    external     CREATE OR REPLACE EXTERNAL TABLE weather.lcd_hourly_nyc
    view         deploy weather.weather_hourly_nyc (imperial + local-time keys)
    materialize  snapshot into weather.m_weather_hourly_nyc
    load         external + view + materialize
    all          everything above, in order

Three source facts the transform pins (see also sql/weather_hourly_nyc.sql):

* **Time basis.** LCD v2 stamps observations in local *standard* time
  year-round (UTC-5, never DST) — verified by matching identical observations
  against the UTC-stamped ISD record in both January and July (+5h both).
  Citibike trips are naive local wall-clock (America/New_York, DST-aware), so
  the view derives ``obs_time_local`` via LST -> UTC -> America/New_York.
* **Units.** LCD v2 is SI: degC, mm, m/s, km, hPa. Parquet stays faithful to
  the source (SI); the view adds the daily mart's imperial conventions.
* **Value markers.** ``T`` = trace precipitation (-> 0.0, matching how GHCN
  daily treats trace); a trailing ``s`` = failed-QC "suspect" (-> NULL, the
  hourly analog of the daily mart's ``qflag IS NULL`` filter); a trailing
  ``V`` = "variable" (the measurement stands); ``VRB`` wind direction has no
  numeric bearing (-> NULL).

Rows kept: FM-15 (routine hourly METAR) and FM-16 (special obs). The SOD/SOM
daily/monthly summary rows are the daily mart's domain and are dropped. Snow
accumulation has **no hourly source** anywhere — snowfall/depth are once-daily
manual measurements; hourly snow shows up only as present-weather flags.

    python -m citibike_pipeline.weather_hourly all
    python -m citibike_pipeline.weather_hourly mirror --years 2024 2025
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import config

# Typed Parquet schema — SI units as published; timestamps are naive LST
# (micros + no timezone => BigQuery reads the column as DATETIME).
LCD_SCHEMA = pa.schema([
    ("station_id", pa.string()),
    ("obs_time_lst", pa.timestamp("us")),
    ("report_type", pa.string()),
    ("temp_c", pa.float64()),
    ("dewpoint_c", pa.float64()),
    ("wetbulb_c", pa.float64()),
    ("rh_pct", pa.float64()),
    ("precip_mm", pa.float64()),
    ("slp_hpa", pa.float64()),
    ("station_pressure_hpa", pa.float64()),
    ("altimeter_hpa", pa.float64()),
    ("wind_speed_ms", pa.float64()),
    ("wind_gust_ms", pa.float64()),
    ("wind_dir_deg", pa.float64()),
    ("visibility_km", pa.float64()),
    ("sky_conditions", pa.string()),
    ("present_weather", pa.string()),
    ("source_file", pa.string()),
])

# (LCD column, parquet column, treat "T" as trace -> 0.0)
_NUMERIC_COLS = [
    ("HourlyDryBulbTemperature", "temp_c", False),
    ("HourlyDewPointTemperature", "dewpoint_c", False),
    ("HourlyWetBulbTemperature", "wetbulb_c", False),
    ("HourlyRelativeHumidity", "rh_pct", False),
    ("HourlyPrecipitation", "precip_mm", True),
    ("HourlySeaLevelPressure", "slp_hpa", False),
    ("HourlyStationPressure", "station_pressure_hpa", False),
    ("HourlyAltimeterSetting", "altimeter_hpa", False),
    ("HourlyWindSpeed", "wind_speed_ms", False),
    ("HourlyWindGustSpeed", "wind_gust_ms", False),
    ("HourlyWindDirection", "wind_dir_deg", False),
    ("HourlyVisibility", "visibility_km", False),
]
_STRING_COLS = [
    ("HourlySkyConditions", "sky_conditions"),
    ("HourlyPresentWeatherType", "present_weather"),
]
_KEEP_REPORT_TYPES = ("FM-15", "FM-16")


def clean_value(v, *, trace_zero: bool = False) -> float | None:
    """One LCD measurement string -> float (or None where unusable).

    Pins the marker rules from the module docstring: trace, suspect, variable,
    VRB. Anything else non-numeric (e.g. ``*`` placeholders) is unmeasured.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if not s:
        return None
    if s == "T":
        return 0.0 if trace_zero else None
    if s == "VRB":
        return None
    if s.endswith("s"):  # NCEI "suspect" QC suffix — failed quality control
        return None
    if s.endswith("V"):  # "variable" — the measured value still stands
        s = s[:-1]
    try:
        return float(s)
    except ValueError:
        return None


def lcd_frame_to_table(df: pd.DataFrame, source_file: str) -> pa.Table:
    """Raw LCD station-year frame (strings) -> typed Arrow table (pure, unit-tested).

    Filters to FM-15/FM-16, cleans every numeric column per ``clean_value``,
    de-duplicates repeated (timestamp, report_type) rows, sorts chronologically.
    """
    d = df.loc[df["REPORT_TYPE"].str.strip().isin(_KEEP_REPORT_TYPES)].copy()
    out = pd.DataFrame()
    out["station_id"] = pd.Series(config.WEATHER_STATION, index=d.index)
    out["obs_time_lst"] = pd.to_datetime(d["DATE"])
    out["report_type"] = d["REPORT_TYPE"].str.strip()
    for src, dest, trace in _NUMERIC_COLS:
        col = d[src] if src in d.columns else pd.Series(None, index=d.index)
        out[dest] = col.map(lambda v: clean_value(v, trace_zero=trace)).astype("float64")
    for src, dest in _STRING_COLS:
        col = d[src] if src in d.columns else pd.Series(None, index=d.index)
        out[dest] = col.map(lambda v: None if pd.isna(v) or not str(v).strip() else str(v).strip())
    out["source_file"] = source_file
    # NCEI files occasionally repeat an observation (e.g. a re-transmitted
    # METAR); keep the first occurrence so each (time, type) appears once.
    out = (out.drop_duplicates(subset=["obs_time_lst", "report_type"], keep="first")
              .sort_values(["obs_time_lst", "report_type"]).reset_index(drop=True))
    return pa.Table.from_pandas(out, schema=LCD_SCHEMA, preserve_index=False)


# --------------------------------------------------------------------- mirror
def _years(args_years: list[int] | None) -> list[int]:
    last = dt.date.today().year
    return sorted(args_years) if args_years else list(range(config.LCD_FIRST_YEAR, last + 1))


def _raw_name(year: int) -> str:
    return f"LCD_{config.WEATHER_STATION}_{year}.csv"


def mirror(years: list[int], *, overwrite: bool) -> int:
    """Freeze NCEI station-year CSVs under raw/lcd/, byte-for-byte.

    Idempotent like the trips mirror: skipped when GCS already holds the file
    at the remote's Content-Length (NCEI re-publishes past years after QC
    reprocessing, and the current year grows — both re-mirror via size drift).
    """
    import requests

    from . import gcsio

    errors = 0
    for i, year in enumerate(years, 1):
        name = _raw_name(year)
        url = f"{config.LCD_BASE_URL}{year}/{name}"
        dest = f"{config.LCD_RAW_PREFIX}{name}"
        try:
            head = requests.head(url, timeout=60)
            if head.status_code == 404:  # year not published (yet)
                print(f"[{i:>2}/{len(years)}] absent {name} (404 at NCEI)", flush=True)
                continue
            head.raise_for_status()
            remote_size = int(head.headers.get("Content-Length", -1))
            if not overwrite and remote_size > 0 and gcsio.size(dest) == remote_size:
                print(f"[{i:>2}/{len(years)}] skip   {name} ({remote_size/1e6:.1f} MB)", flush=True)
                continue
            with requests.get(url, stream=True, timeout=(10, 600)) as r:
                r.raise_for_status()
                r.raw.decode_content = True
                gcsio.upload_stream(r.raw, dest, content_type="text/csv")
            print(f"[{i:>2}/{len(years)}] mirror {name} ({remote_size/1e6:.1f} MB)", flush=True)
        except Exception as e:  # keep a long backfill alive past one bad year
            errors += 1
            print(f"[{i:>2}/{len(years)}] ERROR  {name}: {e}", flush=True)
    print(f"  -> {config.gcs_uri(config.LCD_RAW_PREFIX)}")
    return errors


# -------------------------------------------------------------------- extract
def extract(years: list[int]) -> int:
    """Raw LCD CSVs in GCS -> typed Parquet (one file per station-year)."""
    from . import gcsio

    have = set(gcsio.list_names(config.LCD_RAW_PREFIX))
    errors = 0
    for i, year in enumerate(years, 1):
        raw = f"{config.LCD_RAW_PREFIX}{_raw_name(year)}"
        if raw not in have:
            print(f"[{i:>2}/{len(years)}] absent {raw} — run mirror first", flush=True)
            continue
        try:
            buf = io.BytesIO()
            gcsio._bucket().blob(raw).download_to_file(buf)
            buf.seek(0)
            df = pd.read_csv(buf, dtype=str, low_memory=False)
            table = lcd_frame_to_table(df, raw)
            sink = io.BytesIO()
            pq.write_table(table, sink, compression="snappy")
            sink.seek(0)
            dest = f"{config.LCD_PARQUET_PREFIX}lcd_hourly_nyc_{year}.parquet"
            gcsio.upload_stream(sink, dest, content_type="application/octet-stream")
            print(f"[{i:>2}/{len(years)}] extract {dest} ({table.num_rows:,} obs)", flush=True)
        except Exception as e:
            errors += 1
            print(f"[{i:>2}/{len(years)}] ERROR  {raw}: {e}", flush=True)
    print(f"  -> {config.gcs_uri(config.LCD_PARQUET_PREFIX)}")
    return errors


# ------------------------------------------------------------------- BigQuery
# Kept in lockstep with sql/weather_hourly_nyc.sql (the human-readable mirror).
_VIEW_SQL = """\
CREATE OR REPLACE VIEW `{view}` AS
WITH obs AS (
  SELECT
    -- The Parquet column physically holds LST wall times, but BigQuery
    -- surfaces external Parquet timestamps as UTC-labeled TIMESTAMPs, so
    -- DATETIME() first recovers the naive LST wall time...
    * EXCEPT(obs_time_lst),
    DATETIME(obs_time_lst) AS obs_time_lst,
    -- ...then re-anchor it: LCD v2 stamps observations in local STANDARD time
    -- year-round (UTC-5, never DST — verified against the UTC ISD record in
    -- January and July). 'Etc/GMT+5' is the fixed UTC-5 zone (POSIX sign
    -- convention), i.e. exactly LST.
    TIMESTAMP(DATETIME(obs_time_lst), 'Etc/GMT+5') AS obs_time_utc
  FROM `{external}`
)
SELECT
  station_id,
  report_type,
  obs_time_lst,
  obs_time_utc,
  -- Local wall-clock (America/New_York, DST-aware): the key that lines up
  -- with Citibike's naive-local start_time. +1h vs LST in summer.
  DATETIME(obs_time_utc, 'America/New_York')                    AS obs_time_local,
  DATE(obs_time_utc, 'America/New_York')                        AS date_local,
  EXTRACT(HOUR FROM DATETIME(obs_time_utc, 'America/New_York')) AS hour_local,
  -- Imperial, matching the daily mart's conventions.
  ROUND(temp_c * 9/5 + 32, 1)         AS temp_f,
  ROUND(dewpoint_c * 9/5 + 32, 1)     AS dewpoint_f,
  ROUND(wetbulb_c * 9/5 + 32, 1)      AS wetbulb_f,
  rh_pct,
  ROUND(precip_mm / 25.4, 3)          AS prcp_inches,
  slp_hpa                             AS sea_level_pressure_hpa,
  ROUND(wind_speed_ms * 2.23694, 1)   AS wind_mph,
  ROUND(wind_gust_ms * 2.23694, 1)    AS wind_gust_mph,
  wind_dir_deg,
  ROUND(visibility_km / 1.609344, 1)  AS visibility_miles,
  -- Instantaneous condition flags decoded from METAR present-weather codes.
  -- is_foggy/is_thunder/is_hazy mirror the daily mart's WT01/WT03/WT08
  -- semantics (FG not BR: mist is excluded there too). is_raining/is_snowing
  -- are *falling-now* flags — the daily is_rainy/is_snowy mean "accumulated
  -- today", a different statement.
  IF(REGEXP_CONTAINS(IFNULL(present_weather, ''), r'RA|DZ'), 1, 0)       AS is_raining,
  IF(REGEXP_CONTAINS(IFNULL(present_weather, ''), r'SN|SG|PL|GS'), 1, 0) AS is_snowing,
  IF(REGEXP_CONTAINS(IFNULL(present_weather, ''), r'FG'), 1, 0)          AS is_foggy,
  IF(REGEXP_CONTAINS(IFNULL(present_weather, ''), r'TS'), 1, 0)          AS is_thunder,
  IF(REGEXP_CONTAINS(IFNULL(present_weather, ''), r'HZ'), 1, 0)          AS is_hazy,
  sky_conditions,
  present_weather,
  -- SI originals, as published (the Parquet is the source of truth).
  temp_c, dewpoint_c, wetbulb_c, precip_mm,
  wind_speed_ms, wind_gust_ms, visibility_km,
  source_file
FROM obs"""


def _client():
    from google.cloud import bigquery

    return bigquery.Client(project=config.PROJECT, location=config.LOCATION)


def ensure_external(client) -> None:
    uri = config.gcs_uri(config.LCD_PARQUET_PREFIX, "*.parquet")
    name = config.weather_table_id(config.WEATHER_HOURLY_EXTERNAL)
    client.query(
        f"CREATE OR REPLACE EXTERNAL TABLE `{name}`\n"
        f"OPTIONS (format = 'PARQUET', uris = ['{uri}'])",
        location=config.LOCATION,
    ).result()
    print(f"  + {config.WEATHER_HOURLY_EXTERNAL}  ->  {uri}")


def build_view(client) -> None:
    sql = _VIEW_SQL.format(
        view=config.weather_table_id(config.WEATHER_HOURLY_VIEW),
        external=config.weather_table_id(config.WEATHER_HOURLY_EXTERNAL),
    )
    client.query(sql, location=config.LOCATION).result()
    print(f"  deployed view {config.WEATHER_HOURLY_VIEW}")


def materialize(client) -> None:
    sql = (f"CREATE OR REPLACE TABLE `{config.weather_table_id(config.WEATHER_HOURLY_TABLE)}` AS "
           f"SELECT * FROM `{config.weather_table_id(config.WEATHER_HOURLY_VIEW)}`")
    client.query(sql, location=config.LOCATION).result()
    out = client.get_table(config.weather_table_id(config.WEATHER_HOURLY_TABLE))
    print(f"  materialized {config.WEATHER_HOURLY_TABLE}: {out.num_rows:,} rows")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ingest NOAA LCD v2 hourly weather for Central Park.")
    ap.add_argument("command",
                    choices=["mirror", "extract", "external", "view", "materialize", "load", "all"])
    ap.add_argument("--years", nargs="*", type=int,
                    help=f"station-years to process (default {config.LCD_FIRST_YEAR}..current)")
    ap.add_argument("--overwrite", action="store_true", help="re-mirror even if size matches")
    args = ap.parse_args(argv)

    years = _years(args.years)
    errors = 0
    if args.command in ("mirror", "all"):
        errors += mirror(years, overwrite=args.overwrite)
    if args.command in ("extract", "all"):
        errors += extract(years)
    if args.command in ("external", "load", "all"):
        ensure_external(_client())
    if args.command in ("view", "load", "all"):
        build_view(_client())
    if args.command in ("materialize", "load", "all"):
        materialize(_client())
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
