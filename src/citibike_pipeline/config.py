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


def gcs_uri(*parts: str) -> str:
    """Join a GCS path under the project bucket: gcs_uri('raw', 'zip') -> gs://.../raw/zip."""
    path = "/".join(p.strip("/") for p in parts if p)
    return f"gs://{BUCKET}/{path}"


def table_id(name: str) -> str:
    """Fully-qualified BigQuery table id: `project.dataset.name`."""
    return f"{PROJECT}.{DATASET}.{name}"


def region_of(filename: str) -> str:
    """Citibike publishes Jersey City archives with a `JC-` prefix; everything else is NYC."""
    base = filename.rsplit("/", 1)[-1]
    return "JC" if base.upper().startswith("JC-") else "NYC"
