def test_module_importable_and_exposes_run():
    from feedcache.sources import common_crawl_ranks
    assert callable(common_crawl_ranks.run)

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
