"""Dependency-light self-test for the schema/transform core (no cloud I/O).

Exercises both Citibike layouts on tiny in-memory samples and asserts the
reconciliation rules taken from the reference notebooks: header-based era
detection, the trailing-'.0' strip, '\\N'/'NULL' -> null, and the exact typed
Parquet schema.

    python -m citibike_pipeline.selftest
"""
from __future__ import annotations

import io
import zipfile

import pandas as pd

from .schemas import CURRENT_SCHEMA, LEGACY_SCHEMA, detect_era, normalize_columns
from .transform import frame_to_table

# Legacy layout, with the messy bits we must handle: '.0'-suffixed ids, a '\N'
# birth_year, mixed-case spaced headers, and Customer/Subscriber user types.
LEGACY_CSV = (
    "Trip Duration,Start Time,Stop Time,Start Station ID,Start Station Name,"
    "Start Station Latitude,Start Station Longitude,End Station ID,End Station Name,"
    "End Station Latitude,End Station Longitude,Bike ID,User Type,Birth Year,Gender\n"
    "438,2016-04-01 00:00:30,2016-04-01 00:07:48,497.0,E 17 St,40.737,-73.990,"
    "438.0,St Marks Pl,40.727,-73.987,20645.0,Customer,\\N,0\n"
    "525,2016-04-01 00:01:00,2016-04-01 00:09:45,3236,W 42 St,40.760,-73.991,"
    "3236,W 42 St,40.760,-73.991,15845,Subscriber,1979,2\n"
)

# Current layout: note end_station_id '7079.05' must NOT be touched by the
# '.0' strip, while '6432.0' must become '6432'.
CURRENT_CSV = (
    "ride_id,rideable_type,started_at,ended_at,start_station_name,start_station_id,"
    "end_station_name,end_station_id,start_lat,start_lng,end_lat,end_lng,member_casual\n"
    "CDAD1D727D887388,classic_bike,2021-10-01 00:10:00,2021-10-01 00:43:10,W 50 St,"
    "6432.0,Central Park,7079.05,40.76,-73.98,40.79,-73.96,member\n"
)


def _frame(csv: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(csv), dtype=str, keep_default_na=False)


def main() -> int:
    # --- legacy ---------------------------------------------------------------
    lf = _frame(LEGACY_CSV)
    assert detect_era(lf.columns) == "legacy"
    lf.columns = normalize_columns(lf.columns)
    lt = frame_to_table(lf, "legacy")
    assert lt.schema.equals(LEGACY_SCHEMA), lt.schema
    d = lt.to_pydict()
    assert d["start_station_id"] == ["497", "3236"], d["start_station_id"]   # .0 stripped
    assert d["end_station_id"] == ["438", "3236"], d["end_station_id"]
    assert d["bike_id"][0] == "20645", d["bike_id"]                          # .0 stripped
    assert d["birth_year"][0] is None and d["birth_year"][1] == 1979.0       # \N -> null
    assert d["gender"] == [0, 2]
    assert d["trip_duration"] == [438, 525]

    # --- current --------------------------------------------------------------
    cf = _frame(CURRENT_CSV)
    assert detect_era(cf.columns) == "current"
    cf.columns = normalize_columns(cf.columns)
    ct = frame_to_table(cf, "current")
    assert ct.schema.equals(CURRENT_SCHEMA), ct.schema
    cd = ct.to_pydict()
    assert cd["start_station_id"] == ["6432"], cd["start_station_id"]        # .0 stripped
    assert cd["end_station_id"] == ["7079.05"], cd["end_station_id"]         # left intact
    assert cd["ride_id"] == ["CDAD1D727D887388"]
    assert cd["rideable_type"] == ["classic_bike"]
    assert cd["member_casual"] == ["member"]

    # --- extract de-dup (combined+shard / nested copies) ----------------------
    try:
        from .extract import _csv_members
    except Exception as e:  # cloud libs unavailable in a truly minimal env
        print(f"  (skipped _csv_members check: {e})")
    else:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n in ("201309-citibike-tripdata.csv",         # combined ...
                      "201309-citibike-tripdata_1.csv",       # ... + shards -> drop shards
                      "201309-citibike-tripdata_2.csv",
                      "201405-citibike-tripdata_1.csv",       # shard-only -> keep
                      "201406-citibike-tripdata.csv",         # combined ...
                      "nested/201406-citibike-tripdata.csv",  # ... nested dup -> keep shallow
                      "202604-citibike-tripdata-part1.csv",   # monthly parts -> keep all
                      "202604-citibike-tripdata-part2.csv"):
                z.writestr(n, "h\n1\n")
        with zipfile.ZipFile(buf) as z:
            got = _csv_members(z)
        assert got == sorted([
            "201309-citibike-tripdata.csv",
            "201405-citibike-tripdata_1.csv",
            "201406-citibike-tripdata.csv",
            "202604-citibike-tripdata-part1.csv",
            "202604-citibike-tripdata-part2.csv",
        ]), got
        print("  _csv_members keeps combined over shards and de-dups nested copies")

    # A short header on a non-zero-index chunk (a later read_csv chunk) must fill the
    # absent column without union-misaligning indexes and inflating the row count.
    sf = _frame(CURRENT_CSV)
    sf.columns = normalize_columns(sf.columns)
    sf = sf.drop(columns=["rideable_type"])
    sf.index = pd.RangeIndex(500_000, 500_000 + len(sf))
    st = frame_to_table(sf, "current")
    assert st.num_rows == len(sf), (st.num_rows, len(sf))
    print("  short header on an offset chunk fills absent cols without inflating rows")

    print("selftest OK — both layouts normalize to the expected typed schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
