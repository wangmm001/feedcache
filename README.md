# feedcache

Mirrors public internet top-list / metadata feeds into git-backed data repositories. Code lives here; data lives in sibling repos so `git pull`-ing data doesn't drag in code changes.

## Data repositories

Three repos are populated by this codebase via a shared reusable workflow:

| Source | Data repo | Upstream |
|---|---|---|
| Cisco Umbrella Top 1M | [`wangmm001/umbrella-top1m-cache`](https://github.com/wangmm001/umbrella-top1m-cache) | `https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip` |
| Tranco Top 1M | [`wangmm001/tranco-top1m-cache`](https://github.com/wangmm001/tranco-top1m-cache) | `https://tranco-list.eu/` |
| Cloudflare Radar rank buckets | [`wangmm001/cloudflare-radar-rankings-cache`](https://github.com/wangmm001/cloudflare-radar-rankings-cache) | Cloudflare Radar API `/radar/datasets/ranking_top_<N>` |
| Majestic Million | [`wangmm001/majestic-million-cache`](https://github.com/wangmm001/majestic-million-cache) | `https://downloads.majestic.com/majestic_million.csv` |
| Public Suffix List | [`wangmm001/public-suffix-list-cache`](https://github.com/wangmm001/public-suffix-list-cache) | `https://publicsuffix.org/list/public_suffix_list.dat` |
| Cloud IP ranges (AWS/GCP/Azure/Cloudflare) | [`wangmm001/cloud-ip-ranges-cache`](https://github.com/wangmm001/cloud-ip-ranges-cache) | AWS/GCP/Cloudflare direct JSON+TXT, Azure via HTML scrape |

One derived aggregate (not a mirror — a daily full-outer-join across the five domain-providing sources above):

| Source | Data repo | Upstream |
|---|---|---|
| Cross-list top-domains aggregate | [`wangmm001/top-domains-aggregate`](https://github.com/wangmm001/top-domains-aggregate) | Derived from umbrella + tranco + majestic + cloudflare-radar + crux `current` files |

One companion repo is a **strict GitHub fork mirror** (not populated by this code — it just replays an upstream repo):

| Source | Data repo | Upstream | How it works |
|---|---|---|---|
| Chrome UX Report (CrUX) Top 1M | [`wangmm001/crux-top-lists-mirror`](https://github.com/wangmm001/crux-top-lists-mirror) | [`zakird/crux-top-lists`](https://github.com/zakird/crux-top-lists) | GitHub fork with a daily workflow that runs `gh repo sync` against upstream — tree-level 1:1 mirror. |

## Local usage

```bash
git clone https://github.com/wangmm001/feedcache.git
cd feedcache
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'

# Umbrella / Tranco: no auth
feedcache umbrella ./tmp/umbrella/
feedcache tranco   ./tmp/tranco/

# Cloudflare Radar: free-tier API token required
export CLOUDFLARE_RADAR_API_TOKEN=...
feedcache cloudflare-radar ./tmp/cloudflare-radar/
```

Run tests: `pytest -v`.

## GitHub Actions integration

Each data repo has a ~10-line `.github/workflows/cron.yml` that calls this repo's reusable workflow:

```yaml
name: daily
on:
  schedule: [{ cron: "30 3 * * *" }]
  workflow_dispatch:
permissions:
  contents: write
jobs:
  snapshot:
    uses: wangmm001/feedcache/.github/workflows/reusable-snapshot.yml@main
    with: { source: umbrella }
```

For Cloudflare Radar also pass the secret:

```yaml
    secrets:
      CLOUDFLARE_RADAR_API_TOKEN: ${{ secrets.CLOUDFLARE_RADAR_API_TOKEN }}
```

## Adding a new source

1. Create `feedcache/sources/<name>.py` exporting `run(out_dir: str) -> bool`.
2. Register it in `feedcache/__main__.py`'s `SOURCES` dict.
3. Add a smoke test in `tests/test_<name>.py` (mock the upstream client).
4. Create a new data repo with the same 10-line `cron.yml` pointing at `source: <name>`.

## Design

See [`docs/design.md`](docs/design.md) for the full architecture spec.

## License

Code: MIT. Data repositories carry the licenses of their respective upstream sources; check each data repo's README and LICENSE.
