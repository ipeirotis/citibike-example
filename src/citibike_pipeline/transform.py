"""Turn a raw Citibike CSV (read as strings) into a typed Arrow table.

Kept free of any cloud I/O so it can be unit-tested on tiny in-memory samples
(see ``make selftest``). The caller is responsible for reading the CSV with
``dtype=str`` and already-normalized column names; this module only coerces
types and enforces the per-era Parquet schema.
"""
from __future__ import annotations

import pandas as pd
import pyarrow as pa

from .schemas import SCHEMAS, schema_columns


def _coerce(series: pd.Series, arrow_type: pa.DataType) -> pd.Series:
    """Coerce one column of strings to the dtype implied by ``arrow_type``."""
    if pa.types.is_timestamp(arrow_type):
        # Citibike date formats drift across years; let pandas infer, drop junk.
        return pd.to_datetime(series, errors="coerce")
    if pa.types.is_integer(arrow_type):
        return pd.to_numeric(series, errors="coerce").astype("Int64")
    if pa.types.is_floating(arrow_type):
        return pd.to_numeric(series, errors="coerce").astype("float64")
    # string: trim, and treat empties / '\N' sentinels as NULL (not the text "")
    s = series.astype("string").str.strip()
    return s.mask(s.isin(["", "\\N", "NULL"]))


def clean_frame(df: pd.DataFrame, era: str) -> pd.DataFrame:
    """Return a frame with exactly the era's schema columns, correctly typed.

    Missing columns are added as all-NULL so a short header never breaks the
    Parquet schema; extra columns are dropped.
    """
    # Reproduce the reference notebooks' cell-level cleaning on the raw string
    # frame, before typing: 'NULL'/'\\N' sentinels become missing, and a trailing
    # '.0' is stripped from every cell (e.g. station id '497.0' -> '497',
    # birth_year '1985.0' -> '1985', timestamp '...:00.0' -> '...:00').
    df = df.replace({"NULL": pd.NA, "\\N": pd.NA})
    df = df.replace(r"\.0$", "", regex=True)

    schema = SCHEMAS[era]
    out = {}
    for field in schema:
        col = df[field.name] if field.name in df.columns else pd.Series([pd.NA] * len(df))
        out[field.name] = _coerce(col, field.type)
    return pd.DataFrame(out, columns=schema_columns(era))


def frame_to_table(df: pd.DataFrame, era: str) -> pa.Table:
    """Clean ``df`` and materialize it as an Arrow table on the era's schema."""
    cleaned = clean_frame(df, era)
    return pa.Table.from_pandas(cleaned, schema=SCHEMAS[era], preserve_index=False)
