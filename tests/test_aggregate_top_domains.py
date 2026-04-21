import csv
import gzip
import io
from unittest.mock import MagicMock

import pytest


def _gzip_bytes(s: str) -> bytes:
    return gzip.compress(s.encode("utf-8"), mtime=0)


def _ok_response(body_bytes: bytes):
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    r.raise_for_status.return_value = None
    r.content = body_bytes
    return r


# Small fixtures: each source returns a few overlapping domains.
_FAKE_UMBRELLA = _gzip_bytes("1,google.com\n2,youtube.com\n3,umbrella-only.test\n")
_FAKE_TRANCO = _gzip_bytes("1,google.com\n2,youtube.com\n3,tranco-only.test\n")
_FAKE_MAJESTIC = _gzip_bytes(
    "GlobalRank,TldRank,Domain,TLD,RefSubNets,RefIPs\n"
    "1,1,google.com,com,1,1\n"
    "2,2,github.com,com,1,1\n"
)
_FAKE_CLOUDFLARE = _gzip_bytes("domain\ngoogle.com\nyoutube.com\n")
_FAKE_CRUX = _gzip_bytes(
    "origin,rank\n"
    "https://www.google.com,1000\n"
    "https://youtube.com,1000\n"  # no www. prefix
    "https://en.wikipedia.org,10000\n"  # subdomain stays as-is
    ",1000\n"  # empty origin — should be skipped
)


def _install_fake_get(monkeypatch, url_to_body: dict):
    def fake_get(url, timeout=None):
        body = url_to_body.get(url)
        if body is None:
            raise AssertionError(f"unexpected URL: {url}")
        return _ok_response(body)
    import feedcache.sources.aggregate_top_domains as agg
    monkeypatch.setattr(agg.requests, "get", fake_get)


def _default_url_map():
    from feedcache.sources.aggregate_top_domains import SOURCES
    # SOURCES is [(name, url, parser_key)]; build name→url first then map url→body.
    url_by_name = {name: url for name, url, _ in SOURCES}
    return {
        url_by_name["umbrella"]: _FAKE_UMBRELLA,
        url_by_name["tranco"]: _FAKE_TRANCO,
        url_by_name["majestic"]: _FAKE_MAJESTIC,
        url_by_name["cloudflare-radar"]: _FAKE_CLOUDFLARE,
        url_by_name["crux"]: _FAKE_CRUX,
    }


def _read_output(tmp_path):
    current = tmp_path / "current.csv.gz"
    assert current.exists()
    text = gzip.decompress(current.read_bytes()).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def test_aggregate_writes_sorted_by_count_desc_then_domain_asc(tmp_path, monkeypatch):
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    assert aggregate_top_domains.run(str(tmp_path)) is True

    rows = _read_output(tmp_path)
    # google.com is in all 5 lists (umbrella+tranco+majestic+cloudflare+crux) → count=5
    # youtube.com in 4 (not majestic) → count=4
    # github.com in 1 (majestic only), en.wikipedia.org in 1 (crux only),
    # umbrella-only.test in 1, tranco-only.test in 1
    first = rows[0]
    assert first["domain"] == "google.com"
    assert first["count"] == "5"
    assert first["lists"] == "cloudflare-radar|crux|majestic|tranco|umbrella"

    second = rows[1]
    assert second["domain"] == "youtube.com"
    assert second["count"] == "4"
    assert second["lists"] == "cloudflare-radar|crux|tranco|umbrella"

    # Check that lower-count rows are sorted alphabetically among themselves.
    tail_domains = [r["domain"] for r in rows if r["count"] == "1"]
    assert tail_domains == sorted(tail_domains), tail_domains


def test_aggregate_crux_origin_normalization(tmp_path, monkeypatch):
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    aggregate_top_domains.run(str(tmp_path))
    rows = _read_output(tmp_path)
    domains = {row["domain"]: row for row in rows}

    # https://www.google.com in CrUX → stripped to google.com → should merge with
    # google.com in other lists, so CrUX appears in the 'lists' field
    assert "crux" in domains["google.com"]["lists"].split("|")

    # https://youtube.com (no www.) → youtube.com
    assert "crux" in domains["youtube.com"]["lists"].split("|")

    # https://en.wikipedia.org → keeps subdomain (no PSL yet)
    assert "en.wikipedia.org" in domains
    assert domains["en.wikipedia.org"]["lists"] == "crux"


def test_aggregate_idempotent(tmp_path, monkeypatch):
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    aggregate_top_domains.run(str(tmp_path))
    before = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())
    aggregate_top_domains.run(str(tmp_path))
    after = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())
    assert before == after


def test_aggregate_upstream_failure_writes_nothing(tmp_path, monkeypatch):
    import requests as real_requests
    from feedcache.sources import aggregate_top_domains

    # Mock: first 4 OK, crux 500
    url_map = _default_url_map()
    from feedcache.sources.aggregate_top_domains import SOURCES
    url_by_name = {name: url for name, url, _ in SOURCES}

    def fake_get(url, timeout=None):
        if url == url_by_name["crux"]:
            r = MagicMock()
            r.raise_for_status.side_effect = real_requests.HTTPError("500 Server Error")
            return r
        body = url_map.get(url)
        if body is None:
            raise AssertionError(f"unexpected URL: {url}")
        return _ok_response(body)

    monkeypatch.setattr(aggregate_top_domains.requests, "get", fake_get)

    with pytest.raises(real_requests.HTTPError):
        aggregate_top_domains.run(str(tmp_path))

    # No files produced
    assert list(tmp_path.glob("*.csv.gz")) == []
