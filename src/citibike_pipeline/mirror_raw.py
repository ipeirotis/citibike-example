"""Stage 1 — mirror Citibike's raw trip archives into GCS, byte-for-byte.

Citibike re-publishes and occasionally renames/removes historical archives, so
we freeze an immutable copy in ``gs://<bucket>/raw/zip/`` and treat it as the
single source of truth. Everything downstream reads from here, never from S3, so
reprocessing is deterministic.

Idempotent: a ZIP already present in GCS with the same byte size is skipped, so
re-runs are cheap and only fetch what's new or changed.

    python -m citibike_pipeline.mirror_raw --region all          # mirror everything
    python -m citibike_pipeline.mirror_raw --region jc --limit 1  # one JC file (smoke)
    python -m citibike_pipeline.mirror_raw --dry-run             # show plan only
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET

import requests

from . import config, gcsio


def list_archives(region: str = "all") -> list[tuple[str, int]]:
    """Return [(filename, size_bytes), ...] for every .zip in Citibike's S3 bucket.

    Handles pagination defensively even though the listing currently fits one page.
    """
    archives: list[tuple[str, int]] = []
    marker = ""
    while True:
        resp = requests.get(config.S3_BASE_URL, params={"marker": marker}, timeout=60)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        # Strip the S3 XML namespace so tag lookups stay readable.
        ns = {"s3": root.tag[root.tag.find("{") + 1 : root.tag.find("}")]} if "}" in root.tag else {}

        def find(el, tag):
            return el.find(f"s3:{tag}", ns) if ns else el.find(tag)

        contents = root.findall("s3:Contents", ns) if ns else root.findall("Contents")
        last_key = ""
        for c in contents:
            key = find(c, "Key").text or ""
            last_key = key
            if not key.endswith(".zip"):
                continue
            size = int((find(c, "Size").text or "0"))
            archives.append((key, size))

        truncated = (find(root, "IsTruncated").text or "false").lower() == "true"
        if not truncated or not last_key:
            break
        marker = last_key

    if region != "all":
        want = region.upper()
        archives = [(k, s) for k, s in archives if config.region_of(k) == want]
    return sorted(archives)


def mirror_one(key: str, size: int, *, overwrite: bool, dry_run: bool) -> str:
    """Mirror a single archive. Returns 'skip', 'mirror', or 'plan'."""
    dest = f"{config.RAW_PREFIX}{key}"
    if not overwrite and gcsio.size(dest) == size:
        return "skip"
    if dry_run:
        return "plan"
    url = f"{config.S3_BASE_URL}{key}"
    with requests.get(url, stream=True, timeout=(10, 600)) as r:
        r.raise_for_status()
        r.raw.decode_content = True
        gcsio.upload_stream(r.raw, dest, content_type="application/zip")
    return "mirror"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mirror Citibike raw ZIP archives into GCS.")
    ap.add_argument("--region", choices=["nyc", "jc", "all"], default="all")
    ap.add_argument("--files", nargs="*", help="specific archive filenames (overrides --region/--limit)")
    ap.add_argument("--limit", type=int, default=0, help="cap number of archives (0 = no cap)")
    ap.add_argument("--overwrite", action="store_true", help="re-upload even if size matches")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    archives = list_archives("all" if args.files else args.region)
    if args.files:
        want = set(args.files)
        archives = [(k, s) for k, s in archives if k in want or k.rsplit("/", 1)[-1] in want]
    elif args.limit:
        archives = archives[: args.limit]

    total = len(archives)
    counts = {"skip": 0, "mirror": 0, "plan": 0, "error": 0}
    for i, (key, size) in enumerate(archives, 1):
        try:
            status = mirror_one(key, size, overwrite=args.overwrite, dry_run=args.dry_run)
        except Exception as e:  # don't let one bad archive abort a long backfill
            counts["error"] += 1
            print(f"[{i:>3}/{total}] ERROR  {key}: {e}", flush=True)
            continue
        counts[status] += 1
        print(f"[{i:>3}/{total}] {status:6} {key} ({size/1e6:.1f} MB)", flush=True)

    print(f"\nDone. mirrored={counts['mirror']} skipped={counts['skip']} "
          f"errors={counts['error']} -> {config.gcs_uri(config.RAW_PREFIX)}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
