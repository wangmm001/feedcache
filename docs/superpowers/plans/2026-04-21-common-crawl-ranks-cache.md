# common-crawl-ranks-cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new feedcache source `common-crawl-ranks` that mirrors Common Crawl's Top-1M host-level and domain-level web-graph ranks into a new data repo `wangmm001/common-crawl-ranks-cache`.

**Architecture:** Python `run(out_dir)` module in `feedcache/sources/common_crawl_ranks.py` that (1) polls `https://index.commoncrawl.org/graphinfo.json` to discover the latest CC webgraph release id, (2) short-circuits if `current.release.txt` already matches, (3) streams `host-ranks.txt.gz` and `domain-ranks.txt.gz` over HTTPS, truncates to the first 1,000,000 rows while the connection is still open (so only a few tens of MB are transferred), reshapes to a 5-column CSV with reversed host/domain, and (4) atomically writes both snapshot files plus `current.csv.gz` pointers and a verbatim copy of `graphinfo.json`. A new data repo houses `LICENSE` + `README.md` + `.github/workflows/cron.yml` calling feedcache's existing `reusable-snapshot.yml`.

**Tech Stack:** Python 3.11, `requests` (stream mode), stdlib `gzip`/`csv`/`io`/`pathlib`. Tests: pytest + `monkeypatch` + `unittest.mock.MagicMock`, no third-party HTTP-mock library. GitHub Actions reusable workflow (already exists).

**Reference:** spec at `docs/superpowers/specs/2026-04-21-common-crawl-ranks-cache-design.md`.

---

## Task 1: Scaffold the source module and prove pytest can import it

**Files:**
- Create: `/home/wangmm/feedcache/feedcache/sources/common_crawl_ranks.py`
- Create: `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`

- [ ] **Step 1: Write the failing import test**

Create `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`:

```python
def test_module_importable_and_exposes_run():
    from feedcache.sources import common_crawl_ranks
    assert callable(common_crawl_ranks.run)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_common_crawl_ranks.py -v`
Expected: `ModuleNotFoundError: No module named 'feedcache.sources.common_crawl_ranks'`

- [ ] **Step 3: Create the stub module**

Create `/home/wangmm/feedcache/feedcache/sources/common_crawl_ranks.py`:

```python
from pathlib import Path


GRAPHINFO_URL = "https://index.commoncrawl.org/graphinfo.json"
BASE_URL = "https://data.commoncrawl.org/projects/hyperlinkgraph"
TOP_N = 1_000_000
TIMEOUT = 600


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_common_crawl_ranks.py -v`
Expected: PASS (the test only checks `callable(run)`, not that running it succeeds).

- [ ] **Step 5: Commit**

```bash
cd /home/wangmm/feedcache
git add feedcache/sources/common_crawl_ranks.py tests/test_common_crawl_ranks.py
git commit -m "feat(common-crawl-ranks): scaffold source module

Adds an empty run() stub and a pytest import sanity check so that
subsequent TDD steps have a module to extend."
```

---

## Task 2: Graphinfo fetch and early-return when release is unchanged

**Files:**
- Modify: `/home/wangmm/feedcache/feedcache/sources/common_crawl_ranks.py`
- Modify: `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`

- [ ] **Step 1: Write a shared fake-response fixture + the no-op early-return test**

Append to `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`:

```python
import gzip
import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_FAKE_GRAPHINFO = [
    {
        "id": "cc-main-2026-jan-feb-mar",
        "crawls": ["CC-MAIN-2026-04", "CC-MAIN-2026-08", "CC-MAIN-2026-12"],
        "index": "https://data.commoncrawl.org/projects/hyperlinkgraph/cc-main-2026-jan-feb-mar/index.html",
        "location": "s3://commoncrawl/projects/hyperlinkgraph/cc-main-2026-jan-feb-mar/",
        "stats": {"host": {"nodes": 1, "arcs": 2}, "domain": {"nodes": 3, "arcs": 4}},
    }
]
_FAKE_GRAPHINFO_BYTES = json.dumps(_FAKE_GRAPHINFO).encode("utf-8")


class _FakeResponse:
    """Minimal stand-in for requests.Response usable in both streamed and
    non-streamed modes. streamed=True callers read from .raw via GzipFile."""

    def __init__(self, *, raw_bytes: bytes = b"", content: bytes = b"", json_data=None):
        self.raw = io.BytesIO(raw_bytes)
        self.content = content
        self._json = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self._json

    @property
    def text(self):
        return self.content.decode("utf-8") if self.content else ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


def _patch_http(monkeypatch, handlers):
    """Route requests.get inside the source module to a map of
    url_substring -> callable(url, **kwargs) -> _FakeResponse. The first match
    wins; unmatched URLs raise AssertionError."""
    from feedcache.sources import common_crawl_ranks as m

    def fake_get(url, stream=False, timeout=None, **kwargs):
        for needle, handler in handlers.items():
            if needle in url:
                return handler(url, stream=stream, timeout=timeout, **kwargs)
        raise AssertionError(f"unmocked URL: {url}")

    monkeypatch.setattr(m.requests, "get", fake_get)


def test_noop_early_return_when_release_unchanged(tmp_path, monkeypatch):
    from feedcache.sources import common_crawl_ranks

    (tmp_path / "host").mkdir()
    (tmp_path / "host" / "current.release.txt").write_text(
        "cc-main-2026-jan-feb-mar\n"
    )

    _patch_http(monkeypatch, {
        common_crawl_ranks.GRAPHINFO_URL: lambda url, **kw: _FakeResponse(
            content=_FAKE_GRAPHINFO_BYTES, json_data=_FAKE_GRAPHINFO
        ),
    })

    assert common_crawl_ranks.run(str(tmp_path)) is True

    # No new ranks files under host/ or domain/
    host_csvs = list((tmp_path / "host").glob("*.csv.gz"))
    assert host_csvs == []
    assert not (tmp_path / "domain").exists() or not list((tmp_path / "domain").glob("*.csv.gz"))

    # graphinfo.json may be written on every run (including no-op)
    assert (tmp_path / "graphinfo.json").exists()
    assert json.loads((tmp_path / "graphinfo.json").read_bytes()) == _FAKE_GRAPHINFO


def test_empty_releases_returns_false(tmp_path, monkeypatch):
    from feedcache.sources import common_crawl_ranks

    _patch_http(monkeypatch, {
        common_crawl_ranks.GRAPHINFO_URL: lambda url, **kw: _FakeResponse(
            content=b"[]", json_data=[]
        ),
    })

    assert common_crawl_ranks.run(str(tmp_path)) is False
    # Empty releases → False return → nothing written to data/ at all.
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_common_crawl_ranks.py -v`
Expected: Both new tests fail — `NotImplementedError` from the stub.

- [ ] **Step 3: Implement graphinfo fetch + early-return**

Replace the body of `/home/wangmm/feedcache/feedcache/sources/common_crawl_ranks.py` with:

```python
from pathlib import Path

import requests

from feedcache.common import write_if_changed


GRAPHINFO_URL = "https://index.commoncrawl.org/graphinfo.json"
BASE_URL = "https://data.commoncrawl.org/projects/hyperlinkgraph"
TOP_N = 1_000_000
TIMEOUT = 600


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    graphinfo_resp = requests.get(GRAPHINFO_URL, timeout=30)
    graphinfo_resp.raise_for_status()
    releases = graphinfo_resp.json()
    if not releases:
        return False
    release_id = releases[0]["id"]

    current_release = out / "host" / "current.release.txt"
    if current_release.exists() and current_release.read_text().strip() == release_id:
        write_if_changed(graphinfo_resp.content, out / "graphinfo.json")
        return True

    # Full download path is implemented in Task 3-5.
    raise NotImplementedError("ranks download path not yet implemented")
```

- [ ] **Step 4: Run tests to verify the two new tests pass**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_common_crawl_ranks.py -v`
Expected: `test_module_importable_and_exposes_run`, `test_noop_early_return_when_release_unchanged`, `test_empty_releases_returns_false` all PASS. (The future full-download tests don't exist yet.)

- [ ] **Step 5: Commit**

```bash
cd /home/wangmm/feedcache
git add feedcache/sources/common_crawl_ranks.py tests/test_common_crawl_ranks.py
git commit -m "feat(common-crawl-ranks): graphinfo discovery + no-op early-return

Fetches https://index.commoncrawl.org/graphinfo.json, shorts out when
host/current.release.txt already matches the latest release id, and
refreshes data/graphinfo.json on every run."
```

---

## Task 3: Stream-truncate and transform host ranks into a CSV buffer

**Files:**
- Modify: `/home/wangmm/feedcache/feedcache/sources/common_crawl_ranks.py`
- Modify: `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`

- [ ] **Step 1: Write fixture builder + transform test**

Append to `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`:

```python
def _build_ranks_gz(rows):
    """rows = list of (hc_pos, hc_val, pr_pos, pr_val, entity_rev) tuples.
    Returns gzip-compressed, tab-separated bytes matching CC upstream schema."""
    header = "#harmonicc_pos\t#harmonicc_val\t#pr_pos\t#pr_val\t#host_rev\n"
    body = "".join("\t".join(row) + "\n" for row in rows)
    return gzip.compress((header + body).encode("utf-8"), mtime=0)


_FAKE_HOST_ROWS = [
    ("1", "3.75E7", "5",  "0.0049", "com.facebook.www"),
    ("2", "3.73E7", "4",  "0.0064", "com.googleapis.fonts"),
    ("3", "3.46E7", "2",  "0.0083", "com.google.www"),
    ("4", "3.37E7", "6",  "0.0043", "com.googletagmanager.www"),
    ("5", "3.10E7", "8",  "0.0030", "org.wikipedia.en"),
    ("6", "2.90E7", "9",  "0.0025", "com.youtube.www"),
    ("7", "2.80E7", "11", "0.0020", "com.twitter"),
    ("8", "2.70E7", "13", "0.0018", "com.linkedin.www"),
    ("9", "2.60E7", "14", "0.0015", "com.github"),
    ("10", "2.50E7", "17", "0.0011", "org.mozilla.www"),
]


def test_truncate_and_transform_host(monkeypatch, tmp_path):
    from feedcache.sources import common_crawl_ranks as m

    monkeypatch.setattr(m, "TOP_N", 3)

    _patch_http(monkeypatch, {
        m.GRAPHINFO_URL: lambda url, **kw: _FakeResponse(
            content=_FAKE_GRAPHINFO_BYTES, json_data=_FAKE_GRAPHINFO
        ),
        "host-ranks.txt.gz": lambda url, **kw: _FakeResponse(
            raw_bytes=_build_ranks_gz(_FAKE_HOST_ROWS)
        ),
    })

    host_bytes = m._download_ranks("cc-main-2026-jan-feb-mar", "host", "host")
    text = host_bytes.decode("utf-8").splitlines()

    assert text[0] == "rank,harmonicc_val,pr_pos,pr_val,host"
    # TOP_N=3, so 3 data rows
    assert len(text) == 4
    # Reversed host column
    assert text[1] == "1,3.75E7,5,0.0049,www.facebook.com"
    assert text[2] == "2,3.73E7,4,0.0064,fonts.googleapis.com"
    assert text[3] == "3,3.46E7,2,0.0083,www.google.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_common_crawl_ranks.py::test_truncate_and_transform_host -v`
Expected: `AttributeError: module ... has no attribute '_download_ranks'`.

- [ ] **Step 3: Implement `_download_ranks` and transform**

Replace `/home/wangmm/feedcache/feedcache/sources/common_crawl_ranks.py` with:

```python
import csv
import gzip
import io
from pathlib import Path

import requests

from feedcache.common import write_if_changed


GRAPHINFO_URL = "https://index.commoncrawl.org/graphinfo.json"
BASE_URL = "https://data.commoncrawl.org/projects/hyperlinkgraph"
TOP_N = 1_000_000
TIMEOUT = 600


def _ranks_url(release_id: str, level: str) -> str:
    return f"{BASE_URL}/{release_id}/{level}/{release_id}-{level}-ranks.txt.gz"


def _reverse_entity(entity_rev: str) -> str:
    return ".".join(reversed(entity_rev.split(".")))


def _truncate_and_transform(response, entity_col: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["rank", "harmonicc_val", "pr_pos", "pr_val", entity_col])
    with gzip.GzipFile(fileobj=response.raw) as gz:
        reader = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        header = next(reader)
        if not header.startswith("#harmonicc_pos"):
            raise RuntimeError(f"unexpected ranks header: {header!r}")
        for i, line in enumerate(reader, start=1):
            if i > TOP_N:
                break
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 5:
                raise RuntimeError(f"malformed ranks line {i}: {line!r}")
            hc_pos, hc_val, pr_pos, pr_val, entity_rev = fields
            w.writerow([hc_pos, hc_val, pr_pos, pr_val, _reverse_entity(entity_rev)])
    return buf.getvalue().encode("utf-8")


def _download_ranks(release_id: str, level: str, entity_col: str) -> bytes:
    url = _ranks_url(release_id, level)
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        return _truncate_and_transform(r, entity_col)


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    graphinfo_resp = requests.get(GRAPHINFO_URL, timeout=30)
    graphinfo_resp.raise_for_status()
    releases = graphinfo_resp.json()
    if not releases:
        return False
    release_id = releases[0]["id"]

    current_release = out / "host" / "current.release.txt"
    if current_release.exists() and current_release.read_text().strip() == release_id:
        write_if_changed(graphinfo_resp.content, out / "graphinfo.json")
        return True

    # Full write path is implemented in Task 5.
    raise NotImplementedError("ranks disk-write path not yet implemented")
```

- [ ] **Step 4: Run tests**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_common_crawl_ranks.py -v`
Expected: `test_truncate_and_transform_host` PASSES along with Task 1-2 tests.

- [ ] **Step 5: Commit**

```bash
cd /home/wangmm/feedcache
git add feedcache/sources/common_crawl_ranks.py tests/test_common_crawl_ranks.py
git commit -m "feat(common-crawl-ranks): streaming Top-N truncate + host_rev reversal

Adds _download_ranks() that streams a gzipped upstream ranks file,
stops reading after TOP_N rows, and emits a 5-column CSV with the
host/domain de-reversed. Level-agnostic: entity_col controls the
final column name (host vs. domain)."
```

---

## Task 4: Support domain level (sanity-check the same function works)

**Files:**
- Modify: `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`

- [ ] **Step 1: Add a domain-level transform test**

Append to `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`:

```python
_FAKE_DOMAIN_ROWS = [
    ("1", "9.1E7", "2", "0.005", "com.google"),
    ("2", "9.0E7", "1", "0.006", "com.facebook"),
    ("3", "8.5E7", "3", "0.004", "org.wikipedia"),
]


def test_truncate_and_transform_domain(monkeypatch, tmp_path):
    from feedcache.sources import common_crawl_ranks as m

    monkeypatch.setattr(m, "TOP_N", 3)

    _patch_http(monkeypatch, {
        m.GRAPHINFO_URL: lambda url, **kw: _FakeResponse(
            content=_FAKE_GRAPHINFO_BYTES, json_data=_FAKE_GRAPHINFO
        ),
        "domain-ranks.txt.gz": lambda url, **kw: _FakeResponse(
            raw_bytes=_build_ranks_gz(_FAKE_DOMAIN_ROWS)
        ),
    })

    domain_bytes = m._download_ranks("cc-main-2026-jan-feb-mar", "domain", "domain")
    text = domain_bytes.decode("utf-8").splitlines()

    assert text[0] == "rank,harmonicc_val,pr_pos,pr_val,domain"
    assert len(text) == 4
    assert text[1] == "1,9.1E7,2,0.005,google.com"
    assert text[2] == "2,9.0E7,1,0.006,facebook.com"
    assert text[3] == "3,8.5E7,3,0.004,wikipedia.org"
```

- [ ] **Step 2: Run test to verify it passes immediately**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_common_crawl_ranks.py::test_truncate_and_transform_domain -v`
Expected: PASS — no code change needed because `_download_ranks` already parameterizes `level` and `entity_col`. This test exists to lock that parameterization against future regressions.

- [ ] **Step 3: Commit**

```bash
cd /home/wangmm/feedcache
git add tests/test_common_crawl_ranks.py
git commit -m "test(common-crawl-ranks): regression test for domain level

Locks in that _download_ranks emits a 'domain' header column and
correctly reverses domain_rev entries at the domain granularity."
```

---

## Task 5: Atomic writes of both levels + current pointers + graphinfo.json snapshot

**Files:**
- Modify: `/home/wangmm/feedcache/feedcache/sources/common_crawl_ranks.py`
- Modify: `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`

- [ ] **Step 1: Write the end-to-end happy-path test**

Append to `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`:

```python
def test_end_to_end_writes_all_outputs(tmp_path, monkeypatch):
    from feedcache.sources import common_crawl_ranks as m

    monkeypatch.setattr(m, "TOP_N", 3)

    _patch_http(monkeypatch, {
        m.GRAPHINFO_URL: lambda url, **kw: _FakeResponse(
            content=_FAKE_GRAPHINFO_BYTES, json_data=_FAKE_GRAPHINFO
        ),
        "host-ranks.txt.gz": lambda url, **kw: _FakeResponse(
            raw_bytes=_build_ranks_gz(_FAKE_HOST_ROWS)
        ),
        "domain-ranks.txt.gz": lambda url, **kw: _FakeResponse(
            raw_bytes=_build_ranks_gz(_FAKE_DOMAIN_ROWS)
        ),
    })

    assert m.run(str(tmp_path)) is True

    # --- host side ---
    host_dir = tmp_path / "host"
    host_csvs = sorted(p.name for p in host_dir.glob("*.csv.gz"))
    assert len(host_csvs) == 2, host_csvs  # one dated snapshot + current.csv.gz
    assert "current.csv.gz" in host_csvs
    dated_host = [n for n in host_csvs if n != "current.csv.gz"][0]
    assert dated_host.endswith("_cc-main-2026-jan-feb-mar.csv.gz")
    # current.csv.gz is byte-equal to the dated snapshot
    assert (host_dir / "current.csv.gz").read_bytes() == (host_dir / dated_host).read_bytes()
    # Release sidecar
    assert (host_dir / "current.release.txt").read_text().strip() == "cc-main-2026-jan-feb-mar"
    # Decompressed content starts with the expected CSV header
    decompressed = gzip.decompress((host_dir / "current.csv.gz").read_bytes()).decode()
    assert decompressed.splitlines()[0] == "rank,harmonicc_val,pr_pos,pr_val,host"
    assert decompressed.splitlines()[1] == "1,3.75E7,5,0.0049,www.facebook.com"

    # --- domain side ---
    domain_dir = tmp_path / "domain"
    domain_csvs = sorted(p.name for p in domain_dir.glob("*.csv.gz"))
    assert len(domain_csvs) == 2
    assert (domain_dir / "current.release.txt").read_text().strip() == "cc-main-2026-jan-feb-mar"
    assert gzip.decompress((domain_dir / "current.csv.gz").read_bytes()).decode().splitlines()[0] == \
        "rank,harmonicc_val,pr_pos,pr_val,domain"

    # --- top-level graphinfo snapshot ---
    assert json.loads((tmp_path / "graphinfo.json").read_bytes()) == _FAKE_GRAPHINFO


def test_second_run_is_idempotent_noop(tmp_path, monkeypatch):
    """Run twice back-to-back: second run should hit the early-return path
    because current.release.txt already matches."""
    from feedcache.sources import common_crawl_ranks as m

    monkeypatch.setattr(m, "TOP_N", 3)

    _patch_http(monkeypatch, {
        m.GRAPHINFO_URL: lambda url, **kw: _FakeResponse(
            content=_FAKE_GRAPHINFO_BYTES, json_data=_FAKE_GRAPHINFO
        ),
        "host-ranks.txt.gz": lambda url, **kw: _FakeResponse(
            raw_bytes=_build_ranks_gz(_FAKE_HOST_ROWS)
        ),
        "domain-ranks.txt.gz": lambda url, **kw: _FakeResponse(
            raw_bytes=_build_ranks_gz(_FAKE_DOMAIN_ROWS)
        ),
    })

    assert m.run(str(tmp_path)) is True
    first_listing = sorted(p.name for p in (tmp_path / "host").iterdir())

    assert m.run(str(tmp_path)) is True
    second_listing = sorted(p.name for p in (tmp_path / "host").iterdir())

    assert first_listing == second_listing, (first_listing, second_listing)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_common_crawl_ranks.py::test_end_to_end_writes_all_outputs -v`
Expected: `NotImplementedError: ranks disk-write path not yet implemented`.

- [ ] **Step 3: Finish `run()` with atomic writes**

Replace `/home/wangmm/feedcache/feedcache/sources/common_crawl_ranks.py` with:

```python
import csv
import gzip
import io
from pathlib import Path

import requests

from feedcache.common import (
    deterministic_gzip,
    today_utc_date,
    update_current,
    write_if_changed,
)


GRAPHINFO_URL = "https://index.commoncrawl.org/graphinfo.json"
BASE_URL = "https://data.commoncrawl.org/projects/hyperlinkgraph"
TOP_N = 1_000_000
TIMEOUT = 600


def _ranks_url(release_id: str, level: str) -> str:
    return f"{BASE_URL}/{release_id}/{level}/{release_id}-{level}-ranks.txt.gz"


def _reverse_entity(entity_rev: str) -> str:
    return ".".join(reversed(entity_rev.split(".")))


def _truncate_and_transform(response, entity_col: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["rank", "harmonicc_val", "pr_pos", "pr_val", entity_col])
    with gzip.GzipFile(fileobj=response.raw) as gz:
        reader = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        header = next(reader)
        if not header.startswith("#harmonicc_pos"):
            raise RuntimeError(f"unexpected ranks header: {header!r}")
        for i, line in enumerate(reader, start=1):
            if i > TOP_N:
                break
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 5:
                raise RuntimeError(f"malformed ranks line {i}: {line!r}")
            hc_pos, hc_val, pr_pos, pr_val, entity_rev = fields
            w.writerow([hc_pos, hc_val, pr_pos, pr_val, _reverse_entity(entity_rev)])
    return buf.getvalue().encode("utf-8")


def _download_ranks(release_id: str, level: str, entity_col: str) -> bytes:
    url = _ranks_url(release_id, level)
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        return _truncate_and_transform(r, entity_col)


def run(out_dir: str) -> bool:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    graphinfo_resp = requests.get(GRAPHINFO_URL, timeout=30)
    graphinfo_resp.raise_for_status()
    releases = graphinfo_resp.json()
    if not releases:
        return False
    release_id = releases[0]["id"]

    current_release_host = out / "host" / "current.release.txt"
    if current_release_host.exists() and current_release_host.read_text().strip() == release_id:
        write_if_changed(graphinfo_resp.content, out / "graphinfo.json")
        return True

    # Fetch both levels fully into memory before any disk write.
    host_bytes = _download_ranks(release_id, "host", "host")
    domain_bytes = _download_ranks(release_id, "domain", "domain")

    host_dir = out / "host"
    domain_dir = out / "domain"
    host_dir.mkdir(parents=True, exist_ok=True)
    domain_dir.mkdir(parents=True, exist_ok=True)

    date = today_utc_date()
    snapshot_name = f"{date}_{release_id}.csv.gz"

    deterministic_gzip(host_bytes, host_dir / snapshot_name)
    deterministic_gzip(domain_bytes, domain_dir / snapshot_name)

    update_current(host_dir, "????-??-??_*.csv.gz", "current.csv.gz")
    update_current(domain_dir, "????-??-??_*.csv.gz", "current.csv.gz")

    release_line = (release_id + "\n").encode("utf-8")
    write_if_changed(release_line, host_dir / "current.release.txt")
    write_if_changed(release_line, domain_dir / "current.release.txt")
    write_if_changed(graphinfo_resp.content, out / "graphinfo.json")
    return True
```

- [ ] **Step 4: Run tests**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_common_crawl_ranks.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/wangmm/feedcache
git add feedcache/sources/common_crawl_ranks.py tests/test_common_crawl_ranks.py
git commit -m "feat(common-crawl-ranks): atomic writes + current pointers

Completes run() by downloading both levels into memory, then
(only on success) writing dated snapshot files, current.csv.gz
pointers, current.release.txt sidecars, and a verbatim
graphinfo.json snapshot. Re-running the same release is a no-op."
```

---

## Task 6: Error handling — malformed row and missing upstream

**Files:**
- Modify: `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`

- [ ] **Step 1: Add failure-path tests**

Append to `/home/wangmm/feedcache/tests/test_common_crawl_ranks.py`:

```python
def test_malformed_line_aborts_without_writing(tmp_path, monkeypatch):
    from feedcache.sources import common_crawl_ranks as m

    # Row with only 4 tab-separated fields instead of 5.
    bad_gz = gzip.compress(
        b"#harmonicc_pos\t#harmonicc_val\t#pr_pos\t#pr_val\t#host_rev\n"
        b"1\t3.75E7\t5\t0.0049\n",
        mtime=0,
    )

    _patch_http(monkeypatch, {
        m.GRAPHINFO_URL: lambda url, **kw: _FakeResponse(
            content=_FAKE_GRAPHINFO_BYTES, json_data=_FAKE_GRAPHINFO
        ),
        "host-ranks.txt.gz": lambda url, **kw: _FakeResponse(raw_bytes=bad_gz),
        # domain fetch never happens because host raises first
    })

    with pytest.raises(RuntimeError, match="malformed ranks line"):
        m.run(str(tmp_path))

    # Nothing under data/host or data/domain
    if (tmp_path / "host").exists():
        assert list((tmp_path / "host").glob("*.csv.gz")) == []
    if (tmp_path / "domain").exists():
        assert list((tmp_path / "domain").glob("*.csv.gz")) == []


def test_ranks_404_propagates_without_partial_writes(tmp_path, monkeypatch):
    from feedcache.sources import common_crawl_ranks as m

    class _NotFound(_FakeResponse):
        def raise_for_status(self):
            import requests as _rq
            err = _rq.HTTPError("404 Not Found")
            raise err

    _patch_http(monkeypatch, {
        m.GRAPHINFO_URL: lambda url, **kw: _FakeResponse(
            content=_FAKE_GRAPHINFO_BYTES, json_data=_FAKE_GRAPHINFO
        ),
        "host-ranks.txt.gz": lambda url, **kw: _NotFound(raw_bytes=b""),
    })

    import requests as _rq
    with pytest.raises(_rq.HTTPError):
        m.run(str(tmp_path))

    if (tmp_path / "host").exists():
        assert list((tmp_path / "host").glob("*.csv.gz")) == []
    if (tmp_path / "domain").exists():
        assert list((tmp_path / "domain").glob("*.csv.gz")) == []
```

Note on exception propagation: `run()` lets exceptions propagate so the GitHub-Actions step surfaces the failure (feedcache sources generally return True/False only for *anticipated* outcomes). The reusable workflow's shell step treats any nonzero exit code as a failure.

- [ ] **Step 2: Run tests**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_common_crawl_ranks.py -v`
Expected: all 9 tests PASS. No code change is needed — the existing implementation already raises on malformed rows (Task 3) and propagates HTTPError from `response.raise_for_status()` (Task 3).

- [ ] **Step 3: Commit**

```bash
cd /home/wangmm/feedcache
git add tests/test_common_crawl_ranks.py
git commit -m "test(common-crawl-ranks): malformed-row + 404 atomicity regression tests

Locks in that partial upstream failures leave the data directory
free of any dated csv.gz files."
```

---

## Task 7: Register the source in the CLI

**Files:**
- Modify: `/home/wangmm/feedcache/feedcache/__main__.py`
- Modify: `/home/wangmm/feedcache/tests/test_cli.py`

- [ ] **Step 1: Extend `test_cli_help` assertions**

In `/home/wangmm/feedcache/tests/test_cli.py`, add a new assertion inside `test_cli_help`:

```python
    assert "common-crawl-ranks" in result.stdout
```

Place it alongside the other `assert "X" in result.stdout` lines (e.g. right after `"aggregate-top-domains"`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/wangmm/feedcache && python -m pytest tests/test_cli.py::test_cli_help -v`
Expected: FAIL — `assert "common-crawl-ranks" in result.stdout` because the source is not registered yet.

- [ ] **Step 3: Register the source**

Edit `/home/wangmm/feedcache/feedcache/__main__.py`. Replace the existing import line:

```python
from feedcache.sources import aggregate_top_domains, cloud_ip_ranges, cloudflare_radar, majestic, public_suffix_list, tranco, umbrella
```

with:

```python
from feedcache.sources import aggregate_top_domains, cloud_ip_ranges, cloudflare_radar, common_crawl_ranks, majestic, public_suffix_list, tranco, umbrella
```

And in the `SOURCES` dict, add this entry after `"cloudflare-radar": cloudflare_radar.run,`:

```python
    "common-crawl-ranks": common_crawl_ranks.run,
```

- [ ] **Step 4: Run the full test suite**

Run: `cd /home/wangmm/feedcache && python -m pytest -v`
Expected: every existing test still passes; `test_cli_help` now passes; 9 new `common_crawl_ranks` tests all pass.

- [ ] **Step 5: Commit**

```bash
cd /home/wangmm/feedcache
git add feedcache/__main__.py tests/test_cli.py
git commit -m "feat(cli): register common-crawl-ranks source

Adds \"common-crawl-ranks\" to the SOURCES dispatch table so that
feedcache common-crawl-ranks <out_dir> runs the new source."
```

---

## Task 8: Update the design doc to reflect the 9th repo

**Files:**
- Modify: `/home/wangmm/feedcache/docs/design.md`

- [ ] **Step 1: Register the new data repo in the repo topology diagram**

In `/home/wangmm/feedcache/docs/design.md`, inside the code block under **§2 Repository topology**, add this line to the "mirror" group (between the existing `cloud-ip-ranges-cache` and the blank line before `top-domains-aggregate`):

```
├── wangmm001/common-crawl-ranks-cache    ← mirror (daily cron, quarterly content)
```

- [ ] **Step 2: Add a row in the §3 data-repositories table**

Inside the `## 3. Data repositories` table, insert this row between the `cloud-ip-ranges-cache` row and the `top-domains-aggregate` row:

```
| `common-crawl-ranks-cache` | mirror | CC `https://index.commoncrawl.org/graphinfo.json` + per-release `host/domain-ranks.txt.gz` | 04:30 | `data/{host,domain}/YYYY-MM-DD_<release-id>.csv.gz`, `data/{host,domain}/current.csv.gz`, `data/{host,domain}/current.release.txt`, `data/graphinfo.json` |
```

- [ ] **Step 3: Add §5a entry for common-crawl-ranks**

Inside `## 5. Source types — three patterns`, under `### 5a. Direct mirror`, after the `**cloud-ip-ranges** (...)` block, add:

```markdown
**common-crawl-ranks** (`common_crawl_ranks.py`)
- Upstream discovery: `https://index.commoncrawl.org/graphinfo.json` — JSON array of releases, newest first. The source reads `releases[0]["id"]` (e.g. `cc-main-2026-jan-feb-mar`).
- Idempotence: if `data/host/current.release.txt` already matches the latest release id, the run refreshes only `data/graphinfo.json` and short-circuits. Common Crawl publishes roughly one release per quarter, so daily cron short-circuits on ~90% of days.
- Per-release fetch: `https://data.commoncrawl.org/projects/hyperlinkgraph/{release}/{host,domain}/{release}-{host,domain}-ranks.txt.gz`. Streamed + Top-1M-truncated in a single pass so only the first ~15–25 MB per level is actually transferred (raw files are 2.5–5.6 GB compressed).
- Output per run: `data/host/YYYY-MM-DD_{release-id}.csv.gz` + `data/domain/YYYY-MM-DD_{release-id}.csv.gz`, plus their `current.csv.gz` / `current.release.txt` siblings, plus `data/graphinfo.json`.
- Columns: `rank,harmonicc_val,pr_pos,pr_val,{host,domain}` — upstream `#host_rev` is reversed (`com.facebook.www` → `www.facebook.com`).
- No auth; no new secrets.
```

- [ ] **Step 4: Spot-check the whole file still reads coherently**

Run: `grep -n "common-crawl-ranks" /home/wangmm/feedcache/docs/design.md` — expect at least 4 hits. Skim the §3 table and §5a section for prose consistency; fix any number-off-by-one references in §4 or §5a headings if necessary (e.g. if a count like "6 sources in 6 data repos" appears, bump it to 7).

Specifically: update the subsection header `### 5a. Direct mirror (6 sources in 6 data repos)` to `### 5a. Direct mirror (7 sources in 7 data repos)`.

- [ ] **Step 5: Commit**

```bash
cd /home/wangmm/feedcache
git add docs/design.md
git commit -m "docs(design): register common-crawl-ranks source + data repo

Updates §2 topology, §3 table, §5a narrative, and the 6-vs-7 count
in the §5a header to account for the new mirror."
```

---

## Task 9: Create the `common-crawl-ranks-cache` data-repo skeleton locally

**Files:**
- Create: `/home/wangmm/common-crawl-ranks-cache/LICENSE`
- Create: `/home/wangmm/common-crawl-ranks-cache/README.md`
- Create: `/home/wangmm/common-crawl-ranks-cache/.github/workflows/cron.yml`
- Create: `/home/wangmm/common-crawl-ranks-cache/.gitignore`

- [ ] **Step 1: Create the directory + git init**

Run:
```bash
mkdir -p /home/wangmm/common-crawl-ranks-cache/.github/workflows
cd /home/wangmm/common-crawl-ranks-cache
git init -b main
```

- [ ] **Step 2: Write LICENSE**

Create `/home/wangmm/common-crawl-ranks-cache/LICENSE`:

```
Scaffolding (README, workflow yml): MIT.

Data (`data/`): derived from Common Crawl's published web-graph ranks,
which are subject to the Common Crawl Terms of Use at
https://commoncrawl.org/terms-of-use. Redistribution of the data
should honor those terms.
```

- [ ] **Step 3: Write README.md**

Create `/home/wangmm/common-crawl-ranks-cache/README.md`:

````markdown
# common-crawl-ranks-cache

Daily-polled mirror of [Common Crawl](https://commoncrawl.org) host- and domain-level web-graph ranks, Top-1M per release, produced by [`wangmm001/feedcache`](https://github.com/wangmm001/feedcache).

Common Crawl publishes a new web-graph roughly every quarter; this repo's daily cron therefore commits new files ~4 times a year. On all other days the run short-circuits without a commit.

## Layout

```
data/
├── host/
│   ├── YYYY-MM-DD_<release-id>.csv.gz     # e.g. 2026-04-21_cc-main-2026-jan-feb-mar.csv.gz
│   ├── current.csv.gz                     # pointer to the newest snapshot
│   └── current.release.txt                # plain-text: release id of current.csv.gz
├── domain/
│   └── …same shape as host/
└── graphinfo.json                         # verbatim copy of upstream release index, refreshed daily
```

## Format

Gzipped CSV, 5 columns, header-first, comma-separated:

```
rank,harmonicc_val,pr_pos,pr_val,host
1,3.7549092E7,5,0.004897432273872421,www.facebook.com
2,3.7300396E7,4,0.006354617185491388,fonts.googleapis.com
…
```

| Column | Meaning |
|---|---|
| `rank` | Position in upstream `#harmonicc_pos`, 1 through 1,000,000. |
| `harmonicc_val` | Harmonic Centrality score (scientific notation). |
| `pr_pos` | PageRank position for the same entity. |
| `pr_val` | PageRank score. |
| `host` (or `domain`) | Forward-order host/domain; upstream stores reverse-domain form, this mirror un-reverses it. |

Rows sorted by `rank` ascending. The `domain/` file is the same schema but with `domain` as the last column and one row per registrable domain.

## Consume

```bash
# Latest top-100 hosts by harmonic centrality
curl -sL https://raw.githubusercontent.com/wangmm001/common-crawl-ranks-cache/main/data/host/current.csv.gz \
  | zcat | head -101

# Which Common Crawl release is "current"?
curl -sL https://raw.githubusercontent.com/wangmm001/common-crawl-ranks-cache/main/data/host/current.release.txt
```

## Known simplifications

- Only the Top-1M entries by Harmonic Centrality are kept; full upstream ranks (~288M hosts, ~134M domains per release) are not mirrored. See the feedcache design doc for rationale.
- The `domain` granularity here is Common Crawl's own reverse-domain-merge, not Public Suffix List eTLD+1. These usually agree but disagree around user-content public suffixes such as `github.io`.
- No historical backfill: the repo starts with whatever release is current at the first cron run.

## License

Scaffolding: MIT. Data: subject to [Common Crawl's Terms of Use](https://commoncrawl.org/terms-of-use).

## How it works

Daily GitHub Actions cron (04:30 UTC) calls `wangmm001/feedcache`'s reusable workflow with `source: common-crawl-ranks`. The step `pip install`s feedcache at `main`, runs `feedcache common-crawl-ranks data/`, and commits any new files. Deterministic gzip + `git diff --cached --quiet` means no commit on unchanged days.
````

- [ ] **Step 4: Write the cron workflow**

Create `/home/wangmm/common-crawl-ranks-cache/.github/workflows/cron.yml`:

```yaml
name: daily
on:
  schedule:
    - cron: "30 4 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  snapshot:
    uses: wangmm001/feedcache/.github/workflows/reusable-snapshot.yml@main
    with:
      source: common-crawl-ranks
```

- [ ] **Step 5: Write a .gitignore**

Create `/home/wangmm/common-crawl-ranks-cache/.gitignore`:

```
__pycache__/
*.pyc
.DS_Store
```

- [ ] **Step 6: Commit the initial skeleton**

```bash
cd /home/wangmm/common-crawl-ranks-cache
git add LICENSE README.md .github/workflows/cron.yml .gitignore
git commit -m "chore: initial scaffold for common-crawl-ranks-cache

LICENSE + README + GitHub Actions cron that calls feedcache's
reusable snapshot workflow. No data/ yet; the first scheduled
run populates it."
```

---

## Task 10: Publish (requires explicit user confirmation)

**Files:**
- No local files changed.

> Stop and confirm with the user before running these commands. Pushing to GitHub is not locally reversible. Specifically: the user must approve (a) pushing `main` on `wangmm001/feedcache` and (b) creating + pushing `wangmm001/common-crawl-ranks-cache`.

- [ ] **Step 1: Push feedcache changes to origin**

Run:
```bash
cd /home/wangmm/feedcache
git status                  # confirm: main is clean, ahead of origin by N commits
git log --oneline origin/main..HEAD    # review what will be pushed
git push origin main
```
Expected: remote accepts the push; `test.yml` runs on GitHub and passes.

- [ ] **Step 2: Create the GitHub data repo**

Run:
```bash
gh repo create wangmm001/common-crawl-ranks-cache \
    --public \
    --description "Daily mirror of Common Crawl host/domain Top-1M web-graph ranks (feedcache)." \
    --disable-wiki
```
Expected: gh prints the new repo URL. The command creates the remote only — no code is pushed yet.

- [ ] **Step 3: Push the local skeleton**

Run:
```bash
cd /home/wangmm/common-crawl-ranks-cache
git remote add origin https://github.com/wangmm001/common-crawl-ranks-cache.git
git push -u origin main
```
Expected: remote accepts the push; new repo lands on GitHub with LICENSE + README + workflow.

- [ ] **Step 4: Verify the GitHub Actions workflow is visible**

Run:
```bash
gh workflow list --repo wangmm001/common-crawl-ranks-cache
```
Expected: the `daily` workflow is listed. GitHub may need up to a minute to register it after the first push.

- [ ] **Step 5: Commit locally (no-op — nothing to commit; this step is a checkpoint)**

Nothing new to commit; the skeleton commit from Task 9 is already pushed.

---

## Task 11: Trigger the first run and verify output

**Files:**
- No local files changed.

- [ ] **Step 1: Dispatch the workflow manually**

Run:
```bash
gh workflow run daily --repo wangmm001/common-crawl-ranks-cache
```
Expected: gh returns `✓ Created workflow_dispatch event for daily.yml at main` (or similar).

- [ ] **Step 2: Watch the run**

Run:
```bash
gh run list --repo wangmm001/common-crawl-ranks-cache --limit 1
# Get the <run-id> from the previous output:
gh run watch <run-id> --repo wangmm001/common-crawl-ranks-cache
```
Expected: run succeeds; total runtime a few minutes (download ≈ a few tens of MB over CloudFront).

- [ ] **Step 3: Confirm data landed**

Run:
```bash
gh api repos/wangmm001/common-crawl-ranks-cache/contents/data/host | python -m json.tool
curl -sL https://raw.githubusercontent.com/wangmm001/common-crawl-ranks-cache/main/data/host/current.release.txt
curl -sL https://raw.githubusercontent.com/wangmm001/common-crawl-ranks-cache/main/data/host/current.csv.gz | gunzip -c | head -5
```
Expected:
- `data/host/` contains `current.csv.gz`, `current.release.txt`, one `YYYY-MM-DD_<release-id>.csv.gz` file.
- `current.release.txt` contains the latest CC release id (at plan-writing time: `cc-main-2026-jan-feb-mar`).
- The CSV head shows `rank,harmonicc_val,pr_pos,pr_val,host` + 4 data rows with forward-order hostnames.

- [ ] **Step 4: Spot-check row count and domain side**

Run:
```bash
curl -sL https://raw.githubusercontent.com/wangmm001/common-crawl-ranks-cache/main/data/host/current.csv.gz | gunzip -c | wc -l
# Expected: 1000001 (1 header + 1M rows)
curl -sL https://raw.githubusercontent.com/wangmm001/common-crawl-ranks-cache/main/data/domain/current.csv.gz | gunzip -c | wc -l
# Expected: 1000001
```

- [ ] **Step 5: No commit needed**

This task is verification only; no local files change.

---

## Spec coverage verification

| Spec section | Task(s) implementing it |
|---|---|
| §1 Goal | Tasks 1–11 collectively |
| §2 Scope — new source module + CLI command | Tasks 1, 7 |
| §2 Scope — new data repo skeleton | Task 9 |
| §2 Scope — unit tests | Tasks 1–6 |
| §2 Scope — design.md update | Task 8 |
| §2 Out of scope — aggregate untouched | Enforced by plan contents (no aggregate edits) |
| §3 Repository topology | Tasks 8, 9 |
| §4 Data layout | Task 5 (writes) + Task 9 (README) |
| §5 CSV schema | Task 3 + Task 4 |
| §6 Upstream discovery + idempotence | Task 2 |
| §7 Streaming truncation | Task 3 |
| §8 Error handling + atomicity | Tasks 5, 6 |
| §9 Testing — 6 enumerated test patterns | Tasks 1, 2, 3, 5, 6, 7 cover all 6 |
| §10 GitHub Actions wiring | Task 9 (cron.yml) + Task 10 (push + workflow dispatch) |
| §11 Known simplifications | Task 9 README + Task 8 design.md |
| §12 Future work | Out of scope; documented in spec only |

No gaps.
