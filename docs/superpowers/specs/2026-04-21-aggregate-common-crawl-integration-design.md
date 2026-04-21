# 2026-04-21 — `top-domains-aggregate` Common Crawl integration

Add Common Crawl (CC) as the 6th input source to the cross-list domain aggregator, using CC's domain-level Top-1M mirror already published at `wangmm001/common-crawl-ranks-cache`.

## 1. Goal

After this change, `top-domains-aggregate/data/current.csv.gz` contains domains scored across **six** input lists instead of five, with CC contributing via its Harmonic Centrality ordinal rank. Consumers of the aggregate pick up the signal automatically — no new output schema, just `count` values now ranging 1–6 and a possible new `common-crawl` token in the `lists` column.

## 2. Scope

**In scope**
- `feedcache/sources/aggregate_top_domains.py`: add CC to `SOURCES`, add `_parse_common_crawl`, register in `PARSERS`.
- `tests/test_aggregate_top_domains.py`: extend the fixture + assertions to exercise CC's contribution.
- `feedcache/docs/design.md`: update §3 aggregate table row, §5b inputs table + version history (bump to v2.4; v2.3 is the next slot — see §11).
- `top-domains-aggregate/README.md`: update the "Input lists" table and the "How the `score` is computed" table; bump `count` range text from "1–5" to "1–6".

**Out of scope**
- Using CC's PageRank (`pr_pos`) signal. Deferred to §13 future-work.
- Using CC's `n_hosts` column as a tie-breaker or side signal.
- Changing `RRF_K` (stays at 60).
- Re-visiting CrUX's bucket-rank semantics (pre-existing design choice, not touched).
- Host-level CC ingestion (we use CC's own registrable-domain file, which already folds hosts).

## 3. Architecture

No structural changes. Same `fetch → parse → normalize (PSL) → accumulate RRF → sort → write` flow, just one extra entry in the `SOURCES` list:

```
aggregate_top_domains.run(out_dir)
├── _load_psl()                                      # unchanged
├── for (name, url, parser_key) in SOURCES:          # now 6 entries (was 5)
│     text = fetch(url); dom_rank = PARSERS[key](text, psl)
│     per_source[name] = dom_rank
├── RRF accumulate: contrib = 1 / (RRF_K + rank)      # unchanged, K=60
├── sort by (-count, -score, domain ASC)
└── write data/YYYY-MM-DD.csv.gz + data/current.csv.gz
```

## 4. `aggregate_top_domains.py` changes

### 4.1 Add SOURCES entry

Append to `SOURCES` after the `crux` row (order affects nothing except readability):

```python
("common-crawl",
 "https://raw.githubusercontent.com/wangmm001/common-crawl-ranks-cache/main/data/domain/current.csv.gz",
 "common_crawl"),
```

### 4.2 Add parser

```python
def _parse_common_crawl(text: str, psl: PublicSuffixList) -> dict[str, int]:
    out: dict[str, int] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        try:
            rank = int((row.get("rank") or "").strip())
        except ValueError:
            continue
        d = _normalize(row.get("domain") or "", psl)
        if d and (d not in out or rank < out[d]):
            out[d] = rank
    return out
```

The `n_hosts` column is read by `DictReader` but not used by this parser.

### 4.3 Register in PARSERS

```python
PARSERS = {
    "rank_domain_noheader": _parse_rank_domain_noheader,
    "majestic": _parse_majestic,
    "cloudflare": _parse_cloudflare,
    "crux": _parse_crux,
    "common_crawl": _parse_common_crawl,
}
```

## 5. RRF math (unchanged formula; illustrative numbers)

CC's `rank` is a genuine ordinal 1..1 000 000 (from upstream `harmonicc_pos`). Treatment is identical to umbrella / tranco / majestic / crux (all ordinal-ranked), not the `UNORDERED_RANK=1_000_000` fallback used for Cloudflare Radar.

Per-domain contribution examples with K=60:

| domain | CC rank | `1 / (60 + rank)` |
|---|---|---|
| facebook.com | 1 | 0.01639 |
| google.com | 3 | 0.01587 |
| wikipedia.org | 100 | 0.00625 |
| an-obscure-site.example | 1 000 000 | 9.99e-7 |

Net effect on published output:
- `count` column range: was 1–5, now 1–6.
- `lists` column: may now contain the new token `common-crawl` (sorts lexicographically between `cloudflare-radar` and `crux` within the `|`-joined string).
- `score`: slightly higher for domains that CC also sees; significantly higher for domains previously only in one or two lists that now pick up a strong CC rank.
- New long-tail entries: CC's web-crawl coverage likely exposes many domains (particularly non-commercial and international sites) that the 5 existing top-lists miss. These land in the aggregate with `count=1` and `lists=common-crawl`, which widens the tail meaningfully.

## 6. PSL normalization behavior with CC input

CC's `domain` column is already a registrable form (CC's own reverse-domain-merge). `_normalize()` applies `psl.privatesuffix(domain)` on top, so:

| Input (CC) | `_normalize()` output | Consistent with 5 existing sources? |
|---|---|---|
| `facebook.com` | `facebook.com` | yes |
| `github.io` | `github.io` (PSL returns None → fallback to input) | yes |
| `blog.github.io` (rare in CC domain file; CC should have folded already) | `blog.github.io` | yes |
| `xn--punycode.example` | `xn--punycode.example` | yes |

PSL does not do ASCII/Unicode IDN reconciliation — known pre-existing limitation, unchanged.

## 7. Test changes (`tests/test_aggregate_top_domains.py`)

Add:
- A new fixture constant representing a CC-format CSV: 6 columns (`rank,harmonicc_val,pr_pos,pr_val,domain,n_hosts`), 3–5 rows including at least one domain that also appears in another source's fixture, and at least one CC-only domain.
- A new URL → body mapping in the HTTP mock that serves this fixture when the CC URL is requested.
- Assertions:
  - A domain that was previously `count=N, lists=...` in the 5-source fixture now appears with `count=N+1, lists=...|common-crawl` in the output.
  - The CC-only domain appears in the output with `count=1, lists=common-crawl` and a non-zero score.
  - The `score` column for a CC-contributing domain matches hand-computed `1/(60+rank)` accumulation.

Existing assertions for 5-source behavior must still pass unchanged (except where they implicitly encode `count=5` as the maximum — those need to widen to `count=6`).

## 8. Documentation changes

### 8.1 `feedcache/docs/design.md`

**§3 data-repositories table** — update the aggregate row. Currently mentions "5 sibling `current.csv.gz` files + PSL cache". Change to "6 sibling `current.csv.gz` files + PSL cache".

**§5b "Inputs" table** — add row:

```
| common-crawl | `…/common-crawl-ranks-cache/…/data/domain/current.csv.gz` | ordinal 1–1 000 000 (CC `harmonicc_pos`) |
```

**§5b version history table** — add row:

```
| v2.3 | added common-crawl as a 6th source (CC domain-level Top-1M, harmonicc_pos rank) |
```

### 8.2 `top-domains-aggregate/README.md`

**"Input lists" table** — add row:

```
| `common-crawl` | Common Crawl webgraph ranks | `…/common-crawl-ranks-cache/main/data/domain/current.csv.gz` |
```

**"How the `score` is computed" table** — add row:

```
| common-crawl | `rank` value 1–1 000 000 | CC webgraph Harmonic Centrality (`harmonicc_pos`), true ordinal |
```

**`count` range** — any prose referencing "count integer 1–5" or similar must be updated to "1–6".

**Header / intro paragraph** — adjust if it says "five sources" or "5 lists".

## 9. Cron timing

CC cache cron runs at 04:30 UTC; aggregate cron runs at 05:30 UTC. No change needed — the 60-minute gap is ample given CC's snapshot step completes in <1 minute and `current.csv.gz` atomicity is provided by `deterministic_gzip + update_current`. CC content updates only ~4 times/year; on the other ~360 days the aggregate reads a stable, unchanged CC snapshot.

## 10. Error handling

CC's URL returning 5xx/404, or malformed CSV, propagates `HTTPError` / `ValueError` out of `_fetch_and_parse` just like any other source. The aggregate run fails; GitHub Actions logs the traceback; no commit is produced that day. This matches the existing "all-or-nothing" semantics — there is no per-source fallback, deliberately, so partial aggregates never ship.

## 11. Version numbering

The existing §5b version history tail is v2.2 (smoothed RRF). This change ships as **v2.3**.

## 12. Known simplifications

- **PageRank ignored.** CC exports two centralities; we use only Harmonic Centrality. See §13.
- **`n_hosts` ignored.** CC's per-domain host count is structurally useful (could weight ties or inform coverage), but the aggregate's output schema is `domain,count,score,lists` and doesn't have a slot for it without a schema bump. See §13.
- **CC's domain granularity ≠ PSL for public-suffix edge cases.** The second-pass PSL normalization aligns them; in practice the overlap is near-total.

## 13. Future work (not this spec)

- **PageRank as a second CC-derived signal.** Either (a) a separate pseudo-source `common-crawl-pr` using `pr_pos`, bumping `count`'s max to 7, or (b) a blended CC rank (e.g. `min(rank, pr_pos)` or harmonic mean). Requires a decision on whether "same source, two signals" should count as one or two in `count`.
- **`n_hosts` as a tie-breaker.** Sort order could be `(-count, -score, -n_hosts_if_cc, domain)` to prefer CC-heavy domains on ties.
- **CC host-level as a 7th source.** Would require host-level PSL folding in the aggregate; would double-count CC's information content, so probably not wanted.
- **CrUX bucket-rank rethinking.** Unrelated to CC but a standing item: CrUX rank is a bucket value (1000/10000/100000/1000000) not an ordinal, so its per-bucket contribution is coarse-grained; a log-based scaling could narrow the gap.

## 14. Open questions

None.
