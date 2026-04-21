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
