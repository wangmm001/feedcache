import csv
import gzip
import io
from unittest.mock import MagicMock

import pytest

_FAKE_PSL_TEXT = """\
// ===BEGIN ICANN DOMAINS===
com
org
net
ru
test
co.uk
uk
// ===END ICANN DOMAINS===

// ===BEGIN PRIVATE DOMAINS===
github.io
// ===END PRIVATE DOMAINS===
"""


def _gzip_bytes(s: str) -> bytes:
    return gzip.compress(s.encode("utf-8"), mtime=0)


def _ok_response(body_bytes: bytes):
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    r.raise_for_status.return_value = None
    r.content = body_bytes
    return r


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
    "https://www.google.com,1000\n"        # → google.com
    "https://youtube.com,1000\n"           # → youtube.com
    "https://en.wikipedia.org,10000\n"     # → wikipedia.org (PSL normalization)
    "https://blog.github.io,10000\n"       # → blog.github.io (github.io is a public suffix)
    ",1000\n"                              # empty origin — skipped
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
    from feedcache.sources.aggregate_top_domains import SOURCES, PSL_URL
    url_by_name = {name: url for name, url, _ in SOURCES}
    return {
        PSL_URL: _gzip_bytes(_FAKE_PSL_TEXT),
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
    assert set(rows[0].keys()) == {"domain", "count", "score", "lists"}

    # google.com in all 5 (RRF K=60):
    # 3/(60+1) + 1/(60+1000000) + 1/(60+1000) ≈ 0.050125
    first = rows[0]
    assert first["domain"] == "google.com"
    assert first["count"] == "5"
    assert first["score"] == "0.050125"
    assert first["lists"] == "cloudflare-radar|crux|majestic|tranco|umbrella"

    # youtube.com in 4 (not majestic):
    # 1/62 + 1/63 + 1/1000060 + 1/1060 ≈ 0.032946
    second = rows[1]
    assert second["domain"] == "youtube.com"
    assert second["count"] == "4"
    assert second["score"] == "0.032946"


def test_aggregate_within_count_tier_higher_score_comes_first(tmp_path, monkeypatch):
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    aggregate_top_domains.run(str(tmp_path))
    rows = _read_output(tmp_path)
    rows_by_count = {}
    for row in rows:
        rows_by_count.setdefault(row["count"], []).append(row)

    count1 = rows_by_count.get("1", [])
    domains_1 = [r["domain"] for r in count1]
    if "tranco-only.test" in domains_1 and "umbrella-only.test" in domains_1:
        i_tranco = domains_1.index("tranco-only.test")
        i_umbrella = domains_1.index("umbrella-only.test")
        assert i_tranco < i_umbrella


def test_aggregate_psl_normalizes_crux_subdomain(tmp_path, monkeypatch):
    """en.wikipedia.org → wikipedia.org (PSL eTLD+1 reduction)."""
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    aggregate_top_domains.run(str(tmp_path))
    rows = _read_output(tmp_path)
    domains = {r["domain"]: r for r in rows}

    # en.wikipedia.org in CrUX must collapse to wikipedia.org
    assert "wikipedia.org" in domains, "wikipedia.org should be the registrable domain"
    assert "en.wikipedia.org" not in domains, \
        "en.wikipedia.org should have been normalized away"
    assert "crux" in domains["wikipedia.org"]["lists"].split("|")


def test_aggregate_psl_preserves_private_suffix_subdomains(tmp_path, monkeypatch):
    """blog.github.io stays as blog.github.io because github.io is itself a
    public suffix (private PSL section). The 'blog' is the user-registered label."""
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    aggregate_top_domains.run(str(tmp_path))
    rows = _read_output(tmp_path)
    domains = {r["domain"]: r for r in rows}

    assert "blog.github.io" in domains, \
        "github.io is a public suffix — 'blog.github.io' is the registrable; must be preserved"


def test_aggregate_crux_origin_scheme_and_www_stripped(tmp_path, monkeypatch):
    """https://www.google.com → google.com (scheme + www stripped before PSL lookup)."""
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    aggregate_top_domains.run(str(tmp_path))
    rows = _read_output(tmp_path)
    by_domain = {r["domain"]: r for r in rows}

    assert "crux" in by_domain["google.com"]["lists"].split("|")


def test_aggregate_idempotent(tmp_path, monkeypatch):
    from feedcache.sources import aggregate_top_domains
    _install_fake_get(monkeypatch, _default_url_map())

    aggregate_top_domains.run(str(tmp_path))
    before = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())
    aggregate_top_domains.run(str(tmp_path))
    after = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())
    assert before == after


def test_aggregate_psl_failure_aborts(tmp_path, monkeypatch):
    """If the PSL can't be fetched, the whole run aborts — no partial output."""
    import requests as real_requests
    from feedcache.sources import aggregate_top_domains
    from feedcache.sources.aggregate_top_domains import PSL_URL

    url_map = _default_url_map()

    def fake_get(url, timeout=None):
        if url == PSL_URL:
            r = MagicMock()
            r.raise_for_status.side_effect = real_requests.HTTPError("500 PSL server down")
            return r
        return _ok_response(url_map.get(url, b""))

    monkeypatch.setattr(aggregate_top_domains.requests, "get", fake_get)

    with pytest.raises(real_requests.HTTPError):
        aggregate_top_domains.run(str(tmp_path))
    assert list(tmp_path.glob("*.csv.gz")) == []


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
