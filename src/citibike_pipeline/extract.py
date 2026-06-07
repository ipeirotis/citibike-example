"""Stage 2 — raw ZIPs in GCS  ->  typed Parquet in GCS  (a deterministic GCS->GCS step).

For every archive under ``raw/zip/`` this unzips in a temp dir, and for each CSV
member detects the layout *from the header* (the 2021 annual archive contains
both), normalizes columns, coerces types, and writes one Parquet file per CSV to
the region/era prefix the BigQuery external tables read.

Reading is chunked so a 1.6 GB annual CSV never has to fit in memory at once.

    python -m citibike_pipeline.extract --region jc --limit 1     # smoke: one JC archive
    python -m citibike_pipeline.extract --files JC-202401-citibike-tripdata.csv.zip
    python -m citibike_pipeline.extract --region all              # full backfill
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
import zipfile

import pandas as pd
import pyarrow.parquet as pq

from . import config, gcsio
from .schemas import detect_era, normalize_columns
from .transform import frame_to_table

CHUNK_ROWS = 500_000


def _csv_members(zf: zipfile.ZipFile) -> list[str]:
    """CSV members of a ZIP, de-duplicated by basename.

    Annual archives frequently contain the same monthly CSV twice — once at the
    root and once inside a nested subfolder. We keep a single member per
    basename (the shallowest path), mirroring the manual `mv */* .` + de-dup the
    reference notebooks do, so a month is never counted twice.

    Caveat: a few annual archives also ship a month as BOTH a combined CSV and
    `_1/_2/...` shards (different basenames). Those are handled per-year in the
    original notebooks; for full NYC re-extraction verify counts. The default
    pipeline reuses the existing NYC Parquet and only extracts Jersey City, whose
    archives are a single flat CSV, so this case does not arise there.
    """
    candidates = [
        n for n in zf.namelist()
        if n.lower().endswith(".csv")
        and not n.startswith("__MACOSX")
        and not n.endswith("/")
    ]
    best: dict[str, str] = {}
    for n in candidates:
        base = os.path.basename(n)
        if base not in best or n.count("/") < best[base].count("/"):
            best[base] = n
    return sorted(best.values())


def _read_header(zf: zipfile.ZipFile, member: str) -> list[str]:
    with zf.open(member) as fh:
        first = fh.readline().decode("utf-8-sig", errors="replace")
    return next(csv.reader([first]))


def _process_member(zf: zipfile.ZipFile, member: str, region: str, *,
                    overwrite: bool, dry_run: bool) -> str:
    era = detect_era(_read_header(zf, member))
    stem = os.path.splitext(os.path.basename(member))[0]
    dest = f"{config.PARQUET_PREFIXES[(region, era)]}{stem}.parquet"

    if not overwrite and gcsio.exists(dest):
        print(f"      skip  {member}  ({era}) -> {dest} [exists]")
        return "skip"
    if dry_run:
        print(f"      plan  {member}  ({era}) -> {dest}")
        return "plan"

    rows = 0
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        writer = None
        with zf.open(member) as fh:
            for chunk in pd.read_csv(fh, dtype=str, keep_default_na=False,
                                     encoding="utf-8-sig", chunksize=CHUNK_ROWS):
                chunk.columns = normalize_columns(chunk.columns)
                table = frame_to_table(chunk, era)
                if writer is None:
                    writer = pq.ParquetWriter(tmp_path, table.schema)
                writer.write_table(table)
                rows += table.num_rows
        if writer is not None:
            writer.close()
            gcsio.upload_file(tmp_path, dest)
            print(f"      write {member}  ({era}, {rows:,} rows) -> {dest}")
            return "write"
        print(f"      empty {member}  (no rows)")
        return "empty"
    finally:
        os.path.exists(tmp_path) and os.remove(tmp_path)


def process_archive(key: str, *, overwrite: bool, dry_run: bool) -> None:
    """Extract every CSV in one raw ZIP (downloaded from GCS) to Parquet."""
    region = config.region_of(key)
    src = f"{config.RAW_PREFIX}{key}"
    print(f"[{region}] {key}")
    with tempfile.TemporaryDirectory() as td:
        local_zip = os.path.join(td, os.path.basename(key))
        gcsio.download_file(src, local_zip)
        with zipfile.ZipFile(local_zip) as zf:
            for member in _csv_members(zf):
                _process_member(zf, member, region, overwrite=overwrite, dry_run=dry_run)


def _raw_keys(region: str) -> list[str]:
    names = gcsio.list_names(config.RAW_PREFIX)
    keys = [n[len(config.RAW_PREFIX):] for n in names if n.endswith(".zip")]
    if region != "all":
        keys = [k for k in keys if config.region_of(k) == region.upper()]
    return sorted(keys)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract raw Citibike ZIPs (in GCS) to typed Parquet.")
    ap.add_argument("--region", choices=["nyc", "jc", "all"], default="all")
    ap.add_argument("--files", nargs="*", help="specific raw ZIP names (under raw/zip/)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    keys = args.files if args.files else _raw_keys(args.region)
    if args.limit:
        keys = keys[: args.limit]
    if not keys:
        print("No raw archives found. Run the mirror stage first.")
        return 1

    for key in keys:
        process_archive(key, overwrite=args.overwrite, dry_run=args.dry_run)
    print(f"\nDone. {len(keys)} archive(s) processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
