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


# Fixtures: include explicit ranks for ordinal sources; CrUX has bucket rank.
_FAKE_UMBRELLA = _gzip_bytes("1,google.com\n2,youtube.com\n999000,umbrella-only.test\n")
_FAKE_TRANCO = _gzip_bytes("1,google.com\n3,youtube.com\n500,tranco-only.test\n")
_FAKE_MAJESTIC = _gzip_bytes(
    "GlobalRank,TldRank,Domain,TLD,RefSubNets,RefIPs\n"
    "1,1,google.com,com,1,1\n"
    "100,1,github.com,com,1,1\n"
)
_FAKE_CLOUDFLARE = _gzip_bytes("domain\ngoogle.com\nyoutube.com\n")
_FAKE_CRUX = _gzip_bytes(
    "origin,rank\n"
    "https://www.google.com,1000\n"
    "https://youtube.com,1000\n"
    "https://en.wikipedia.org,10000\n"
    ",1000\n"
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
    return list(csv.DictReader(io.StringIO(text)))


def test_aggregate_has_score_column_and_sorts_by_count_then_score(tmp_path, monkeypatch):
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    assert aggregate_top_domains.run(str(tmp_path)) is True

    rows = _read_output(tmp_path)
    # Header check: 4 cols including 'score'
    assert set(rows[0].keys()) == {"domain", "count", "score", "lists"}

    # google.com in all 5: ranks 1/1/1 (umbrella/tranco/majestic) + 1M (cloudflare) + 1000 (crux)
    # score = 1 + 1 + 1 + 1e-6 + 1e-3 = 3.001001
    first = rows[0]
    assert first["domain"] == "google.com"
    assert first["count"] == "5"
    assert first["score"] == "3.001001"
    assert first["lists"] == "cloudflare-radar|crux|majestic|tranco|umbrella"

    # youtube.com in 4 lists (not majestic): umbrella=2, tranco=3, cloudflare=1M, crux=1000
    # score = 0.5 + 0.333333 + 1e-6 + 1e-3 = 0.834334
    second = rows[1]
    assert second["domain"] == "youtube.com"
    assert second["count"] == "4"
    assert second["score"] == "0.834334"


def test_aggregate_within_count_tier_higher_score_comes_first(tmp_path, monkeypatch):
    """Two domains with same count but different real ranks — higher-score should win."""
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    aggregate_top_domains.run(str(tmp_path))
    rows = _read_output(tmp_path)
    rows_by_count = {}
    for row in rows:
        rows_by_count.setdefault(row["count"], []).append(row)

    # Among count=1 domains: tranco-only.test (rank 500) should come before
    # umbrella-only.test (rank 999000) because it has higher score.
    count1 = rows_by_count.get("1", [])
    domains_1 = [r["domain"] for r in count1]
    if "tranco-only.test" in domains_1 and "umbrella-only.test" in domains_1:
        i_tranco = domains_1.index("tranco-only.test")
        i_umbrella = domains_1.index("umbrella-only.test")
        assert i_tranco < i_umbrella, (
            f"tranco-only.test (score ~1/500) should come before "
            f"umbrella-only.test (score ~1/999000); got order: {domains_1}"
        )


def test_aggregate_crux_origin_normalization(tmp_path, monkeypatch):
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    aggregate_top_domains.run(str(tmp_path))
    rows = _read_output(tmp_path)
    by_domain = {r["domain"]: r for r in rows}

    # https://www.google.com → google.com, merges with other lists
    assert "crux" in by_domain["google.com"]["lists"].split("|")

    # https://en.wikipedia.org stays as-is
    assert "en.wikipedia.org" in by_domain
    assert by_domain["en.wikipedia.org"]["lists"] == "crux"


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
    from feedcache.sources.aggregate_top_domains import SOURCES

    url_map = _default_url_map()
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

    assert list(tmp_path.glob("*.csv.gz")) == []
