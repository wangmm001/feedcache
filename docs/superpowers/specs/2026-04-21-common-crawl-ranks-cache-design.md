# 2026-04-21 — `common-crawl-ranks-cache` design

Mirror Common Crawl's official host-level and domain-level web-graph ranks into a new feedcache data repo, Top-1M per file, following the established feedcache mirror pattern.

## 1. Goal

Produce two continuously-refreshed CSV files — `host-ranks` and `domain-ranks` — that carry Common Crawl's published Harmonic Centrality and PageRank signals for the Top 1,000,000 entities per release, in a layout consumable by the same scripts that read the other feedcache mirrors (`umbrella-top1m-cache`, `tranco-top1m-cache`, etc.).

This is the **first-phase MVP** of Common Crawl integration. `top-domains-aggregate` is **not** modified in this phase; deciding whether and how to fold the CC signal into the cross-list aggregate is explicitly out of scope (see §12).

## 2. Scope

**In scope**
- New feedcache source module `feedcache/sources/common_crawl_ranks.py` exposing `run(out_dir) -> bool`.
- One new CLI subcommand: `feedcache common-crawl-ranks <out_dir>`.
- New data repository `wangmm001/common-crawl-ranks-cache` with LICENSE, README, `data/` tree, `.github/workflows/cron.yml` that calls the existing feedcache `reusable-snapshot.yml`.
- Top-1M truncation per release, host- and domain-level, with `current.csv.gz` pointers and a plain-text `current.release.txt` sidecar.
- Unit tests at `tests/test_common_crawl_ranks.py`, fixtured against tiny synthetic `graphinfo.json` and ranks files.
- Update of `feedcache/docs/design.md` §3 and §5a to register the new source (deferred — part of the implementation plan, not this spec).

**Out of scope**
- Full-resolution dump (CC host-ranks is ~5.6 GB compressed; not viable in git; see §11).
- Historical backfill of past CC webgraph releases (each release is ~8 GB compressed on upstream; only the current release is mirrored).
- Self-computed PageRank or Harmonic Centrality from raw edge lists.
- URL-level CC-Index or cluster.idx mirroring.
- Integration with `top-domains-aggregate` (PSL normalization, cross-list scoring changes).

## 3. Repository topology

Two repos, aligned with the existing feedcache topology:

- **Code**: extends `wangmm001/feedcache` (no new code repo).
- **Data**: new `wangmm001/common-crawl-ranks-cache` alongside the six existing mirror data repos.

```
wangmm001/feedcache                          ← code (add 1 source)
│
└── wangmm001/common-crawl-ranks-cache       ← NEW data repo (this spec)
```

`top-domains-aggregate`, `crux-top-lists-mirror`, and the other five mirror repos are untouched.

## 4. Data layout

```
common-crawl-ranks-cache/
├── LICENSE
├── README.md                                 # documents schema + URLs (§5, §6)
├── .github/
│   └── workflows/
│       └── cron.yml                          # calls feedcache reusable-snapshot.yml
└── data/
    ├── host/
    │   ├── YYYY-MM-DD_<release-id>.csv.gz    # e.g. 2026-04-21_cc-main-2026-jan-feb-mar.csv.gz
    │   ├── current.csv.gz                    # lexicographic-max copy via update_current
    │   └── current.release.txt               # plain text: the release id only
    ├── domain/
    │   ├── YYYY-MM-DD_<release-id>.csv.gz
    │   ├── current.csv.gz
    │   └── current.release.txt
    └── graphinfo.json                        # verbatim copy of upstream index at run time
```

### Why this shape

- **Two subdirectories** (`host/`, `domain/`) because host and domain rank lists are **different granularities** with different entity sets; consumers typically want one or the other. Keeping them separate avoids having to encode "type" in the filename.
- **`YYYY-MM-DD_<release-id>.csv.gz`** filename mirrors tranco's `YYYY-MM-DD_<versionID>.csv.gz` convention: self-describing (you can tell run day + upstream release from the filename alone), lexicographically sortable by run day so `update_current` picks the newest.
- **`current.release.txt`** is the idempotence key (see §6). Keeping it as a plain file — not a JSON field or filename parse — keeps the early-return check trivial.
- **`graphinfo.json`** snapshot is written on every run (cheap — a few KB). It serves both as an audit trail and as a debug aid if a release transition misbehaves.

## 5. Output CSV schema

Header-first, comma-separated, UTF-8. Schemas differ per level (host is 5 columns, domain is 6):

```
# host/*.csv.gz
rank,harmonicc_val,pr_pos,pr_val,host
1,3.7549092E7,5,0.004897432273872421,www.facebook.com

# domain/*.csv.gz
rank,harmonicc_val,pr_pos,pr_val,domain,n_hosts
1,3.053703E7,3,0.009072779578696339,facebook.com,3356
```

| Column | Source | Transform | Present in |
|---|---|---|---|
| `rank` | upstream `#harmonicc_pos` | integer, 1 to 1,000,000, ascending | host + domain |
| `harmonicc_val` | upstream `#harmonicc_val` | passed through unchanged (scientific notation preserved) | host + domain |
| `pr_pos` | upstream `#pr_pos` | integer, passed through | host + domain |
| `pr_val` | upstream `#pr_val` | passed through unchanged | host + domain |
| `host` (host file) or `domain` (domain file) | upstream `#host_rev` | split by `.`, reversed, rejoined (`com.facebook.www` → `www.facebook.com`) | host + domain |
| `n_hosts` | upstream `#n_hosts` | passed through (count of distinct hosts aggregated into this registrable domain) | **domain only** |

Rows sorted by `rank` ascending. Header row included.

### Upstream format for reference (from an actual fetch)

Host file — 5 columns:

```
#harmonicc_pos	#harmonicc_val	#pr_pos	#pr_val	#host_rev
1	3.7549092E7	5	0.004897432273872421	com.facebook.www
2	3.7300396E7	4	0.006354617185491388	com.googleapis.fonts
```

Domain file — 6 columns (extra trailing `#n_hosts`):

```
#harmonicc_pos	#harmonicc_val	#pr_pos	#pr_val	#host_rev	#n_hosts
1	3.053703E7	3	0.009072779578696339	com.facebook	3356
2	3.0458862E7	2	0.01547277614257803	com.googleapis	2899
```

Tab-separated; header prefixed with `#`. Confirmed by `curl` + `gunzip -c | head` against `cc-main-2025-26-dec-jan-feb` (host) and `cc-main-2026-jan-feb-mar` (domain) on 2026-04-21.

> **Errata (2026-04-21):** Initial drafts of this spec assumed both files shared the host's 5-column schema. The live workflow exposed the extra `#n_hosts` column on the domain side and a hotfix generalized `_truncate_and_transform` to accept arbitrary extra columns. The Output CSV schema table above was updated correspondingly so that the `domain` file emits `n_hosts` as a 6th column.

### Why comma-separated with header

Other feedcache mirrors (umbrella, tranco, majestic) are all CSV; keeping the same delimiter lets any downstream tool treat the CC files identically. Header is included because the 5 columns aren't self-evident from values alone (two `pos` columns, two `val` columns). This differs from tranco/umbrella (no header) but matches majestic (header).

## 6. Upstream discovery + idempotence

### Discovery

Single source of truth: `https://index.commoncrawl.org/graphinfo.json`. Returns a JSON array of release objects, newest first. Each object has:

```json
{
  "id": "cc-main-2026-jan-feb-mar",
  "crawls": ["CC-MAIN-2026-04", "CC-MAIN-2026-08", "CC-MAIN-2026-12"],
  "index": "https://data.commoncrawl.org/projects/hyperlinkgraph/cc-main-2026-jan-feb-mar/index.html",
  "location": "s3://commoncrawl/projects/hyperlinkgraph/cc-main-2026-jan-feb-mar/",
  "stats": { "host": { "nodes": ..., "arcs": ... }, "domain": { ... } }
}
```

The source takes `releases[0]["id"]` as the latest release id.

### URL construction

```python
BASE = "https://data.commoncrawl.org/projects/hyperlinkgraph"
HOST_URL   = f"{BASE}/{release_id}/host/{release_id}-host-ranks.txt.gz"
DOMAIN_URL = f"{BASE}/{release_id}/domain/{release_id}-domain-ranks.txt.gz"
```

Confirmed file existence + `content-length` via `curl -I` on 2026-04-21.

### Idempotence

```python
release_id = fetch_graphinfo()[0]["id"]
current = out / "host" / "current.release.txt"
if current.exists() and current.read_text().strip() == release_id:
    return True  # no-op, upstream unchanged
```

CC publishes roughly one release per quarter. Daily cron will short-circuit here on ~90% of days — no graph downloads, no commits. Mirrors tranco's version-id early-return pattern.

One snapshot of `graphinfo.json` is always written (even on no-op runs), so `data/graphinfo.json` stays fresh and consumers can cheaply poll it to learn when a new release landed.

## 7. Streaming truncation

The raw `host-ranks.txt.gz` is 5.6 GB and `domain-ranks.txt.gz` is 2.5 GB (confirmed 2026-04-21 via `curl -I`). Downloading them whole would:

1. Blow through GitHub Actions runner disk (~14 GB free after checkout + Python + deps).
2. Pointlessly transfer gigabytes of data we throw away.

The source therefore streams-and-truncates:

```python
TOP_N = 1_000_000

with requests.get(URL, stream=True, timeout=600) as r:
    r.raise_for_status()
    with gzip.GzipFile(fileobj=r.raw) as gz:
        reader = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        header = next(reader)
        assert header.startswith("#harmonicc_pos"), f"unexpected header: {header!r}"
        out_buf = io.StringIO()
        w = csv.writer(out_buf, lineterminator="\n")
        w.writerow(["rank", "harmonicc_val", "pr_pos", "pr_val", "host"])  # "domain" for domain file
        for i, line in enumerate(reader, start=1):
            if i > TOP_N:
                break
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 5:
                raise RuntimeError(f"malformed line {i}: {line!r}")
            hc_pos, hc_val, pr_pos, pr_val, host_rev = fields
            host = ".".join(reversed(host_rev.split(".")))
            w.writerow([hc_pos, hc_val, pr_pos, pr_val, host])
```

Breaking out of the loop closes the HTTP connection (via `with requests.get(...)`). The gzip decompressor stops pulling from the socket; only the bytes needed to produce the first 1,000,001 lines are actually transferred — in practice the first few percent of the compressed file (low tens of MB).

Output per file is ~15–25 MB gzipped — comfortably under GitHub's 100 MB per-file soft limit.

## 8. Error handling + atomicity

Follows the `cloud_ip_ranges` "fetch all to memory, then write" pattern:

1. Fetch `graphinfo.json` → parse → derive `release_id`.
2. If `release_id` matches the existing `current.release.txt`, early-return True (no writes).
3. Otherwise, download and truncate host ranks into `host_csv_bytes` (in memory).
4. Download and truncate domain ranks into `domain_csv_bytes` (in memory).
5. Only after both succeed, write:
   - `data/host/<date>_<release_id>.csv.gz` via `deterministic_gzip`.
   - `data/domain/<date>_<release_id>.csv.gz` via `deterministic_gzip`.
   - Update both `current.csv.gz` pointers via `update_current`.
   - Write both `current.release.txt` via `write_if_changed`.
   - Write `data/graphinfo.json` (verbatim `response.text`).

Any exception at steps 1–4 aborts before any file is written; the `data/` tree stays consistent. Return `False` on any unrecoverable error → reusable workflow fails → no commit.

**Specific failure classes and behavior:**

`run()` distinguishes two failure modes:
- **Anticipated, no data reasonable to publish yet** → `return False` (no exception). Only the empty-`releases` case qualifies.
- **Unanticipated / indicates upstream change or transient outage** → exception propagates. The feedcache CLI exits non-zero either way, so both cause the GitHub Actions step to fail and prevent a commit; propagation just gives the runner logs a full traceback for debugging.

| Failure | Behavior |
|---|---|
| `graphinfo.json` 5xx or non-JSON | `raise_for_status` / `JSONDecodeError` propagates |
| `releases` empty array | explicit check → `return False` (no write) |
| `host-ranks` or `domain-ranks` 404 (release listed but file not yet uploaded) | `raise_for_status` → `HTTPError` propagates; cron retries next scheduled run |
| Header mismatch (upstream schema change) | `RuntimeError("unexpected ranks header: ...")` propagates — human investigates |
| Fewer than 1,000,000 rows (tiny release or truncated upload) | writes whatever it got, no error (rank column truncates to actual max) |
| Broken line (not 5 tab-separated fields) | `RuntimeError("malformed ranks line N: ...")` propagates |

## 9. Testing

File: `tests/test_common_crawl_ranks.py`. Patterns copied from `test_majestic.py` and `test_cloud_ip_ranges.py` (both do memory-only HTTP mocking).

Fixtures:
- `graphinfo.json` with two synthetic releases (`"cc-main-2026-jan-feb-mar"` first, `"cc-main-2025-26-dec-jan-feb"` second).
- `fake_host_ranks.txt.gz` and `fake_domain_ranks.txt.gz` — each 10 tab-separated rows behind a `#`-prefixed header. Row values crafted so `host_rev` reversal is observable (e.g. `com.example.www` → `www.example.com`).

Tests:
1. **Happy path**: patch HTTP to return the fixtures; run against a tmp directory; assert both `data/host/*.csv.gz` and `data/domain/*.csv.gz` exist, headers correct, rows match expected reversed hosts, `current.csv.gz` symlink-equivalent (byte-equal) to the dated file, `current.release.txt` contains the release id.
2. **Top-N truncation**: monkeypatch `TOP_N = 3`, assert output has exactly 3 data rows (plus header) out of the 10-row fixture.
3. **No-op early-return**: seed `data/host/current.release.txt` with the latest release id before running; assert `run` returns True and no new files were written under `data/host/` or `data/domain/`. (`data/graphinfo.json` may be overwritten on every run, including no-op runs — see §6.)
4. **Malformed row**: fixture with a 4-field line, assert `run` returns False and `data/` is empty.
5. **Empty releases**: `graphinfo.json` returning `[]`, assert False + empty `data/`.
6. **CLI wiring**: `test_cli.py` gets a new `test_common_crawl_ranks_source_registered` that calls `feedcache common-crawl-ranks --help` (or inspects `SOURCES["common-crawl-ranks"]`).

Mocking style: existing feedcache tests use `pytest`'s `monkeypatch` fixture to swap `feedcache.sources.<name>.requests.get` (or `download_to` for the direct-download sources) with a fake function that returns `unittest.mock.MagicMock` response objects. No third-party HTTP-mock library is required; this spec follows the same style. The gzip fixtures are generated at test-setup time with `gzip.compress(..., mtime=0)` for determinism.

## 10. GitHub Actions wiring

**In the new data repo** (`common-crawl-ranks-cache/.github/workflows/cron.yml`):

```yaml
name: daily
on:
  schedule: [{ cron: "30 4 * * *" }]    # 04:30 UTC — concurrent with public-suffix-list-cache; separate Actions VMs
  workflow_dispatch:
permissions:
  contents: write
jobs:
  snapshot:
    uses: wangmm001/feedcache/.github/workflows/reusable-snapshot.yml@main
    with: { source: common-crawl-ranks }
```

No new secrets (CC is entirely anonymous HTTPS). The existing reusable workflow needs no changes — it already accepts any `source` name and passes it to the `feedcache` CLI.

**Cron slot chosen**: 04:30 UTC. Existing lineup:
- 03:30 umbrella, 03:45 tranco, 04:00 cloudflare-radar, 04:15 majestic, 04:30 public-suffix-list, 04:45 cloud-ip-ranges, 05:00 crux-mirror, 05:30 aggregate-top-domains. common-crawl-ranks piles onto the 04:30 slot alongside PSL; GitHub Actions runs them in separate VMs so there's no contention, and both short-circuit on most days (PSL when upstream `public_suffix_list.dat` is unchanged, CC when `graphinfo.json` still points at the same release).

04:30 slots cleanly between majestic and cloud-ip-ranges. Since `common-crawl-ranks` has no downstream dependency (aggregate is untouched in this phase), slot position is flexible.

## 11. Known simplifications

- **Top-1M truncation is lossy.** Common Crawl reports ~288M hosts and ~134M domains per release; we keep the top 0.35% and 0.75% respectively. Acceptable: this mirror exists to be comparable to the other top-1M lists, not to be a full graph dump.
- **`domain` granularity is CC's own reverse-domain-merge, not PSL eTLD+1.** For example, a user-content subdomain hosted on a public suffix (e.g. `blog.github.io` where `github.io` is a PSL public suffix) may collapse differently than it does in `top-domains-aggregate`. This difference is explicitly deferred to the aggregate-integration phase.
- **Harmonic Centrality and PageRank are the only signals kept.** We do not compute in-degree, betweenness, or any other centrality.
- **No historical backfill.** The repo starts with whatever release is current on the first cron run. Historical CC releases are still available upstream; a future backfill pass could populate them.
- **IDN / punycode not normalized.** Entries are whatever CC stored (historically a mix of punycode and occasional UTF-8).
- **No release lag handling.** If upstream publishes `graphinfo.json` before the corresponding ranks files (a rare transient), the daily run fails once and retries cleanly the next day.

## 12. Future work (not in this spec)

- **Aggregate integration.** Add CC as a 6th source to `top-domains-aggregate`. Requires a decision on (a) PSL normalization vs. CC's native domain granularity, (b) RRF rank contribution formula — CC Top-1M has a true ordinal so likely `1/(60+rank)` like umbrella/tranco/majestic.
- **Historical backfill.** Loop `graphinfo.json` for older release ids, fetch each `host-ranks` / `domain-ranks`, write as `YYYY-MM-DD_<release-id>.csv.gz` with the CC release's publication date (parseable from the blog post or `stats.last_modified`). One-shot script, not part of the daily cron.
- **Raw webgraph access.** Separate track: mirror or locally compute from `*-vertices.txt.gz` + `*-edges.txt.gz` to enable custom analyses (in-degree rankings, seed-set PageRank, linguistic sub-graphs). Storage- and CPU-intensive; would not live in this repo.
- **URL-level cc-index.** Separate track for `cluster.idx` mirroring + WARC slicing tools.

## 13. Open questions

None at spec time — all schema, URL, and sizing facts were validated against live upstream on 2026-04-21.
