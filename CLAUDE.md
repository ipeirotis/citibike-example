# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## What we are building

This project builds an **ETL pipeline for Citibike trip data**:

1. **Extract** — download Citibike's published historical *trip* archives (one ZIP
   of CSVs per period) from their public AWS S3 bucket.
2. **Load (raw)** — stage the files in a **Google Cloud Storage** bucket, converting
   the per-period CSVs to **Parquet** with an explicit, typed schema.
3. **Transform / unify** — load the Parquet files into **BigQuery** and reconcile the
   *two different CSV layouts* Citibike has used over the years into **one unifying
   schema** — a single canonical `trips` table (or view) covering 2013 → present.

The hard part of this project is step 3: Citibike changed its trip-data format in
2021, so a row from 2014 and a row from 2024 describe the same kind of event with
different column names, different ID formats, and different available fields. The
goal of this repo is a clean, well-documented reconciliation of those eras.

> **Reference data already exists.** Trips are already loaded in BigQuery at
> **`nyu-datasets.citibike`** (region `US`). Treat that dataset as the prior art /
> target to reproduce and improve on. The proof-of-concept notebooks this repo is
> based on live at
> <https://github.com/ipeirotis-org/datasets/tree/main/Citibike>.

## Architecture / data flow

```
Citibike S3 archives (ZIP of CSVs)
        │  download + unzip
        ▼
   per-period CSVs  ──normalize columns──►  typed Parquet
        │
        │  upload
        ▼
GCS bucket: gs://citibike-archive/  (csv/ and parquet/ subfolders)
        │
        │  BigQuery external table over Parquet, then load to native
        ▼
BigQuery: nyu-datasets.citibike
        │
        │  UNION + column reconciliation across eras
        ▼
   ONE unified trips table/view  (canonical schema below)
```

## Cloud resources

| Resource | Value |
|---|---|
| GCP project | `nyu-datasets` |
| GCS bucket | `gs://citibike-archive` (subfolders `csv/`, `parquet/`) |
| BigQuery dataset | `nyu-datasets.citibike` (location `US`) |
| Service account | `citibike-sa@nyu-datasets.iam.gserviceaccount.com` |
| SA role (storage) | `roles/storage.objectAdmin` |

The pipeline also needs BigQuery access to create/load tables. The minimal roles are
`roles/storage.objectAdmin` (read/write Parquet in the bucket) plus
`roles/bigquery.dataEditor` and `roles/bigquery.jobUser` (create tables and run load
jobs). Confirm/grant these through the cloud-bootstrap setup flow (see **Cloud
access** below) — do not widen roles without asking.

## Source data

Citibike publishes historical trip data as ZIP files under
**`https://s3.amazonaws.com/tripdata/`** (index: `.../tripdata/index.html`):

- **2013 – early 2021 (annual):** `YYYY-citibike-tripdata.zip` — the *legacy* layout.
- **2021 – present (monthly):** `YYYYMM-citibike-tripdata.csv.zip` — the *current*
  layout. Jersey City rides are published separately as
  `JC-YYYYMM-citibike-tripdata.csv.zip`.

The cutover happened in **2021**; some 2021 files exist in both layouts, so detect the
layout from the CSV header rather than from the year alone.

## The two source schemas (the thing we are unifying)

**Legacy layout (≈2013–2021).** After normalization (lowercase, strip spaces → `_`):

```
trip_duration, start_time, stop_time,
start_station_id, start_station_name, start_station_latitude, start_station_longitude,
end_station_id,   end_station_name,   end_station_latitude,   end_station_longitude,
bike_id, user_type, birth_year, gender
```

**Current layout (2021 → present).** Raw headers are
`ride_id, rideable_type, started_at, ended_at, start_station_name, start_station_id,
end_station_name, end_station_id, start_lat, start_lng, end_lat, end_lng,
member_casual`; after normalization:

```
ride_id, rideable_type, start_time, stop_time,
start_station_id, start_station_name, start_station_latitude, start_station_longitude,
end_station_id,   end_station_name,   end_station_latitude,   end_station_longitude,
member_casual
```

### Key differences to reconcile

| Concern | Legacy (≤2021) | Current (≥2021) | Reconciliation |
|---|---|---|---|
| Trip duration | `trip_duration` (seconds) | *(absent)* | Compute `stop_time - start_time`; keep an explicit seconds column. |
| Rider type | `user_type` = `Subscriber`/`Customer` | `member_casual` = `member`/`casual` | Map `Subscriber → member`, `Customer → casual`. |
| Bike type | *(absent)* | `rideable_type` = `classic_bike`/`electric_bike`/`docked_bike` | NULL for legacy, or *infer* from `bike_id` ranges (see `BikeTypes.md` in the reference repo). |
| Trip / ride id | *(absent)* | `ride_id` (hash string) | NULL for legacy; do not synthesize a fake id. |
| Station id | integer (e.g. `497`) | string (e.g. `HB102`, `5905.14`) | **Canonical type is STRING** — cast legacy ids to string. |
| Demographics | `birth_year`, `gender` (0/1/2) | *(removed for privacy)* | NULL for current era. |

## Canonical unified schema

Target a single table/view that is the **superset** of both eras. Era-specific fields
are `NULL` where the source did not provide them. Suggested columns and types:

```
ride_id                  STRING     -- current era only
rideable_type            STRING     -- current era; inferable for legacy via bike_id
start_time               TIMESTAMP
stop_time                TIMESTAMP
trip_duration            INT64      -- seconds; explicit legacy, computed current
start_station_id         STRING     -- STRING to cover both eras
start_station_name       STRING
start_station_latitude   FLOAT64
start_station_longitude  FLOAT64
end_station_id           STRING
end_station_name         STRING
end_station_latitude     FLOAT64
end_station_longitude    FLOAT64
member_casual            STRING     -- 'member' | 'casual' (mapped for legacy)
bike_id                  STRING     -- legacy only
birth_year               INT64      -- legacy only
gender                   INT64      -- legacy only (0=unknown,1=male,2=female)
```

Consider adding provenance columns (e.g. `source_file`, `source_era`) so unified rows
remain traceable to the archive they came from.

## Repository structure

This repo is **new** — currently only this file, a README, and the
`cloud-bootstrap` skill. There is no pipeline code yet. When building it, keep things
discoverable; a reasonable layout:

```
.
├── CLAUDE.md                       # this file
├── README.md
├── .claude/
│   └── skills/
│       └── cloud-bootstrap/        # vendored credential-management skill (see below)
├── src/ or pipeline/               # extraction, normalization, Parquet conversion, load
├── schemas/                        # canonical schema + per-era mappings (JSON/SQL)
└── sql/                            # BigQuery DDL + the unifying UNION view/query
```

Prefer **Python 3** (pandas/pyarrow + `google-cloud-storage` and
`google-cloud-bigquery`) for the pipeline, matching the reference notebooks. Add a
`requirements.txt` when the first code lands.

## Cloud access (credentials)

Cloud authentication is managed by the **cloud-bootstrap** skill vendored at
`.claude/skills/cloud-bootstrap/`. It stores an encrypted GCP service-account key in
the repo so every Claude Code session can re-authenticate without manual steps.

- The encryption passphrase is provided via the **`GCP_CREDENTIALS_KEY`** environment
  variable (already set in this environment). It is the *passphrase*, **not** the key
  itself — never print it or commit it.
- **First-time setup has not run yet** (`.cloud-config.json` does not exist). To enable
  cloud access, ask: *"Set up GCP credentials for project `nyu-datasets`."* The skill
  will create/confirm the service account, encrypt the key to
  `.cloud-credentials.<git-email>.enc`, install a SessionStart auth hook, and append a
  `## Cloud Credentials` section to this file.
- Once set up, future sessions authenticate automatically; `gcloud`/`bq` are installed
  by the skill's SessionStart hook.
- **Never** commit a plaintext key (`credentials.json`); never widen IAM roles without
  asking the user first.

## Local environment notes

- `python3` (3.11) and `gh` are available. `gcloud`, `bq`, and `gsutil` are **not**
  installed until the cloud-bootstrap SessionStart hook runs — install them via the
  skill rather than ad hoc.
- Pin the dataset region to `US` for all BigQuery operations to match the existing
  `nyu-datasets.citibike` dataset.
- This is an ephemeral cloud workspace: commit and push anything worth keeping.

## Conventions

- Commit messages: imperative mood, concise, no trailing period.
- Make the schema reconciliation **explicit and documented** — the mappings above are
  the spec. If you change a mapping (e.g. how `rideable_type` is inferred for legacy
  rows), update this file in the same commit.
- Detect CSV layout from the header, not the filename year.
- Keep raw archives immutable in GCS; do transformations downstream (Parquet/BigQuery)
  so a reload is always reproducible from the bucket.

## Reference material

- Proof-of-concept notebooks: <https://github.com/ipeirotis-org/datasets/tree/main/Citibike>
  (`Copy_Citibike_Trips.ipynb` = legacy loader, `Copy_Citibike_Trips_After_2021.ipynb`
  = current loader, `BikeTypes.md` = bike-id → bike-type heuristics).
- Existing loaded data: BigQuery `nyu-datasets.citibike`.
- cloud-bootstrap skill: <https://github.com/ipeirotis/cloud-bootstrap>.
