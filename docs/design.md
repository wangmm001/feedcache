# feedcache Design (as of 2026-04-21)

---

## 1. Purpose

feedcache mirrors public internet top-list and metadata feeds into git-backed data repositories, and produces one derived cross-list domain aggregate. Each upstream source gets its own data repository; code lives in a single separate repository. Consumers do `git pull` on a data repo to get the latest snapshot without ever touching source code.

---

## 2. Repository topology

```
wangmm001/feedcache                        ← code (this repo)
│
├── wangmm001/umbrella-top1m-cache         ← mirror (daily)
├── wangmm001/tranco-top1m-cache           ← mirror (daily)
├── wangmm001/cloudflare-radar-rankings-cache  ← mirror (daily)
├── wangmm001/majestic-million-cache       ← mirror (daily)
├── wangmm001/public-suffix-list-cache     ← mirror (daily)
├── wangmm001/cloud-ip-ranges-cache        ← mirror (daily)
├── wangmm001/common-crawl-ranks-cache    ← mirror (daily cron, quarterly content)
│
├── wangmm001/top-domains-aggregate        ← derived (daily)
│
└── wangmm001/crux-top-lists-mirror        ← GitHub fork mirror (daily, not feedcache)
```

**Code/data separation rationale.** A `git pull` on a data repo gets only new snapshots — no code changes, no dependency noise. When feedcache itself is updated, all data repos pick up the new code automatically on their next cron run (the reusable workflow installs `feedcache@main` from GitHub at run time). Each data repo authenticates itself with its own `GITHUB_TOKEN`; no cross-repo credentials are needed except `CLOUDFLARE_RADAR_API_TOKEN` (Cloudflare Radar only).

---

## 3. Data repositories

| Repo | Role | Upstream | Cron (UTC) | Output layout |
|---|---|---|---|---|
| `umbrella-top1m-cache` | mirror | `s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip` | 03:30 | `data/YYYY-MM-DD.csv.gz`, `data/current.csv.gz` |
| `tranco-top1m-cache` | mirror | `tranco-list.eu` via `tranco` PyPI client | 03:45 | `data/YYYY-MM-DD_<versionID>.csv.gz`, `data/YYYY-MM-DD.version.txt`, `data/current.csv.gz`, `data/current.version.txt` |
| `cloudflare-radar-rankings-cache` | mirror | Cloudflare Radar `/radar/datasets/ranking_top_<N>` | 04:00 | `data/YYYY-MM-DD/top-{1000,10000,100000,1000000}.csv.gz`, `data/current/top-*.csv.gz` |
| `majestic-million-cache` | mirror | `downloads.majestic.com/majestic_million.csv` | 04:15 | `data/YYYY-MM-DD.csv.gz`, `data/current.csv.gz` |
| `public-suffix-list-cache` | mirror | `publicsuffix.org/list/public_suffix_list.dat` | 04:30 | `data/YYYY-MM-DD.dat.gz`, `data/current.dat.gz` |
| `cloud-ip-ranges-cache` | mirror | AWS/GCP/Azure/Cloudflare (see §5a) | 04:45 | `data/YYYY-MM-DD/{aws,gcp,azure,cloudflare-v4,cloudflare-v6}.{json,txt}.gz`, `data/current/…` |
| `common-crawl-ranks-cache` | mirror | CC `https://index.commoncrawl.org/graphinfo.json` + per-release `host/domain-ranks.txt.gz` | 04:30 | `data/{host,domain}/YYYY-MM-DD_<release-id>.csv.gz`, `data/{host,domain}/current.csv.gz`, `data/{host,domain}/current.release.txt`, `data/graphinfo.json` |
| `top-domains-aggregate` | derived | 5 sibling `current.csv.gz` files + PSL cache | 05:30 | `data/YYYY-MM-DD.csv.gz`, `data/current.csv.gz` |
| `crux-top-lists-mirror` | fork mirror | `zakird/crux-top-lists` | 05:00 | inherited from upstream (see §5c) |

All mirror repos share three conventions:

- **Append-only**: files are never deleted; `git log` is the change history.
- **Idempotent**: re-running the same day overwrites the day's file with the same bytes.
- **Deterministic gzip**: `mtime=0`, no embedded filename — identical content produces identical bytes, so `git diff --cached --quiet` reliably detects no-change days.

---

## 4. Code repository layout

```
feedcache/
├── pyproject.toml              # hatchling build; deps: requests, tranco, publicsuffixlist
├── README.md
├── LICENSE                     # MIT
├── docs/
│   └── design.md               # this file
├── feedcache/
│   ├── __init__.py
│   ├── __main__.py             # CLI dispatcher — maps source name → sources/*.run()
│   ├── common.py               # shared helpers (see §6)
│   └── sources/
│       ├── __init__.py
│       ├── umbrella.py
│       ├── tranco.py
│       ├── cloudflare_radar.py
│       ├── majestic.py
│       ├── public_suffix_list.py
│       ├── cloud_ip_ranges.py
│       └── aggregate_top_domains.py
├── tests/
│   ├── __init__.py
│   ├── test_common.py
│   ├── test_umbrella.py
│   ├── test_tranco.py
│   ├── test_cloudflare_radar.py
│   ├── test_majestic.py
│   ├── test_public_suffix_list.py
│   ├── test_cloud_ip_ranges.py
│   ├── test_aggregate_top_domains.py
│   └── test_cli.py
└── .github/
    └── workflows/
        ├── reusable-snapshot.yml   # called by all 7 feedcache-populated data repos
        └── test.yml                # runs pytest on every push / PR
```

The CLI entry point is `feedcache <source> <out_dir>`. `__main__.py` maintains a `SOURCES` dict mapping each source name string to its `run(out_dir: str) -> bool` function. A non-`True` return causes a non-zero exit code, which fails the GitHub Actions step.

---

## 5. Source types — three patterns

### 5a. Direct mirror (7 sources in 7 data repos)

Each source downloads its upstream, compresses deterministically, writes a dated file plus a `current.*` pointer, and returns. All network I/O happens before any file is written — failure mid-download leaves the data directory unchanged.

**umbrella** (`umbrella.py`)
- Upstream: `https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip`
- Downloads the ZIP to a tempfile outside `data/`, extracts the single `.csv` member into memory, gzips to `data/YYYY-MM-DD.csv.gz`, updates `data/current.csv.gz`.
- Format: two-column no-header CSV (`rank,domain`), rank 1–1 000 000 in order.

**tranco** (`tranco.py`)
- Upstream: `https://tranco-list.eu/` via the `tranco` PyPI client (`Tranco(cache_dir="/tmp/feedcache-tranco-cache")`).
- Reads `latest.list_id`; if it matches `data/current.version.txt`, returns early (no new data today).
- Writes `data/YYYY-MM-DD_<versionID>.csv.gz` (rank,domain no-header CSV), `data/YYYY-MM-DD.version.txt`, and both `current.*` files.
- The version ID in the filename makes every snapshot self-describing and reproducible.

**cloudflare-radar** (`cloudflare_radar.py`)
- Upstream: `https://api.cloudflare.com/client/v4/radar/datasets/ranking_top_{bucket}` for buckets 1000, 10000, 100000, 1000000.
- Requires `CLOUDFLARE_RADAR_API_TOKEN` env var (Bearer auth via `requests`, no SDK).
- All 4 buckets fetched to memory before writing — if any fails, nothing is written (atomic snapshot semantics).
- Response format: single-column CSV with a `domain` header; entries are **unordered** (bucket membership only, no ordinal rank within the bucket). Cloudflare updates weekly; daily cron with deterministic gzip means unchanged weeks produce no commits.
- Writes `data/YYYY-MM-DD/top-<N>.csv.gz` and `data/current/top-<N>.csv.gz` for each of the four bucket sizes.

**majestic** (`majestic.py`)
- Upstream: `https://downloads.majestic.com/majestic_million.csv`
- 12-column CSV with header. The `GlobalRank` and `Domain` columns are the ones consumed by the aggregator; the full row is stored verbatim.
- Downloads to tempfile, reads bytes, gzips to `data/YYYY-MM-DD.csv.gz`, updates `data/current.csv.gz`.

**public-suffix-list** (`public_suffix_list.py`)
- Upstream: `https://publicsuffix.org/list/public_suffix_list.dat`
- Mozilla Public Suffix List in `.dat` format. Stored as-is (no CSV transformation).
- Writes `data/YYYY-MM-DD.dat.gz`, updates `data/current.dat.gz`.
- Consumed at runtime by `aggregate_top_domains.py` for eTLD+1 normalization.

**common-crawl-ranks** (`common_crawl_ranks.py`)
- Upstream discovery: `https://index.commoncrawl.org/graphinfo.json` — JSON array of releases, newest first. The source reads `releases[0]["id"]` (e.g. `cc-main-2026-jan-feb-mar`).
- Idempotence: if `data/host/current.release.txt` already matches the latest release id, the run refreshes only `data/graphinfo.json` and short-circuits. Common Crawl publishes roughly one release per quarter, so daily cron short-circuits on ~90% of days.
- Per-release fetch: `https://data.commoncrawl.org/projects/hyperlinkgraph/{release}/{host,domain}/{release}-{host,domain}-ranks.txt.gz`. Streamed + Top-1M-truncated in a single pass so only the first ~15–25 MB per level is actually transferred (raw files are 2.5–5.6 GB compressed).
- Output per run: `data/host/YYYY-MM-DD_{release-id}.csv.gz` + `data/domain/YYYY-MM-DD_{release-id}.csv.gz`, plus their `current.csv.gz` / `current.release.txt` siblings, plus `data/graphinfo.json`.
- Columns: `rank,harmonicc_val,pr_pos,pr_val,{host,domain}` — upstream `#host_rev` is reversed (`com.facebook.www` → `www.facebook.com`).
- No auth; no new secrets.

**cloud-ip-ranges** (`cloud_ip_ranges.py`)
- Four providers combined in one atomic snapshot under a single dated directory:
  - **AWS**: `https://ip-ranges.amazonaws.com/ip-ranges.json` — direct JSON download.
  - **GCP**: `https://www.gstatic.com/ipranges/cloud.json` — direct JSON download.
  - **Azure**: two-hop HTML scrape — fetches `microsoft.com/en-us/download/confirmation.aspx?id=56519`, regex-extracts the `download.microsoft.com/download/…/ServiceTags_Public_<YYYYMMDD>.json` URL, then downloads it.
  - **Cloudflare**: separate plain-text lists at `cloudflare.com/ips-v4` and `cloudflare.com/ips-v6`.
- All five payloads are fetched to memory before any disk write; any failure aborts cleanly.
- Output per day: `data/YYYY-MM-DD/{aws.json.gz, gcp.json.gz, azure.json.gz, cloudflare-v4.txt.gz, cloudflare-v6.txt.gz}` plus a `data/current/` mirror.

### 5b. Derived aggregate (1 source, 1 data repo)

**aggregate-top-domains** (`aggregate_top_domains.py`) → `top-domains-aggregate`

This is **not a mirror**. It fetches `current.csv.gz` from five sibling data repos over HTTPS, normalizes every domain to its registrable name (eTLD+1), computes a cross-list score, and writes one CSV per day.

**Inputs (fetched at run time):**

| List | URL | Rank semantics |
|---|---|---|
| umbrella | `…/umbrella-top1m-cache/…/current.csv.gz` | ordinal 1–1 000 000 |
| tranco | `…/tranco-top1m-cache/…/current.csv.gz` | ordinal 1–1 000 000 |
| majestic | `…/majestic-million-cache/…/current.csv.gz` | ordinal (`GlobalRank`) 1–1 000 000 |
| cloudflare-radar | `…/cloudflare-radar-rankings-cache/…/current/top-1000000.csv.gz` | unordered; all entries assigned synthetic rank 1 000 000 |
| crux | `…/crux-top-lists-mirror/…/data/global/current.csv.gz` | bucket (1000/10000/100000/1000000); best bucket per origin used |

Plus PSL from `…/public-suffix-list-cache/…/current.dat.gz`.

**PSL normalization (`_normalize`):**

1. Strip leading `www.` from host.
2. For CrUX origins (scheme://host format): extract `hostname` via `urlparse` before step 1.
3. Call `psl.privatesuffix(host)` (from `publicsuffixlist` PyPI package) to reduce to eTLD+1.
4. If the result is `None` (host is itself a public suffix or unresolvable), fall back to the stripped host.
5. Multiple origins or subdomains that map to the same registrable domain are merged; the best (lowest) rank is kept for RRF scoring.

**RRF scoring (v2.2):**

```
score_contribution = 1 / (60 + rank)
domain_score = sum of contributions across all lists where domain appears
```

The constant `RRF_K = 60` damps rank-1 dominance: the score ratio between rank 1 and rank 1000 is ~18× rather than 1000× (which would be the case with K=0). This is the "smoothed RRF" formula introduced in v2.2.

**Output format** (`domain,count,score,lists`, 4 columns):

- `domain`: registrable name (eTLD+1), e.g. `google.com`
- `count`: number of lists (1–5) where the domain appears
- `score`: sum of RRF contributions, formatted to 6 decimal places
- `lists`: `|`-separated sorted list of source names, e.g. `crux|tranco|umbrella`
- Rows sorted: `count DESC`, `score DESC`, `domain ASC`

Written to `data/YYYY-MM-DD.csv.gz`; `data/current.csv.gz` updated via `update_current`.

**Aggregator version history:**

| Version | Change |
|---|---|
| v1 | binary count only — 3-col output (`domain,count,lists`) |
| v2 | added `score = sum(1/rank_i)` RRF column — 4-col output |
| v2.1 | added PSL normalization (fetches `public-suffix-list-cache` at runtime) |
| v2.2 | smoothed score to `sum(1/(60 + rank_i))` to damp rank-1 dominance |

### 5c. GitHub fork mirror (1 repo, no feedcache involvement)

**crux-top-lists-mirror** → fork of `zakird/crux-top-lists`

The Chrome UX Report (CrUX) top-1M data is produced by querying Google BigQuery; `zakird/crux-top-lists` already does that work and publishes monthly gzipped CSVs. Rather than re-implement BigQuery access, `crux-top-lists-mirror` is a plain GitHub fork that stays in sync via a daily workflow:

```yaml
# .github/workflows/sync.yml in crux-top-lists-mirror
- run: gh repo sync wangmm001/crux-top-lists-mirror --source zakird/crux-top-lists
```

Characteristics:
- The tree is a 1:1 copy of upstream at the time of the last sync (except for the addition of `sync.yml` itself — the fork's HEAD SHA therefore diverges from upstream by exactly one commit).
- All workflows inherited from `zakird/crux-top-lists` are disabled; only `sync.yml` runs.
- No feedcache code or reusable workflow is involved.
- Data layout (inherited): `data/global/YYYYMM.csv.gz`, `data/global/current.csv.gz`, `data/country/<cc>/YYYYMM.csv.gz`. CrUX releases monthly (typically the second Tuesday); `current.csv.gz` is updated after each monthly download.
- The `aggregate-top-domains` source reads `crux-top-lists-mirror/data/global/current.csv.gz` over HTTPS; the CrUX rank field is a bucket value (1000/10000/100000/1000000), not an ordinal.

---

## 6. Shared infrastructure

### `common.py` helpers

| Function | Signature | Purpose |
|---|---|---|
| `today_utc_date` | `() -> str` | Returns `YYYY-MM-DD` in UTC. Centralizes timezone handling. |
| `deterministic_gzip` | `(src_bytes: bytes, dest: Path) -> None` | `gzip.compress(..., mtime=0)` — no timestamp or filename embedded. Same input always produces the same bytes. Writes via atomic temp-then-rename. |
| `write_if_changed` | `(content: bytes, dest: Path) -> bool` | Byte-compares against existing file; writes only if different. Returns `True` if written. Used for sidecar `.version.txt` files. |
| `update_current` | `(directory: Path, pattern: str, current_name: str) -> Path or None` | Glob-sorts files matching `pattern`, copies the lexicographically largest to `current_name`. Used by all mirror sources. |
| `download_to` | `(url: str, dest: Path, timeout: int) -> Path` | Streaming `requests.get` into a temp file, then atomic rename. |

### reusable-snapshot.yml and the cron pattern

`feedcache/.github/workflows/reusable-snapshot.yml` is called by each of the 8 feedcache-populated data repos. It accepts one input (`source`) and one optional secret (`CLOUDFLARE_RADAR_API_TOKEN`):

```yaml
# Steps condensed:
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
  with: { python-version: "3.11" }          # no pip cache (data repos have no pyproject.toml)
- run: pip install "git+https://github.com/wangmm001/feedcache.git@main"
- run: feedcache ${{ inputs.source }} data/
  env: { CLOUDFLARE_RADAR_API_TOKEN: ${{ secrets.CLOUDFLARE_RADAR_API_TOKEN }} }
- run: |
    git config user.name "feedcache-bot"
    git config user.email "feedcache-bot@users.noreply.github.com"
    git add data/
    if git diff --cached --quiet; then exit 0; fi
    git commit -m "Snapshot: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push
```

Each data repo's `cron.yml` is approximately 10 lines:

```yaml
name: daily
on:
  schedule: [{ cron: "30 3 * * *" }]   # adjust per-repo
  workflow_dispatch:
permissions:
  contents: write
jobs:
  snapshot:
    uses: wangmm001/feedcache/.github/workflows/reusable-snapshot.yml@main
    with: { source: umbrella }
    # secrets: { CLOUDFLARE_RADAR_API_TOKEN: ${{ secrets.CLOUDFLARE_RADAR_API_TOKEN }} }
    # (uncomment for cloudflare-radar only)
```

`permissions: contents: write` must be declared in the calling workflow because reusable workflow permissions are a subset of the caller's permissions.

The `pip install git+https://...@main` pattern means feedcache updates propagate automatically to all data repos on their next cron run without any version pinning in the data repos.

### Secrets model

- `GITHUB_TOKEN` (automatic): used by every data repo to `git push` to itself. No PAT needed.
- `CLOUDFLARE_RADAR_API_TOKEN` (manual secret): stored only in `cloudflare-radar-rankings-cache`. Passed through the reusable workflow's optional `secrets` parameter to the `cloudflare-radar` source.
- No other secrets. The PSL, Umbrella, Tranco, Majestic, cloud-IP-ranges, and aggregate sources all use unauthenticated HTTPS.

---

## 7. Known deviations from the original plan

These are issues discovered during implementation and how each was resolved:

- **`cloudflare` SDK 4.3.1 circular-import bug.** The official Python SDK raised a circular-import error on import. Resolution: fell back to `requests` + direct REST endpoint. The SDK is no longer a dependency.
- **`Tranco(cache=False)` invalid kwarg.** The `tranco` PyPI client rejected `cache=False` as an unknown keyword argument. Resolution: use `Tranco(cache_dir="/tmp/feedcache-tranco-cache")` — a temp directory that persists for the duration of the runner job.
- **Cloudflare Radar `/radar/ranking/top?limit=N` max limit 100.** The original plan used the ranked top endpoint, which caps at 100 results per call. Resolution: switched to `/radar/datasets/ranking_top_<N>`, which returns the full unordered bucket as a plain CSV download. The trade-off is that entries within a bucket have no ordinal rank; the aggregator assigns `UNORDERED_RANK = 1_000_000` to all Cloudflare Radar entries.
- **Umbrella temp file inside `data/`.** An early draft wrote the zip to `data/<tmp>.zip`, which would get picked up by `git add data/`. Resolution: use `tempfile.NamedTemporaryFile` outside `data/` (system temp directory).
- **Tranco `.version.txt` sidecar written with `open()`.** This bypassed the atomic rename and could leave a partial file on runner crash. Resolution: switched to `write_if_changed`, which uses temp-then-rename.
- **`reusable-snapshot.yml` had `cache: "pip"`.** The `actions/setup-python` pip cache requires a `requirements.txt` or `pyproject.toml` in the checked-out repo. Data repos contain neither, so the cache step errored. Resolution: removed `cache: "pip"` from the reusable workflow. (The code repo's own `test.yml` may still use it since `feedcache` has a `pyproject.toml`.)
- **Workflow commit timestamp lacked seconds.** Original format was `%Y-%m-%dT%H:%MZ`, which meant two runs in the same minute produced identical commit messages. Resolution: use `%Y-%m-%dT%H:%M:%SZ` (with `%S`).

---

## 8. Known limitations (scope choices, not bugs)

- **AWS syncToken frequency.** AWS IP ranges can update multiple times per week (each update increments `syncToken`). The daily cron catches at most one snapshot per day; intra-day changes are missed.
- **No Cloudflare Radar ordered top-100.** The `/radar/ranking/top?limit=N` endpoint (max N=100, returns ordered) is not used. All Cloudflare Radar data comes from the unordered bucket files.
- **No historical backfill for Umbrella, Tranco, Majestic, or Cloudflare Radar.** Repositories contain data from the first cron run onward. Historical Umbrella and Cloudflare data is not available upstream; Tranco historical access (`/list/date/YYYYMMDD/full`) and Majestic historical data were out of scope.
- **No CrUX BigQuery direct access.** CrUX monthly data comes via `zakird/crux-top-lists` fork sync. The feedcache project does not query BigQuery directly.
- **No IDN reconciliation.** Punycode (`xn--...`) and Unicode domain representations appear inconsistently across sources. No normalization is applied; the same domain may appear as separate entries.
- **No time-series aggregate (v2.3).** The `top-domains-aggregate` repo stores one snapshot per day but no trend analysis or month-over-month comparison is implemented.

---

## 9. Future extensions (not implemented)

- **v2.3 top-domains-trends.** Monthly snapshot archive of the aggregate output; CrUX-only monthly backfill from 2025-01 using `crux-top-lists-mirror` historical data.
- **Tranco historical backfill.** The Tranco API supports `/list/date/YYYYMMDD/full` for past dates; a one-time backfill pass could populate the cache back to a chosen start date.
- **Additional sources under consideration:** CISA Known Exploited Vulnerabilities (KEV), OSV vulnerability data, `hugovk/top-pypi-packages` fork, RIR (ARIN/RIPE/APNIC/LACNIC/AfriNIC) IP allocation data, abuse.ch blocklists.
- **More frequent cloud-IP-ranges polling.** A 6-hourly cron for `cloud-ip-ranges-cache` would reduce the AWS syncToken lag.

---

## 10. Repository URLs

All ten repos under `wangmm001`:

- `https://github.com/wangmm001/feedcache` — code
- `https://github.com/wangmm001/umbrella-top1m-cache` — data
- `https://github.com/wangmm001/tranco-top1m-cache` — data
- `https://github.com/wangmm001/cloudflare-radar-rankings-cache` — data
- `https://github.com/wangmm001/majestic-million-cache` — data
- `https://github.com/wangmm001/public-suffix-list-cache` — data
- `https://github.com/wangmm001/cloud-ip-ranges-cache` — data
- `https://github.com/wangmm001/common-crawl-ranks-cache` — data
- `https://github.com/wangmm001/top-domains-aggregate` — derived data
- `https://github.com/wangmm001/crux-top-lists-mirror` — fork mirror
