# top-domains-aggregate v2.3 (Common Crawl integration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Common Crawl's domain-level Top-1M as the 6th input to the `top-domains-aggregate` cross-list RRF aggregator.

**Architecture:** Extend `feedcache/sources/aggregate_top_domains.py`'s `SOURCES` list with a new `common-crawl` entry pointing at `common-crawl-ranks-cache/data/domain/current.csv.gz`, add a `_parse_common_crawl` parser (reads `rank` + `domain` columns, ignores the `n_hosts` column), pass through the shared PSL normalization, and flow into the existing RRF accumulator with `K=60` unchanged. `count` column's max rises from 5 to 6; `lists` column gains a new `common-crawl` token.

**Tech Stack:** Python 3.11, existing feedcache deps (`requests`, `publicsuffixlist`, stdlib `csv`/`gzip`/`io`). Tests: pytest + `monkeypatch` + `unittest.mock.MagicMock`. No new dependencies.

**Reference:** spec at `docs/superpowers/specs/2026-04-21-aggregate-common-crawl-integration-design.md` (committed on main at `a0bf0ee`).

---

## Task 1: TDD — extend the aggregator with Common Crawl

**Files:**
- Modify: `/home/wangmm/feedcache/feedcache/sources/aggregate_top_domains.py`
- Modify: `/home/wangmm/feedcache/tests/test_aggregate_top_domains.py`

- [ ] **Step 1: Extend test fixtures with CC — but do NOT touch the aggregator yet**

Edit `/home/wangmm/feedcache/tests/test_aggregate_top_domains.py`.

Add a new fixture constant right after the existing `_FAKE_CRUX` line:

```python
_FAKE_COMMON_CRAWL = _gzip_bytes(
    "rank,harmonicc_val,pr_pos,pr_val,domain,n_hosts\n"
    "1,9.5E7,2,0.01,google.com,41269\n"
    "2,9.0E7,3,0.012,youtube.com,50\n"
    "1000,5.0E6,1500,0.0005,cc-only.example,1\n"
)
```

Extend `_default_url_map()` by adding one more entry at the end of the returned dict, after the `crux` line. Replace the full function body with:

```python
def _default_url_map():
    from feedcache.sources.aggregate_top_domains import SOURCES, PSL_URL
    url_by_name = {name: url for name, url, _ in SOURCES}
    return {
        PSL_URL: _gzip_bytes(_FAKE_PSL_TEXT),
        url_by_name["umbrella"]: _FAKE_UMBRELLA,
        url_by_name["tranco"]: _FAKE_TRANCO,
        url_by_name["majestic"]: _FAKE_MAJESTIC,
        url_by_name["cloudflare-radar"]: _FAKE_CLOUDFLARE,
        url_by_name["crux"]: _FAKE_CRUX,
        url_by_name["common-crawl"]: _FAKE_COMMON_CRAWL,
    }
```

Add a NEW test at the end of the file (do not modify existing tests yet):

```python
def test_aggregate_common_crawl_only_domain_lands_with_count_1(tmp_path, monkeypatch):
    """A domain that appears only in CC gets count=1, lists=common-crawl,
    and score = 1/(60+rank)."""
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    aggregate_top_domains.run(str(tmp_path))
    rows = _read_output(tmp_path)
    by_domain = {r["domain"]: r for r in rows}

    assert "cc-only.example" in by_domain, \
        "cc-only.example should land from the CC fixture"
    row = by_domain["cc-only.example"]
    assert row["count"] == "1"
    assert row["lists"] == "common-crawl"
    # rank=1000 in CC → contribution 1/(60+1000) = 1/1060 ≈ 0.000943
    assert row["score"] == "0.000943"
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_aggregate_top_domains.py::test_aggregate_common_crawl_only_domain_lands_with_count_1 -v`

Expected: FAIL. Two possible failure modes — either `_install_fake_get`'s AssertionError fires for the new `common-crawl` URL (because the aggregator's `SOURCES` list doesn't include it, so no fetch to that URL, but `_default_url_map` references `url_by_name["common-crawl"]` which KeyErrors), OR the `cc-only.example` domain is not in the output (because the aggregator didn't fetch CC). The immediate error will be `KeyError: 'common-crawl'` from `url_by_name["common-crawl"]` in `_default_url_map` — that's the red state.

- [ ] **Step 3: Implement `common-crawl` as the 6th source**

Edit `/home/wangmm/feedcache/feedcache/sources/aggregate_top_domains.py`.

Extend the `SOURCES` list to include `common-crawl` after `crux`:

```python
SOURCES: list[tuple[str, str, str]] = [
    ("umbrella",
     "https://raw.githubusercontent.com/wangmm001/umbrella-top1m-cache/main/data/current.csv.gz",
     "rank_domain_noheader"),
    ("tranco",
     "https://raw.githubusercontent.com/wangmm001/tranco-top1m-cache/main/data/current.csv.gz",
     "rank_domain_noheader"),
    ("majestic",
     "https://raw.githubusercontent.com/wangmm001/majestic-million-cache/main/data/current.csv.gz",
     "majestic"),
    ("cloudflare-radar",
     "https://raw.githubusercontent.com/wangmm001/cloudflare-radar-rankings-cache/main/data/current/top-1000000.csv.gz",
     "cloudflare"),
    ("crux",
     "https://raw.githubusercontent.com/wangmm001/crux-top-lists-mirror/main/data/global/current.csv.gz",
     "crux"),
    ("common-crawl",
     "https://raw.githubusercontent.com/wangmm001/common-crawl-ranks-cache/main/data/domain/current.csv.gz",
     "common_crawl"),
]
```

Add a new parser function right after `_parse_crux`:

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

Extend the `PARSERS` dict:

```python
PARSERS = {
    "rank_domain_noheader": _parse_rank_domain_noheader,
    "majestic": _parse_majestic,
    "cloudflare": _parse_cloudflare,
    "crux": _parse_crux,
    "common_crawl": _parse_common_crawl,
}
```

- [ ] **Step 4: Run the new CC-only test to verify it passes**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_aggregate_top_domains.py::test_aggregate_common_crawl_only_domain_lands_with_count_1 -v`

Expected: PASS.

- [ ] **Step 5: Update existing numeric assertions for 6-source world**

Two existing tests encode 5-source score values; they now need to reflect CC's contribution to `google.com` (rank 1) and `youtube.com` (rank 2).

In `test_aggregate_has_score_column_and_sorts_by_count_then_score`, replace the block starting at `first = rows[0]`:

```python
    # google.com in all 6 (RRF K=60, CC rank=1):
    # 4/(60+1) + 1/(60+1000000) + 1/(60+1000) ≈ 0.066518
    first = rows[0]
    assert first["domain"] == "google.com"
    assert first["count"] == "6"
    assert first["score"] == "0.066518"
    assert first["lists"] == "common-crawl|cloudflare-radar|crux|majestic|tranco|umbrella"

    # youtube.com in 5 (not majestic; CC rank=2):
    # 1/62 + 1/63 + 1/1000060 + 1/1060 + 1/62 ≈ 0.049075
    second = rows[1]
    assert second["domain"] == "youtube.com"
    assert second["count"] == "5"
    assert second["score"] == "0.049075"
```

No other existing test encodes a specific score or count number; `test_aggregate_within_count_tier_higher_score_comes_first`, `test_aggregate_psl_normalizes_crux_subdomain`, `test_aggregate_psl_preserves_private_suffix_subdomains`, `test_aggregate_crux_origin_scheme_and_www_stripped`, `test_aggregate_idempotent`, `test_aggregate_psl_failure_aborts`, and `test_aggregate_upstream_failure_writes_nothing` all pass without modification given the updated `_default_url_map`.

- [ ] **Step 6: Run the full test file**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_aggregate_top_domains.py -v`

Expected: all tests (8 existing + 1 new = 9) PASS.

- [ ] **Step 7: Run the full feedcache suite to confirm no regressions elsewhere**

Run: `cd /home/wangmm/feedcache && python -m pytest -v`

Expected: all tests PASS. The baseline at the parent commit (`a0bf0ee` on main) is 48/48 passing; after this task the count rises to 49/49 (the new CC-only test adds one).

- [ ] **Step 8: Commit**

```bash
cd /home/wangmm/feedcache
git add feedcache/sources/aggregate_top_domains.py tests/test_aggregate_top_domains.py
git commit -m "feat(aggregate): add common-crawl as 6th source (v2.3)

Extends SOURCES with common-crawl-ranks-cache/data/domain/current.csv.gz
and adds _parse_common_crawl (reads rank+domain columns, ignores
n_hosts). Per-domain RRF contribution uses 1/(60+rank) against CC's
harmonicc_pos, treated as a true ordinal 1..1_000_000. Updates
google.com/youtube.com score assertions for the new 6-source world."
```

---

## Task 2: Update `feedcache/docs/design.md`

**Files:**
- Modify: `/home/wangmm/feedcache/docs/design.md`

- [ ] **Step 1: Update §3 table row for top-domains-aggregate**

Find the row in the §3 data-repositories table that starts with `` `top-domains-aggregate` ``. Its current "Upstream" cell mentions "5 sibling `current.csv.gz` files + PSL cache". Change "5" to "6".

Exact replacement target (verify by reading the file before editing; the surrounding row text is stable):

Current:
```
| `top-domains-aggregate` | derived | 5 sibling `current.csv.gz` files + PSL cache | 05:30 | `data/YYYY-MM-DD.csv.gz`, `data/current.csv.gz` |
```

New:
```
| `top-domains-aggregate` | derived | 6 sibling `current.csv.gz` files + PSL cache | 05:30 | `data/YYYY-MM-DD.csv.gz`, `data/current.csv.gz` |
```

- [ ] **Step 2: Update §5b Inputs table**

Find the `### 5b. Derived aggregate` section's "**Inputs (fetched at run time):**" table. Add a new row after the `crux` row, matching the surrounding format:

```
| common-crawl | `…/common-crawl-ranks-cache/…/data/domain/current.csv.gz` | ordinal 1–1 000 000 (CC `harmonicc_pos`) |
```

- [ ] **Step 3: Update §5b version history table**

In the same `### 5b. Derived aggregate` section, find the "Aggregator version history" table. Its tail row is `v2.2`. Append one new row:

```
| v2.3 | added common-crawl as 6th source (domain-level Top-1M, harmonicc_pos rank) |
```

- [ ] **Step 4: Update §5b input-count prose**

Find the sentence at the beginning of `### 5b. Derived aggregate` that describes the aggregator. The current text includes "fetches `current.csv.gz` from five sibling data repos". Change "five" to "six".

- [ ] **Step 5: Spot-check with grep**

Run: `grep -nE "common-crawl|5 sibling|five sibling" /home/wangmm/feedcache/docs/design.md`

Expected: the common-crawl tokens now appear in §3, §5b inputs table, and §5b version history. No occurrences of "5 sibling" or "five sibling" should remain in §5b's description of the aggregator. (Occurrences elsewhere — like historical commit messages quoted in docs — are fine if any exist, but none are expected in this file.)

- [ ] **Step 6: Commit**

```bash
cd /home/wangmm/feedcache
git add docs/design.md
git commit -m "docs(design): record v2.3 (aggregate now consumes common-crawl)

Updates §3 table count, §5b inputs table, §5b version history, and
§5b intro prose to reflect the 6th source added in v2.3."
```

---

## Task 3: Update `top-domains-aggregate` data repo README

**Files:**
- Modify: `/home/wangmm/top-domains-aggregate/README.md`

Note: this is a separate repository at `/home/wangmm/top-domains-aggregate/` — not the feedcache worktree. Do all Task 3 commits in that directory.

- [ ] **Step 1: Read the current README to understand its structure**

Run: `cat /home/wangmm/top-domains-aggregate/README.md`

Expected sections (this file already exists and will be updated, not created): intro paragraph, Layout, Format (including a `count 1–5` description), "How the `score` is computed" table, "Input lists" table, Known simplifications, Consume, License, How it works.

Note the existing row structure in both tables so the additions match exactly.

- [ ] **Step 2: Update the Format section's `count` range**

Find the existing line in the Format section that says `count integer 1–5 = number of distinct input lists the domain appears in.` Replace `1–5` with `1–6` and replace `five lists` or `5 lists` anywhere else in the file with `six lists` / `6 lists` as appropriate. Verify with `grep -nE "1–5|five list|5 list|5 input" /home/wangmm/top-domains-aggregate/README.md` — after the edit, no matches should remain (other than possibly historical references intentionally preserved).

- [ ] **Step 3: Update the sample row block**

Find the sample CSV block in the Format section (the one showing `google.com,5,3.001001,...`). Replace it with a version that reflects 6-source merging, using the hand-computed smoothed-RRF values from Task 1's test:

Existing block (current text):
```
domain,count,score,lists
google.com,5,3.001001,cloudflare-radar|crux|majestic|tranco|umbrella
facebook.com,5,2.501001,cloudflare-radar|crux|majestic|tranco|umbrella
...
```

Replace with (note: the actual score values below use the smoothed-RRF v2.2+ formula and the live data's actual ranks, so they may drift slightly once the live run happens; the illustrative numbers here are rounded representative values):

```
domain,count,score,lists
google.com,6,0.066518,common-crawl|cloudflare-radar|crux|majestic|tranco|umbrella
youtube.com,5,0.049075,common-crawl|cloudflare-radar|crux|tranco|umbrella
...
```

If the existing block contains additional example rows (e.g. `only-in-umbrella.test,1,...`), preserve the existing `count=1` example style but make sure `common-crawl` also shows up as a possible single-source example:

```
...
cc-only.example,1,0.000943,common-crawl
only-in-umbrella.test,1,0.000016,umbrella
```

- [ ] **Step 4: Add a row to the "How the `score` is computed" table**

Find the table whose rows describe umbrella/tranco/majestic/cloudflare-radar/crux rank semantics. Add after the `crux` row:

```
| common-crawl | `rank` column (harmonicc_pos) | ordered list — CC's webgraph Harmonic Centrality is a true ordinal 1–1,000,000 |
```

- [ ] **Step 5: Add a row to the "Input lists" table**

Find the table listing source names + GitHub raw URLs. Add after the `crux` row:

```
| `common-crawl` | Common Crawl webgraph (host/domain rank cache) | `raw.githubusercontent.com/wangmm001/common-crawl-ranks-cache/main/data/domain/current.csv.gz` |
```

- [ ] **Step 6: Update the number of source lists mentioned in intro prose**

The intro paragraph of the README mentions "five lists". Update to "six lists". Also update the "Daily cross-list aggregation" intro if it encodes the count.

- [ ] **Step 7: Update the Known simplifications section (if relevant)**

If the README's Known simplifications section mentions PSL only in the context of 5 sources, update to reflect that CC's domain column is already registrable-form but still passes through PSL normalization for cross-source consistency. Suggested wording:

```
- **CC's domain granularity vs. PSL:** `common-crawl-ranks-cache` exports a domain-level file where CC's own reverse-domain-merge has already produced registrable-form domains. The aggregator still passes these through PSL `privatesuffix` so all 6 inputs go through the same normalization. In practice the two agree on ~all cases; the main divergence is around public-suffix edge cases (e.g. `github.io`).
```

- [ ] **Step 8: Commit**

```bash
cd /home/wangmm/top-domains-aggregate
git add README.md
git commit -m "docs: document v2.3 (common-crawl as 6th input)

Updates the Format schema (count 1–6), sample rows, 'How the score
is computed' table, 'Input lists' table, and intro prose to reflect
the Common Crawl integration shipped in v2.3."
```

---

## Task 4: Publish (requires explicit user confirmation)

> Stop and confirm with the user before running these commands. Pushing is not locally reversible. Specifically: push `main` on `wangmm001/feedcache` and on `wangmm001/top-domains-aggregate`.

**Files:**
- No local files changed.

- [ ] **Step 1: Review what will be pushed on feedcache**

Run:
```bash
cd /home/wangmm/feedcache
git status
git log --oneline origin/main..HEAD
```

Expected: main is 3 commits ahead of origin/main (spec commit `a0bf0ee` + Task 1 feat commit + Task 2 docs commit; if Task 1 split into multiple commits, adjust expectation to match).

- [ ] **Step 2: Push feedcache main**

Run:
```bash
cd /home/wangmm/feedcache
git push origin main
```

Expected: push succeeds with no rejections; `test.yml` on GitHub Actions runs against the new main and passes.

- [ ] **Step 3: Review what will be pushed on top-domains-aggregate**

Run:
```bash
cd /home/wangmm/top-domains-aggregate
git status
git log --oneline origin/main..HEAD
```

Expected: 1 commit ahead (Task 3 docs commit).

- [ ] **Step 4: Push top-domains-aggregate main**

Run:
```bash
cd /home/wangmm/top-domains-aggregate
git push origin main
```

Expected: push succeeds.

- [ ] **Step 5: Verify `test.yml` pass on feedcache**

Run:
```bash
gh run list --repo wangmm001/feedcache --workflow test.yml --limit 1
```

Expected: most-recent run is marked `completed` with conclusion `success`. If it's still queued/in progress, wait with:
```bash
gh run watch <run-id> --repo wangmm001/feedcache --exit-status
```

---

## Task 5: Trigger the aggregate workflow and verify 6-source output

**Files:**
- No local files changed.

- [ ] **Step 1: Dispatch the aggregate workflow**

Run:
```bash
gh workflow run daily --repo wangmm001/top-domains-aggregate
```

Expected: `✓ Created workflow_dispatch event for daily.yml at main`.

- [ ] **Step 2: Watch the run**

Run:
```bash
gh run list --repo wangmm001/top-domains-aggregate --limit 1
# Copy the run-id from output:
gh run watch <run-id> --repo wangmm001/top-domains-aggregate --exit-status
```

Expected: run completes with all steps green. Total time ~1–3 minutes (fetching 6 URLs + PSL + computing ~1.5M-domain RRF + commit + push).

- [ ] **Step 3: Verify `common-crawl` appears in the output**

Run:
```bash
curl -sL https://raw.githubusercontent.com/wangmm001/top-domains-aggregate/main/data/current.csv.gz | gunzip -c | head -5
```

Expected: the top-5 rows show `count=6` for several entries (google, youtube, facebook, etc.) and their `lists` column contains `common-crawl` alphabetized between `cloudflare-radar` and `crux` (i.e. `common-crawl|cloudflare-radar|crux|majestic|tranco|umbrella`).

- [ ] **Step 4: Verify `count` distribution has 6 as the new max**

Run:
```bash
curl -sL https://raw.githubusercontent.com/wangmm001/top-domains-aggregate/main/data/current.csv.gz | gunzip -c | python3 -c "
import csv, sys
from collections import Counter
c = Counter(r['count'] for r in csv.DictReader(sys.stdin))
for k in sorted(c, key=int, reverse=True):
    print(f'{k}: {c[k]}')
"
```

Expected: the top line is `6: N` for some N≥1 (domains that are in all 6 lists). Previously this was `5: N`. The distribution now spans `1` through `6`.

- [ ] **Step 5: Spot-check one CC-only domain**

Run:
```bash
curl -sL https://raw.githubusercontent.com/wangmm001/top-domains-aggregate/main/data/current.csv.gz | gunzip -c | awk -F, '$4=="common-crawl"' | head -5
```

Expected: at least some rows where `count=1` and `lists=common-crawl`, i.e. domains that CC's webgraph sees but the other 5 top-lists miss. These are the long-tail sites. Rows should have plausible `score` values matching `1/(60+rank)`.

- [ ] **Step 6: No commit needed**

This task is verification-only; no local files change.

---

## Spec coverage verification

| Spec section | Task(s) |
|---|---|
| §1 Goal | Tasks 1–5 collectively |
| §2 scope — aggregate_top_domains.py change | Task 1 |
| §2 scope — tests | Task 1 |
| §2 scope — feedcache design.md update | Task 2 |
| §2 scope — top-domains-aggregate README update | Task 3 |
| §2 out-of-scope (PageRank, n_hosts, RRF_K, crux bucket, host-level) | Not implemented — enforced by plan contents |
| §3 Architecture | Task 1 Step 3 |
| §4.1 SOURCES entry | Task 1 Step 3 |
| §4.2 _parse_common_crawl | Task 1 Step 3 |
| §4.3 PARSERS dict | Task 1 Step 3 |
| §5 RRF math + count 1–6 | Task 1 Steps 5, 6 + Task 3 Step 2 |
| §6 PSL normalization behavior | Task 1 Step 3 (via _normalize call, unchanged); existing tests in file cover PSL behavior |
| §7 Test changes | Task 1 Steps 1, 5 |
| §8.1 design.md updates | Task 2 |
| §8.2 README updates | Task 3 |
| §9 Cron timing | No code change — existing 04:30/05:30 ordering is compatible |
| §10 Error handling | Not changed — inherited from existing fetch_and_parse propagation |
| §11 Version v2.3 | Task 2 Step 3 |
| §12 Known simplifications | Task 3 Step 7 (README) + present in spec |
| §13 Future work | Not in plan; deferred per spec |

No gaps.
