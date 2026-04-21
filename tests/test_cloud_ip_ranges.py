from unittest.mock import MagicMock

import pytest


def _ok(body_bytes):
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    r.raise_for_status.return_value = None
    r.content = body_bytes
    r.text = body_bytes.decode() if isinstance(body_bytes, bytes) else body_bytes
    return r


def test_cloud_ip_ranges_writes_five_files(tmp_path, monkeypatch):
    from feedcache.sources import cloud_ip_ranges as cir

    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        if url == cir.AZURE_CONFIRM_PAGE:
            return _ok(b'<html><a href="https://download.microsoft.com/download/7/1/d/'
                       b'71d86715-5596-4529-9b13-da13a5de5b63/'
                       b'ServiceTags_Public_20260413.json">click</a></html>')
        if "ServiceTags_Public" in url:
            return _ok(b'{"changeNumber": 42, "values": []}')
        if url == cir.AWS_URL:
            return _ok(b'{"syncToken": "abc", "prefixes": []}')
        if url == cir.GCP_URL:
            return _ok(b'{"syncToken": "def", "prefixes": []}')
        if url == cir.CLOUDFLARE_V4_URL:
            return _ok(b"173.245.48.0/20\n103.21.244.0/22\n")
        if url == cir.CLOUDFLARE_V6_URL:
            return _ok(b"2400:cb00::/32\n")
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(cir.requests, "get", fake_get)

    assert cir.run(str(tmp_path)) is True

    dated_dirs = [p for p in tmp_path.iterdir() if p.is_dir() and p.name != "current"]
    assert len(dated_dirs) == 1
    daily_files = sorted(p.name for p in dated_dirs[0].iterdir())
    assert daily_files == [
        "aws.json.gz",
        "azure.json.gz",
        "cloudflare-v4.txt.gz",
        "cloudflare-v6.txt.gz",
        "gcp.json.gz",
    ]
    current_files = sorted(p.name for p in (tmp_path / "current").iterdir())
    assert current_files == daily_files

    # Two-hop Azure: confirmation page then actual JSON
    assert cir.AZURE_CONFIRM_PAGE in calls
    assert any("ServiceTags_Public" in c for c in calls)


def test_cloud_ip_ranges_azure_regex_miss_raises(tmp_path, monkeypatch):
    from feedcache.sources import cloud_ip_ranges as cir

    def fake_get(url, timeout=None):
        if url == cir.AZURE_CONFIRM_PAGE:
            return _ok(b"<html>no json link here</html>")
        return _ok(b"{}")

    monkeypatch.setattr(cir.requests, "get", fake_get)

    with pytest.raises(RuntimeError, match="Could not find Azure ServiceTags JSON URL"):
        cir.run(str(tmp_path))


def test_cloud_ip_ranges_partial_failure_no_commit(tmp_path, monkeypatch):
    from feedcache.sources import cloud_ip_ranges as cir
    import requests

    # AWS fetches OK, GCP fails with HTTPError — nothing should land.
    def fake_get(url, timeout=None):
        if url == cir.AWS_URL:
            return _ok(b'{"prefixes": []}')
        if url == cir.GCP_URL:
            r = MagicMock()
            r.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
            return r
        return _ok(b"{}")

    monkeypatch.setattr(cir.requests, "get", fake_get)

    with pytest.raises(requests.HTTPError):
        cir.run(str(tmp_path))

    # No files persisted
    assert list(tmp_path.rglob("*.gz")) == []


def test_cloud_ip_ranges_idempotent(tmp_path, monkeypatch):
    from feedcache.sources import cloud_ip_ranges as cir

    def fake_get(url, timeout=None):
        if url == cir.AZURE_CONFIRM_PAGE:
            return _ok(b'href="https://download.microsoft.com/download/a/'
                       b'ServiceTags_Public_20260101.json"')
        if "ServiceTags_Public" in url:
            return _ok(b'{"x":1}')
        return _ok(b'{"x":1}')  # same stub for all clouds

    monkeypatch.setattr(cir.requests, "get", fake_get)

    cir.run(str(tmp_path))
    before = sorted((str(p.relative_to(tmp_path)), p.read_bytes()) for p in tmp_path.rglob("*.gz"))
    cir.run(str(tmp_path))
    after = sorted((str(p.relative_to(tmp_path)), p.read_bytes()) for p in tmp_path.rglob("*.gz"))
    assert before == after
