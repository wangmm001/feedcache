import gzip
import io
import zipfile
from pathlib import Path

import pytest


_FAKE_CSV = (
    b'"Rank","Domain","Open Page Rank"\n'
    b'"1","www.facebook.com","10.00"\n'
    b'"2","fonts.googleapis.com","10.00"\n'
)


def _zip_bytes(csv_bytes: bytes, name: str = "top10milliondomains.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, csv_bytes)
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, *, status_code=200, body=b"", headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


def _patch_get(monkeypatch, response_factory):
    from feedcache.sources import domcop

    captured = {}

    def fake_get(url, headers=None, stream=False, timeout=None):
        assert url == domcop.UPSTREAM_URL
        captured["headers"] = dict(headers or {})
        return response_factory()

    monkeypatch.setattr(domcop.requests, "get", fake_get)
    return captured


def test_domcop_first_run_writes_snapshot_and_lastmod(tmp_path, monkeypatch):
    from feedcache.sources import domcop

    zip_bytes = _zip_bytes(_FAKE_CSV)
    captured = _patch_get(
        monkeypatch,
        lambda: _FakeResponse(
            status_code=200,
            body=zip_bytes,
            headers={"Last-Modified": "Sun, 29 Mar 2026 11:30:31 GMT"},
        ),
    )

    assert domcop.run(str(tmp_path)) is True
    assert "If-Modified-Since" not in captured["headers"]

    names = sorted(p.name for p in tmp_path.iterdir())
    assert "current.csv.gz" in names
    assert "current.last-modified.txt" in names
    dated = [n for n in names if n.endswith(".csv.gz") and n != "current.csv.gz"]
    assert len(dated) == 1, names

    assert gzip.decompress((tmp_path / "current.csv.gz").read_bytes()) == _FAKE_CSV
    assert (tmp_path / "current.last-modified.txt").read_text().strip() == (
        "Sun, 29 Mar 2026 11:30:31 GMT"
    )


def test_domcop_sends_if_modified_since_and_skips_on_304(tmp_path, monkeypatch):
    from feedcache.sources import domcop

    (tmp_path / "current.last-modified.txt").write_text(
        "Sun, 29 Mar 2026 11:30:31 GMT\n"
    )
    captured = _patch_get(
        monkeypatch,
        lambda: _FakeResponse(status_code=304),
    )

    assert domcop.run(str(tmp_path)) is True
    assert captured["headers"]["If-Modified-Since"] == (
        "Sun, 29 Mar 2026 11:30:31 GMT"
    )

    # Nothing new landed on disk.
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["current.last-modified.txt"]


def test_domcop_refreshes_when_upstream_changes(tmp_path, monkeypatch):
    from feedcache.sources import domcop

    (tmp_path / "current.last-modified.txt").write_text(
        "Sun, 29 Mar 2026 11:30:31 GMT\n"
    )
    new_csv = _FAKE_CSV + b'"3","www.google.com","10.00"\n'
    captured = _patch_get(
        monkeypatch,
        lambda: _FakeResponse(
            status_code=200,
            body=_zip_bytes(new_csv),
            headers={"Last-Modified": "Mon, 29 Jun 2026 09:00:00 GMT"},
        ),
    )

    assert domcop.run(str(tmp_path)) is True
    assert captured["headers"]["If-Modified-Since"] == (
        "Sun, 29 Mar 2026 11:30:31 GMT"
    )

    assert gzip.decompress((tmp_path / "current.csv.gz").read_bytes()) == new_csv
    assert (tmp_path / "current.last-modified.txt").read_text().strip() == (
        "Mon, 29 Jun 2026 09:00:00 GMT"
    )


def test_domcop_rejects_zip_without_csv(tmp_path, monkeypatch):
    from feedcache.sources import domcop

    bad_zip = _zip_bytes(b"not-a-csv-body", name="README.txt")
    _patch_get(
        monkeypatch,
        lambda: _FakeResponse(status_code=200, body=bad_zip),
    )

    with pytest.raises(RuntimeError, match="unexpected zip contents"):
        domcop.run(str(tmp_path))
