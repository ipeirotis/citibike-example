"""Schema reconciliation: the heart of the project.

Citibike has shipped two CSV layouts over the years. This module detects which
layout a CSV uses (from its header, never the filename year — the 2021 archive
straddles the change) and normalizes both into the two typed Parquet schemas
that the BigQuery external tables expect.

The cross-era *unification* into a single canonical row happens downstream in
SQL (see ``sql/trips_unified.sql`` / ``load_bigquery.build_unified_view``); this
module's job is only to produce clean, typed, per-era Parquet.
"""
from __future__ import annotations

from typing import Iterable

import pyarrow as pa

# --- Column-name normalization ------------------------------------------------
# Applied after a base normalize (strip -> lowercase -> spaces/dashes to "_").
# Folds every historical spelling of a column onto the canonical legacy/current
# names. Names already canonical (e.g. "start_station_id") pass through.
_RENAME = {
    # legacy quirks (no separators in the oldest headers)
    "tripduration": "trip_duration",
    "starttime": "start_time",
    "stoptime": "stop_time",
    "bikeid": "bike_id",
    "usertype": "user_type",
    # current layout -> canonical
    "started_at": "start_time",
    "ended_at": "stop_time",
    "start_lat": "start_station_latitude",
    "start_lng": "start_station_longitude",
    "end_lat": "end_station_latitude",
    "end_lng": "end_station_longitude",
}


def normalize_column(name: str) -> str:
    """Normalize a single raw CSV header to its canonical name.

    Mirrors the reference notebooks (strip -> lower -> space to '_' -> drop
    parentheses), with extra robustness for dashes and doubled underscores.
    """
    base = (name.strip().lower()
            .replace(" ", "_").replace("-", "_")
            .replace("(", "").replace(")", ""))
    while "__" in base:
        base = base.replace("__", "_")
    return _RENAME.get(base, base)


def normalize_columns(names: Iterable[str]) -> list[str]:
    return [normalize_column(n) for n in names]


# --- Era detection -------------------------------------------------------------
# Signals that unambiguously identify each layout, checked against the
# *normalized* header.
_CURRENT_SIGNALS = {"ride_id", "rideable_type", "member_casual"}
_LEGACY_SIGNALS = {"trip_duration", "bike_id", "user_type", "birth_year"}


def detect_era(raw_headers: Iterable[str]) -> str:
    """Return 'legacy' or 'current' for a CSV given its raw header row."""
    cols = set(normalize_columns(raw_headers))
    if cols & _CURRENT_SIGNALS:
        return "current"
    if cols & _LEGACY_SIGNALS:
        return "legacy"
    raise ValueError(f"Cannot determine Citibike layout from header: {sorted(cols)}")


# --- Typed Parquet schemas -----------------------------------------------------
# These intentionally match the existing nyu-datasets.citibike external tables so
# freshly produced Parquet is a drop-in for trips_2013_2021 / trips_2021_now
# (and their JC counterparts).
LEGACY_SCHEMA = pa.schema([
    ("trip_duration", pa.int64()),
    ("start_time", pa.timestamp("us")),
    ("stop_time", pa.timestamp("us")),
    ("start_station_id", pa.string()),
    ("start_station_name", pa.string()),
    ("start_station_latitude", pa.float64()),
    ("start_station_longitude", pa.float64()),
    ("end_station_id", pa.string()),
    ("end_station_name", pa.string()),
    ("end_station_latitude", pa.float64()),
    ("end_station_longitude", pa.float64()),
    ("bike_id", pa.string()),
    ("user_type", pa.string()),
    ("birth_year", pa.float64()),   # FLOAT: blanks/'\\N' become NULL, not 0
    ("gender", pa.int64()),         # 0=unknown, 1=male, 2=female
])

CURRENT_SCHEMA = pa.schema([
    ("ride_id", pa.string()),
    ("rideable_type", pa.string()),
    ("start_time", pa.timestamp("us")),
    ("stop_time", pa.timestamp("us")),
    ("start_station_id", pa.string()),
    ("start_station_name", pa.string()),
    ("start_station_latitude", pa.float64()),
    ("start_station_longitude", pa.float64()),
    ("end_station_id", pa.string()),
    ("end_station_name", pa.string()),
    ("end_station_latitude", pa.float64()),
    ("end_station_longitude", pa.float64()),
    ("member_casual", pa.string()),
])

SCHEMAS = {"legacy": LEGACY_SCHEMA, "current": CURRENT_SCHEMA}


def schema_columns(era: str) -> list[str]:
    return [f.name for f in SCHEMAS[era]]
