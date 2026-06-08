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
Citibike S3 archives (ZIP of CSVs)  —  s3.amazonaws.com/tripdata/
        │  Stage 1: mirror byte-for-byte (idempotent)
        ▼
GCS  gs://citibike-archive/raw/zip/         ← immutable, write-once landing zone
        │  Stage 2: extract — detect layout per CSV (header), normalize, type
        ▼
GCS  .../tripdata/parquet/  .../rides/parquet/  (+ jc/…)    typed Parquet
        │  Stage 3: external tables, then the unifying UNION
        ▼
BigQuery  nyu-datasets.citibike
        │  trips_2013_2021 + trips_2021_now (+ JC)  ──reconcile eras──►
        ▼
   trips_unified  (canonical superset view; materialized as `m_trips_unified`)
```

Stage 1 (mirror raw ZIPs into GCS before any parsing) makes the pipeline
reproducible: Citibike re-publishes/renames archives, so the extract reads the
frozen copy in `raw/zip/`, never live S3.

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

Citibike publishes trip data as ZIP files under
**`https://s3.amazonaws.com/tripdata/`** (167 archives as of mid-2026):

- **Annual `YYYY-citibike-tripdata.zip`** for 2013–2023.
- **Monthly `YYYYMM-citibike-tripdata.zip`** (occasionally `.csv.zip`) from 2024-01.
- **Jersey City `JC-YYYYMM-citibike-tripdata.csv.zip`** (2015 → present), published
  separately and detected by the `JC-` prefix.

Two changes are independent: the **packaging** went annual → monthly in 2024, but the
**CSV layout** changed in early **2021** — the 2021 annual archive contains *both*
(Jan = legacy, Feb+ = current). So always detect the layout from the CSV header, never
the year. Annual archives also sometimes ship the same month twice (root + nested
folder), which the extractor de-duplicates.

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

Implemented as the view **`nyu-datasets.citibike.trips_unified`** (the original
`all_trips` is left intact). It is the **superset** of both eras — era-specific fields
are `NULL` where the source did not provide them:

```
ride_id                  STRING     -- current era only
rideable_type            STRING     -- current era; NULL legacy (inferable via bike_id)
start_time               TIMESTAMP
stop_time                TIMESTAMP
trip_duration_seconds    INT64      -- legacy: explicit seconds; current: computed
start_station_id         STRING     -- STRING to cover both eras
start_station_name       STRING
start_station_latitude   FLOAT64
start_station_longitude  FLOAT64
end_station_id           STRING
end_station_name         STRING
end_station_latitude     FLOAT64
end_station_longitude    FLOAT64
member_casual            STRING     -- 'member' | 'casual' (legacy mapped from user_type)
bike_id                  STRING     -- legacy only
birth_year               INT64      -- legacy only
gender                   INT64      -- legacy only (0=unknown,1=male,2=female)
distance_meters          FLOAT64    -- ST_DISTANCE(start, end) station points
region                   STRING     -- 'NYC' | 'JC'
source_era               STRING     -- 'legacy' | 'current'
source_file              STRING     -- GCS Parquet object the row came from (_FILE_NAME)
```

This improves on `all_trips`, which recomputes duration in *minutes*, drops
`ride_id`/`bike_id`/`birth_year`/`gender`, and carries no provenance. The
machine-readable spec lives in `schemas/canonical.json`.

## Repository structure

```
.
├── CLAUDE.md  README.md  requirements.txt  Makefile
├── .claude/skills/cloud-bootstrap/     # vendored credential-management skill
├── src/citibike_pipeline/
│   ├── config.py          # all resource names (project, bucket, prefixes, tables)
│   ├── schemas.py         # column normalization, era detection, typed Parquet schemas
│   ├── transform.py       # raw CSV (strings) -> typed Arrow table (pure, unit-tested)
│   ├── mirror_raw.py      # Stage 1: Citibike S3 -> gs://…/raw/zip/ (idempotent)
│   ├── extract.py         # Stage 2: raw ZIPs in GCS -> typed Parquet in GCS
│   ├── load_bigquery.py   # Stage 3: external tables + the unified view/table
│   ├── gcsio.py           # thin GCS helpers
│   └── selftest.py        # `make selftest` — transform core, no cloud
├── sql/trips_unified.sql  # the unifying UNION (human-readable; generated by load_bigquery)
└── schemas/canonical.json # machine-readable canonical schema
```

Python 3.11 (pandas/pyarrow + `google-cloud-storage`/`google-cloud-bigquery`), matching
the reference notebooks. Run `make install` then `make selftest`. The package runs from
`src/` via `PYTHONPATH=src` (set by the `Makefile`).

## Pipeline

Three stages, each a CLI module run via the `Makefile`. Cloud auth is automatic
(cloud-bootstrap SessionStart hook), so the modules just use the default clients.

| Stage | Command | What it does |
|---|---|---|
| 1 — mirror | `make mirror` / `mirror-jc` | Byte-for-byte copy of every Citibike `*.zip` into `gs://citibike-archive/raw/zip/`. Idempotent (skips files already present with matching size). **Downstream reads raw from here, never S3.** |
| 2 — extract | `make extract` / `extract-jc` | For each raw ZIP, detect each CSV's layout from its header, normalize + type, write Parquet to the region/era prefix. Chunked, so multi-GB annual CSVs stay in memory budget. |
| 3 — load | `make unify` (`external` + `view`) | (Re)create external tables over the Parquet and deploy `trips_unified`. `make materialize` snapshots it into native `m_trips_unified`. |

**Fidelity to the reference notebooks.** Stage 2 follows `Copy_Citibike_Trips*.ipynb`
where it matters — the column-rename map, the `NULL`/`\N`→null and trailing-`.0`
cleaning, and the per-era PyArrow schemas — so its Parquet is a drop-in for the existing
`trips_2013_2021` / `trips_2021_now` tables. It *improves* on them with the raw-mirror
step, header-based era detection (vs. moving files by hand), de-duplication of doubled
files inside annual archives, chunked streaming, and Jersey City coverage. `make
selftest` pins these rules.

**NYC Parquet already exists** (produced by those notebooks); the default flow reuses it
and only extracts JC. Full NYC re-extraction from raw works too — `extract._csv_members`
de-duplicates the doubled files in annual archives (nested copies, and the combined-vs-shard
duplication that all of 2013 and 2018 ship) so no month is double-counted.

## Cloud access (credentials)

Cloud authentication is managed by the **cloud-bootstrap** skill vendored at
`.claude/skills/cloud-bootstrap/`. It stores an encrypted GCP service-account key in
the repo so every Claude Code session can re-authenticate without manual steps.

- The encryption passphrase is provided via the **`GCP_CREDENTIALS_KEY`** environment
  variable (already set in this environment). It is the *passphrase*, **not** the key
  itself — never print it or commit it.
- **Setup is complete** (`.cloud-config.json` is committed). Sessions authenticate
  automatically via the SessionStart hook — see the **Cloud Credentials** section below
  for the service account, granted roles, and how to add teammates or escalate access.
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
- A materialized view/table mirrors its view's name with an `m_` prefix
  (`trips_unified` → `m_trips_unified`), matching the dataset's `all_trips` / `m_all_trips`.

## Reference material

- Proof-of-concept notebooks: <https://github.com/ipeirotis-org/datasets/tree/main/Citibike>
  (`Copy_Citibike_Trips.ipynb` = legacy loader, `Copy_Citibike_Trips_After_2021.ipynb`
  = current loader, `BikeTypes.md` = bike-id → bike-type heuristics).
- Existing loaded data: BigQuery `nyu-datasets.citibike`.
- cloud-bootstrap skill: <https://github.com/ipeirotis/cloud-bootstrap>.

## Cloud Credentials

> Provisioned by the **cloud-bootstrap** skill (first-time setup). Sessions authenticate
> automatically — no manual steps.

- **Provider / project:** GCP, `nyu-datasets`.
- **Service account:** `claude-agent@nyu-datasets.iam.gserviceaccount.com` — a dedicated
  agent identity, kept separate from the pipeline's `citibike-sa`.
- **Granted roles** (least privilege for this pipeline):

  | Role | Why |
  |---|---|
  | `roles/storage.objectAdmin` | Read/write raw CSV + Parquet in `gs://citibike-archive` |
  | `roles/bigquery.dataEditor` | Create/replace and load tables in `nyu-datasets.citibike` |
  | `roles/bigquery.jobUser` | Run BigQuery load/query jobs |

- **Per-user encrypted keys:** multi-user setup — each member has their own
  `.cloud-credentials.<git-email>.enc`. In Claude Code on the Web this workspace's git
  identity is `noreply@anthropic.com`, so the committed key is
  `.cloud-credentials.noreply@anthropic.com.enc`. Keys are AES-256-CBC (`openssl`); the
  passphrase lives only in the `GCP_CREDENTIALS_KEY` env var, never in the repo.
- **How auth happens:** the SessionStart hook `.claude/hooks/cloud-auth.sh` (wired in
  `.claude/settings.json`) installs `gcloud`, decrypts the key with `GCP_CREDENTIALS_KEY`,
  runs `gcloud auth activate-service-account`, and sets the project. The plaintext key is
  written to `/tmp` and deleted immediately.
- **TLS note:** this sandbox runs a TLS-inspecting egress proxy, so the hook points
  `gcloud`/`bq` at the system CA bundle (`core/custom_ca_certs_file` →
  `/etc/ssl/certs/ca-certificates.crt`). Python clients honor the pre-set
  `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE`.
- **Add a teammate:** they open the repo in Claude Code, set their own
  `GCP_CREDENTIALS_KEY`, and ask to "set up cloud credentials"; the skill runs its
  *add-team-member* flow (a new key on the same SA, encrypted with their passphrase).
  Their GCP account needs `roles/iam.serviceAccountKeyAdmin` on the project.
- **Escalate permissions:** if a command returns 403, ask the user to grant the specific
  role (the skill's *permission-escalation* flow names it). Do **not** widen roles unasked.
- **Verified at setup:** GCS bucket listing, BigQuery table listing, and a trivial query
  all succeeded. `nyu-datasets.citibike` already contains `trips_2013_2021` and
  `trips_2021_now` (external) plus a unified **`all_trips`** view — the prior art this
  pipeline reproduces.
