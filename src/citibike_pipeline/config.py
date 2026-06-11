"""Central configuration for the Citibike ETL pipeline.

Every cloud resource name lives here so the rest of the pipeline reads cleanly.
Values can be overridden via environment variables (handy for testing against a
scratch project/bucket), but the defaults point at the real
``nyu-datasets.citibike`` resources documented in CLAUDE.md.
"""
from __future__ import annotations

import os

# --- GCP / BigQuery -----------------------------------------------------------
PROJECT = os.environ.get("CITIBIKE_PROJECT", "nyu-datasets")
DATASET = os.environ.get("CITIBIKE_DATASET", "citibike")
LOCATION = os.environ.get("CITIBIKE_LOCATION", "US")

# --- GCS -----------------------------------------------------------------------
BUCKET = os.environ.get("CITIBIKE_BUCKET", "citibike-archive")

# Immutable, write-once landing zone for the exact ZIPs mirrored from Citibike.
# The Python extract reads from here, never from S3 directly, so reprocessing is
# deterministic and decoupled from AWS availability.
RAW_PREFIX = "raw/zip/"

# Typed Parquet output prefixes, split by region + layout era. The NYC prefixes
# match the existing external tables; JC mirrors that shape under jc/.
PARQUET_PREFIXES = {
    ("NYC", "legacy"): "tripdata/parquet/",
    ("NYC", "current"): "rides/parquet/",
    ("JC", "legacy"): "jc/tripdata/parquet/",
    ("JC", "current"): "jc/rides/parquet/",
}

# --- Source (Citibike public S3) ----------------------------------------------
# Listing this URL returns an XML inventory of every published trip archive.
S3_BASE_URL = "https://s3.amazonaws.com/tripdata/"

# --- BigQuery objects ----------------------------------------------------------
# External tables over the Parquet prefixes above, keyed by (region, era).
EXTERNAL_TABLES = {
    ("NYC", "legacy"): "trips_2013_2021",
    ("NYC", "current"): "trips_2021_now",
    ("JC", "legacy"): "trips_jc_2013_2021",
    ("JC", "current"): "trips_jc_2021_now",
}

# The improved, lossless union. Left as a separate object so the original
# `all_trips` view (prior art) is never clobbered.
UNIFIED_VIEW = "trips_unified"
# Materialization of the view into a native table. Convention: the view's name
# with an `m_` prefix (matches the dataset's existing all_trips / m_all_trips).
UNIFIED_TABLE = "m_trips_unified"

# --- Stage 4: daily marts for the weather-effects dashboard -------------------
# One row per calendar day aggregated from m_trips_unified, the weather-join view
# the Streamlit dashboard reads, and the materialized snapshots (`m_` prefix).
DAILY_VIEW = "daily_trips"
DAILY_TABLE = "m_daily_trips"
DAILY_WEATHER_VIEW = "daily_trips_weather"

# Daily NYC weather lives in a sibling dataset (same project + US location).
WEATHER_DATASET = os.environ.get("CITIBIKE_WEATHER_DATASET", "weather")
WEATHER_DAILY_TABLE = "m_weather_daily_nyc"

# --- Stage W: hourly NYC weather (NOAA LCD v2) ---------------------------------
# The daily mart summarizes GHCN-Daily for Central Park; LCD v2 is the *hourly*
# ASOS record of the same station, so the two marts share one instrument.
WEATHER_STATION = "USW00094728"  # NY CITY CENTRAL PARK — same id the daily mart filters on
LCD_BASE_URL = "https://www.ncei.noaa.gov/oa/local-climatological-data/v2/access/"
LCD_FIRST_YEAR = 2013            # Citibike era; LCD coverage reaches further back if needed
LCD_RAW_PREFIX = "raw/lcd/"                  # immutable station-year CSVs, as published
LCD_PARQUET_PREFIX = "weather/lcd/parquet/"  # typed Parquet (SI units, LST timestamps)
WEATHER_HOURLY_EXTERNAL = "lcd_hourly_nyc"   # external table over the Parquet
WEATHER_HOURLY_VIEW = "weather_hourly_nyc"   # imperial units + local-time keys + flags
WEATHER_HOURLY_TABLE = "m_weather_hourly_nyc"

# trips_unified double-counts January 2021 — the 2021 annual archive ships that
# month in the legacy layout and Citibike *also* re-published it in the current
# layout, so both copies loaded — plus ~1.5k stray current-era rows in 2019-2020
# carrying corrupt timestamps. The current layout's canonical data begins here;
# legacy (which cleanly ends 2021-01-31) owns every earlier day. daily_trips uses
# this to keep each calendar day in exactly one era per region.
CURRENT_ERA_START = "2021-02-01"


def gcs_uri(*parts: str) -> str:
    """Join a GCS path under the project bucket: gcs_uri('raw', 'zip') -> gs://.../raw/zip."""
    path = "/".join(p.strip("/") for p in parts if p)
    return f"gs://{BUCKET}/{path}"


def table_id(name: str) -> str:
    """Fully-qualified BigQuery table id: `project.dataset.name`."""
    return f"{PROJECT}.{DATASET}.{name}"


def weather_table_id(name: str) -> str:
    """Fully-qualified id for an object in the sibling `weather` dataset."""
    return f"{PROJECT}.{WEATHER_DATASET}.{name}"


def region_of(filename: str) -> str:
    """Citibike publishes Jersey City archives with a `JC-` prefix; everything else is NYC."""
    base = filename.rsplit("/", 1)[-1]
    return "JC" if base.upper().startswith("JC-") else "NYC"
